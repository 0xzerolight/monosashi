"""The adapter runner: the subprocess contract, faults, and offset repair."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from monosashi import runner
from monosashi.predictions import PredictedUnit, dump_predictions, load_predictions
from monosashi.runner import AdapterSpec, describe, load_registry, repair, run, run_to_dir

FAKE = AdapterSpec(
    "fake", (sys.executable, str(Path(__file__).parent / "fixtures" / "fake_adapter.py")), {}, True
)


def test_describe_reads_the_adapter_description() -> None:
    d = describe(FAKE)
    assert (d.name, d.partition, d.fields) == ("fake", True, ())


def test_faults_are_recorded_and_the_run_continues(tmp_path: Path) -> None:
    inputs = [("a", "食べた"), ("b", "CRASH"), ("c", "ERROR"), ("d", "HANG"), ("e", "寝た")]
    with (tmp_path / "stderr.log").open("w+", encoding="utf-8") as log:
        out = {p.id: p for p in run(FAKE, inputs, log, timeout=3)}
        log.seek(0)
        logged = log.read()
    assert [u.surface for u in out["a"].units] == ["食", "べ", "た"]
    assert out["b"].status == "crash"
    assert out["c"].status == "crash" and "planted" in logged
    assert out["d"].status == "timeout"
    assert out["e"].status == "ok" and len(out["e"].units) == 2  # restarted after the hang


def test_a_stray_stdout_line_garbles_one_record_and_the_run_continues(tmp_path: Path) -> None:
    inputs = [("a", "食べた"), ("b", "NOISE"), ("c", "寝た"), ("d", "EXTRA"), ("e", "見た")]
    with (tmp_path / "stderr.log").open("w+", encoding="utf-8") as log:
        out = {p.id: p for p in run(FAKE, inputs, log, timeout=10)}
        log.seek(0)
        logged = log.read()
    assert out["b"].status == "garbled" and "not a JSON object" in logged  # NOISE: not JSON
    assert out["d"].status == "garbled" and "another id" in logged  # EXTRA: a JSON object without the id
    # The adapter was restarted, so the next records get their own answers, not the stray ones.
    assert (out["c"].status, [u.surface for u in out["c"].units]) == ("ok", ["寝", "た"])
    assert (out["e"].status, [u.surface for u in out["e"].units]) == ("ok", ["見", "た"])


def test_a_non_numeric_ms_is_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def ask(self: object, request: dict[str, str], timeout: float) -> dict[str, Any]:
        return {"id": request["id"], "units": [{"start": 0, "end": 1, "surface": "a"}], "ms": "fast"}

    monkeypatch.setattr(runner._Process, "ask", ask)
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as log:
        out = list(run(FAKE, [("a", "a")], log))
    assert (out[0].status, out[0].ms) == ("ok", None)
    dump_predictions(tmp_path / "p.jsonl", out)  # would fail on round("fast", 3)


def test_wrong_offsets_are_repaired_from_surfaces(tmp_path: Path) -> None:
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as log:
        out = list(run(FAKE, [("a", "OFFSET𠮷田"), ("b", "JUNK")], log, timeout=10))
    assert out[0].status == "repaired"
    assert [(u.start, u.end, u.surface) for u in out[0].units][-2:] == [(6, 7, "𠮷"), (7, 8, "田")]
    assert out[1].status == "garbled"


def test_repair_finds_repeated_surfaces_in_order() -> None:
    text = "はははは"
    units = [PredictedUnit(0, 2, "はは"), PredictedUnit(3, 5, "はは")]  # the second one's offsets are wrong
    kept, status = repair(text, units)
    assert [(u.start, u.end) for u in kept] == [(0, 2), (2, 4)]
    assert status == "repaired"


def test_repair_drops_a_right_span_that_overlaps_the_previous_unit() -> None:
    # べた is where it says it is, inside 食べた: dropped, not moved into the second 食べた.
    kept, status = repair("食べた。食べた", [PredictedUnit(0, 3, "食べた"), PredictedUnit(1, 3, "べた")])
    assert [(u.start, u.end) for u in kept] == [(0, 3)]
    assert status == "garbled"


def test_run_to_dir_writes_the_run(tmp_path: Path) -> None:
    run_to_dir(FAKE, [("a", "食べた")], tmp_path / "fake")
    assert (tmp_path / "fake" / "describe.json").exists()
    assert [p.id for p in load_predictions(tmp_path / "fake" / "predictions.jsonl")] == ["a"]


def test_registry_lists_the_light_adapters() -> None:
    assert {"fugashi-unidic-lite", "sudachi-a", "sudachi-c"} <= set(load_registry())

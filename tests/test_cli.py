from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from helpers import hajimete_shimatta, record
from monosashi import cli, runner
from monosashi.cli import main
from monosashi.jmdict import repo_root
from monosashi.predictions import load_predictions
from monosashi.schema import Source, dump_records, load_records
from monosashi.sources import Sentence, dump_sentences

FIXTURES = Path(__file__).parent / "fixtures"


def test_validate_exits_zero_on_clean_files(tmp_path: Path, index_path: Path) -> None:
    path = tmp_path / "ok.jsonl"
    path.write_text(json.dumps(hajimete_shimatta(), ensure_ascii=False) + "\n", encoding="utf-8")
    assert main(["--index", str(index_path), "validate", str(path)]) == 0


def test_validate_exits_one_and_prints_issues(
    tmp_path: Path, index_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = hajimete_shimatta()
    data["units"][0]["entries"] = [1999999]
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    assert main(["--index", str(index_path), "validate", str(path)]) == 1
    assert "[entries-exist]" in capsys.readouterr().out


def test_validate_prints_advisories_without_failing(
    tmp_path: Path, index_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = record(
        "三歳",
        [{"start": 0, "end": 2, "surface": "三歳", "kind": "word", "entries": [1294940], "form": "歳",
          "reading": "さんさい", "form_reading": "さい", "split_points": [1]}],
    )  # fmt: skip
    path = tmp_path / "note.jsonl"
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    assert main(["--index", str(index_path), "validate", str(path)]) == 0
    captured = capsys.readouterr()
    assert "[counter-whole-entry]" in captured.out
    assert "0 issue(s)" in captured.err


def test_candidates_json_normalizes_input(index_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--index", str(index_path), "candidates", "--json", "すげ～"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["text"] == "すげ〜"


def test_lookup_prints_entries(index_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--index", str(index_path), "jmdict", "lookup", "一人暮らし"]) == 0
    assert "jmdict 1613340" in capsys.readouterr().out


def test_lookup_lists_readings_in_jmdict_order_with_common_starred(
    index_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SPEC.md §5's free-variant rule takes the first common reading, else the first listed."""
    assert main(["--index", str(index_path), "jmdict", "lookup", "一日"]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if x.startswith("jmdict 1576260 "))
    assert "一日【いちにち*】, 一日【いちじつ】" in line


def test_lookup_shows_spelling_tags(index_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--index", str(index_path), "jmdict", "lookup", "すご〜い"]) == 0
    assert "すご〜い(sk)【すご〜い】" in capsys.readouterr().out


def test_lookup_shows_dialect_tags(index_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--index", str(index_path), "jmdict", "lookup", "おおきに"]) == 0
    assert "thanks a lot (int; uk ksb)" in capsys.readouterr().out


def test_lookup_prints_senses(index_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--index", str(index_path), "jmdict", "lookup", "ならない"]) == 0
    assert "must" in capsys.readouterr().out  # sense 3 of 2083990, past the display gloss


def test_candidates_print_senses(index_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--index", str(index_path), "candidates", "ならない"]) == 0
    lines = capsys.readouterr().out.splitlines()
    first_sense = next(i for i, line in enumerate(lines) if line.startswith("2083990: 1) "))
    assert first_sense > max(i for i, line in enumerate(lines) if line.startswith("["))
    assert "3) must ...; have to ...; ought to ... (exp)" in lines[first_sense]
    assert main(["--index", str(index_path), "candidates", "--json", "ならない"]) == 0
    rows = json.loads(capsys.readouterr().out)["candidates"]
    (row,) = [r for r in rows if r["seq"] == 2083990]
    assert row["senses"][2] == {"pos": ["exp"], "glosses": ["must ...", "have to ...", "ought to ..."]}


def test_tag_prints_hints(index_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--index", str(index_path), "tag", "食べちゃった"]) == 0
    assert "[0:6] 食べちゃった contraction" in capsys.readouterr().out


def test_select_writes_the_selection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from monosashi.schema import Source
    from monosashi.sources import Hint, Sentence, dump_sentences

    pool = tmp_path / "tagged.jsonl"
    dump_sentences(
        pool,
        [
            Sentence(f"t{i}", f"食べた{i:02d}", Source("tatoeba", str(i), "CC-BY-2.0-FR", f"Tatoeba sentence #{i} by u{i} (export v)"), "conversation",
                     "open", hints=(Hint("heteronym", 0, 3),))
            for i in range(5)
        ],
    )  # fmt: skip
    out = tmp_path / "selection"
    assert main(["select", "--pool", str(pool), "--out", str(out)]) == 0
    assert (out / "core.jsonl").exists() and (out / "reserve.jsonl").exists()
    assert "| heteronym |" in (out / "summary.md").read_text(encoding="utf-8")


def test_run_and_score_the_fake_adapter(
    tmp_path: Path, index_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = runner.AdapterSpec("fake", (sys.executable, str(FIXTURES / "fake_adapter.py")), {}, True)
    monkeypatch.setattr(runner, "load_registry", lambda path=None: {"fake": fake})
    gold = str(FIXTURES / "spec-examples.jsonl")
    examples = len(list(load_records(Path(gold))))
    runs = tmp_path / "runs"
    assert main(["run", "fake", "--gold", gold, "--out", str(runs)]) == 0
    predictions = list(load_predictions(runs / "fake" / "predictions.jsonl"))
    assert len(predictions) == examples and {p.status for p in predictions} == {"ok"}
    report = tmp_path / "report.md"
    score = ["score", str(runs / "fake"), "--gold", gold, "--samples", "20", "--out", str(report)]
    assert main(["--index", str(index_path), *score]) == 0
    text = report.read_text(encoding="utf-8")
    assert f"Gold records: {examples}." in text and "| fake |" in text
    assert text in capsys.readouterr().out


def _blind_selection(path: Path, sentences: list[Sentence]) -> str:
    dump_sentences(path, sentences)
    return str(path)


def test_label_prepare_bundle_limit_draws_from_every_part_of_the_selection(
    tmp_path: Path, index_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_labels_dir", lambda: tmp_path / "labels")
    monkeypatch.chdir(tmp_path)
    by_slice = [
        Sentence(f"s{i:03d}", f"食べた{i:03d}", Source("tatoeba", str(i), "CC-BY-2.0-FR", "x"), "conversation",
                 "open" if i < 60 else "seed")
        for i in range(100)
    ]  # fmt: skip
    selection = _blind_selection(tmp_path / "core.jsonl", by_slice)
    args = ["--index", str(index_path), "label", "prepare", "pilot", "--input", selection]
    assert main([*args, "--bundle", "bundle", "--limit", "50"]) == 0
    assert json.loads(capsys.readouterr().out)["bundle"] == str((tmp_path / "bundle").resolve())
    ids = json.loads((tmp_path / "labels" / "pilot" / "blind.json").read_text(encoding="utf-8"))["ids"]
    slices = {s.id: s.slice for s in by_slice}
    assert len(ids) == 50 and {slices[real] for real in ids.values()} == {"open", "seed"}


def test_label_collect_restores_a_blind_run(
    tmp_path: Path, index_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_labels_dir", lambda: tmp_path / "labels")
    examples = list(load_records(FIXTURES / "spec-examples.jsonl"))[:5]
    sentences = [Sentence(f"core-{i}", r.text, Source("tatoeba", str(i), "CC-BY-2.0-FR", "x"), "literature", "open")
                 for i, r in enumerate(examples)]  # fmt: skip
    selection = _blind_selection(tmp_path / "core.jsonl", sentences)
    bundle = tmp_path / "bundle"
    common = ["--input", selection, "--bundle", str(bundle)]
    assert main(["--index", str(index_path), "label", "prepare", "pilot", *common, "--batch-size", "2"]) == 0
    gold = {r.text: r.units for r in examples}
    for path in sorted(bundle.glob("*/batch-*.input.jsonl")):
        labels = path.parent / "labels" / path.name.replace(".input", "")
        dump_records(labels, [replace(r, units=gold[r.text]) for r in load_records(path)])
    assert main(["--index", str(index_path), "label", "collect", "pilot", *common]) == 0
    assert "0 issue(s)" in capsys.readouterr().err
    collected = {
        r.id: r
        for path in (tmp_path / "labels" / "pilot" / "labels-A").glob("*.jsonl")
        for r in load_records(path)
    }
    assert {(r.id, r.text, r.register, r.units) for r in collected.values()} == {
        (s.id, s.text, "literature", gold[s.text]) for s in sentences
    }


def test_label_prepare_refuses_a_bundle_in_the_repo(
    tmp_path: Path, index_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_labels_dir", lambda: tmp_path / "labels")
    monkeypatch.chdir(repo_root())
    selection = _blind_selection(
        tmp_path / "core.jsonl",
        [Sentence("s1", "食べた", Source("t", "1", "MIT", "x"), "conversation", "open")],
    )
    with pytest.raises(SystemExit, match=r"nothing prepared: .*inside the repository"):
        main(
            [
                "--index",
                str(index_path),
                "label",
                "prepare",
                "pilot",
                "--input",
                selection,
                "--bundle",
                "t7-bundles",
            ]
        )
    assert not (repo_root() / "t7-bundles").exists()


def test_label_compare_without_tools_says_what_it_leaves_out(
    tmp_path: Path, index_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_labels_dir", lambda: tmp_path / "labels")
    examples = list(load_records(FIXTURES / "spec-examples.jsonl"))[:2]
    for side in "AB":
        (tmp_path / "labels" / "r" / f"labels-{side}").mkdir(parents=True)
        dump_records(tmp_path / "labels" / "r" / f"labels-{side}" / "batch-001.jsonl", examples)
    assert main(["--index", str(index_path), "label", "compare", "r"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["records"] == 2
    assert "no --tools: no tools items, and the spot draw differs" in captured.err

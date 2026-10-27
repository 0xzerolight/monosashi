"""The report on two hand-built runs: a partition tool and a content-only tool."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from monosashi import SPEC_VERSION
from monosashi.jmdict import Dictionary
from monosashi.predictions import Description, PredictedUnit, Prediction
from monosashi.report import render
from monosashi.schema import Record, Unit, load_records
from monosashi.score import METRICS, Scorer, ToolScores, score_tool

RECORDS = list(load_records(Path(__file__).parent / "fixtures" / "spec-examples.jsonl"))
FULL = Description("full", "1", "test", "2026", True, ("form", "reading", "form_reading", "entries", "kind"))
CARDS = Description("cards", "1", "test", "2026", False, ("form", "form_reading"))


def _unit(u: Unit) -> PredictedUnit:
    return PredictedUnit(u.start, u.end, u.surface, u.form, u.reading, u.form_reading, u.entries, u.kind)


def _lines(text: str, title: str) -> list[str]:
    """The lines under ``## title``, up to the next section."""
    lines = text.splitlines()
    start = lines.index(f"## {title}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1 : end]


def _section(text: str, title: str) -> list[list[str]]:
    """The rows of the table under ``## title``, header first, cells stripped."""
    return [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in _lines(text, title)
        if line.startswith("| ")
    ]


def _as(record: Record, slice_: str, corpus: str, register: str | None = None) -> Record:
    return replace(
        record,
        slice=slice_,
        source=replace(record.source, corpus=corpus),
        register=register or record.register,
    )


def _perfect(scorer: Scorer, name: str, description: Description, records: list[Record]) -> ToolScores:
    predictions = [Prediction(r.id, tuple(map(_unit, r.units))) for r in records]
    return score_tool(scorer, name, description, records, predictions)


def test_render_shows_missing_fields_intervals_and_leaves_seeds_out(dictionary: Dictionary) -> None:
    scorer = Scorer(dictionary)
    records = [replace(RECORDS[0], slice="seed"), *RECORDS[1:]]
    full = score_tool(
        scorer, "full", FULL, records, [Prediction(r.id, tuple(map(_unit, r.units))) for r in records]
    )
    cards = score_tool(
        scorer,
        "cards",
        CARDS,
        records,
        [Prediction(r.id, tuple(_unit(u) for u in r.units if u.is_content)) for r in records],
    )
    text = render(scorer, [full, cards], samples=50)

    header, *rows = _section(text, "Overall")
    cell = {row[0]: dict(zip(header, row, strict=True)) for row in rows}
    assert header[1:-2] == [METRICS[m] for m in METRICS]  # tiled form and form_reading included
    for metric in ("card", "junk", "seg", "content"):
        assert "(" in cell["full"][METRICS[metric]], metric  # a bootstrap interval
    assert "(" not in cell["full"][METRICS["form"]]
    # The content-only tool has no partition, readings or ids: those cells are empty.
    for column in ("seg", "seg_lenient", "reading", "reading_tiled", "entry"):
        assert cell["cards"][METRICS[column]] == "–", column
    assert cell["cards"]["entry ids not in the pin"] == "–"
    assert cell["full"]["entry ids not in the pin"] == "0"
    assert "(" in cell["cards"][METRICS["card"]] and "(" in cell["cards"][METRICS["content"]]

    registers = {row[0] for row in _section(text, "By register (seeds left out)")[1:]}
    assert registers == {f"conversation ({len(records) - 1})"}
    slices = {row[0] for row in _section(text, "By slice")[1:]}
    assert slices == {"seed (1)", f"synthetic ({len(records) - 1})"}


def test_seeds_get_their_own_table_and_registers_state_their_composition(dictionary: Dictionary) -> None:
    scorer = Scorer(dictionary)
    records = [
        _as(RECORDS[0], "seed", "ichiran", "comic"),
        _as(RECORDS[1], "seed", "jiten", "game-net"),
        _as(RECORDS[2], "seed", "jiten", "game-net"),
        _as(RECORDS[3], "open", "tatoeba"),
        _as(RECORDS[4], "plain", "tatoeba"),
        *RECORDS[5:],  # synthetic, conversation, corpus spec-examples
    ]
    synthetic = len(records) - 5
    text = render(scorer, [_perfect(scorer, "full", FULL, records)], samples=20)

    assert text.splitlines()[0] == f"# Results (spec {SPEC_VERSION})"
    assert text.splitlines()[2].startswith(f"Gold records: {len(records)}. Seeds: 3,")
    assert "measured inside each adapter, overhead included" in text.splitlines()[2]
    overall = _lines(text, "Overall")
    assert f"{len(records) - 3} records, seeds left out." in overall
    assert f"{len(records)} records" not in "\n".join(overall)
    seeds = {row[0] for row in _section(text, "Seed suites")[1:]}
    assert seeds == {"ichiran (1)", "jiten (2)"}

    header, *rows = _section(text, "By register (seeds left out)")
    assert header[:3] == ["", "slices", "sources"]
    composition = {row[0]: (row[1], row[2]) for row in rows}
    assert composition == {
        f"conversation ({synthetic + 2})": (
            f"synthetic {synthetic}, open 1, plain 1",
            f"spec-examples {synthetic}, tatoeba 2",
        )
    }
    slices = {row[0] for row in _section(text, "By slice")[1:]}
    assert slices == {"open (1)", "plain (1)", "seed (3)", f"synthetic ({synthetic})"}
    for phrase in ("threshold", "decision", "adopt", "contribute"):
        assert phrase not in text.lower(), phrase


def test_a_gold_set_of_seeds_only_renders(dictionary: Dictionary) -> None:
    scorer = Scorer(dictionary)
    records = [_as(r, "seed", "ichiran") for r in RECORDS]
    text = render(scorer, [_perfect(scorer, "full", FULL, records)], samples=20)
    assert "No non-seed records." in _lines(text, "Overall")
    assert {row[0] for row in _section(text, "Seed suites")[1:]} == {f"ichiran ({len(records)})"}


def test_the_tools_table_notes_jitens_setup(dictionary: Dictionary) -> None:
    scorer = Scorer(dictionary)
    jiten = Description("jiten", "1", "test", "2026", True, ("form", "form_reading", "entries", "kind"))
    text = render(
        scorer,
        [_perfect(scorer, "full", FULL, RECORDS), _perfect(scorer, "jiten", jiten, RECORDS)],
        samples=20,
    )
    header, *rows = _section(text, "Tools")
    notes = {row[0]: dict(zip(header, row, strict=True))["notes"] for row in rows}
    assert notes["full"] == ""
    assert "widens ASCII digits before placing words" in notes["jiten"]
    assert "without jiten.moe's corpus frequency ranks" in notes["jiten"]

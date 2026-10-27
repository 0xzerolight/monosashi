"""Labeling: batches, blind bundles, agreement, the queue, merging and the review loop."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from monosashi import SPEC_VERSION
from monosashi.jmdict import Dictionary, repo_root
from monosashi.label import batches, blind
from monosashi.label.compare import (
    SPOT_COUNT,
    audit_ids,
    compare,
    compare_record,
    dump_queue,
    kinds_agree,
    load_queue,
    tool_items,
)
from monosashi.label.merge import (
    Decision,
    decision_from_dict,
    load_all_decisions,
    load_decisions,
    merge,
    merge_record,
)
from monosashi.predictions import PredictedUnit, Prediction
from monosashi.review import render_item, review
from monosashi.schema import REGISTERS, SLICES, Label, Record, Source, Unit, dump_records, load_records
from monosashi.sources import Hint, Sentence

EXAMPLES = {r.id: r for r in load_records(Path(__file__).parent / "fixtures" / "spec-examples.jsonl")}


def _units(r: Record, i: int, **changes: object) -> tuple[Unit, ...]:
    units = list(r.units)
    units[i] = replace(units[i], **changes)  # type: ignore[arg-type]
    return tuple(units)


def test_identical_labelings_agree() -> None:
    r = EXAMPLES["spec-01"]
    assert compare_record(r, r) == []


def test_a_field_difference_queues_that_unit_only() -> None:
    a = EXAMPLES["spec-15"]  # こっち|の|方 (ほう)
    b = replace(a, units=_units(a, 2, entries=(1516925,), reading="かた", form_reading="かた"))
    (item,) = compare_record(a, b)
    assert (item.type, item.start, item.end) == ("field", 4, 5)
    assert item.fields == ("entries", "reading", "form_reading")


def test_a_boundary_difference_queues_one_region() -> None:
    a = EXAMPLES["spec-07"]  # そう|です·か
    joined = Unit(0, 5, "そうですか", "expression", (2137720,), "そうですか", "そうですか", "そうですか")
    b = replace(a, units=(joined,))
    (item,) = compare_record(a, b)
    assert (item.type, item.start, item.end, len(item.a), len(item.b)) == ("boundary", 0, 5, 2, 1)


def test_agreement_is_counted_per_unit() -> None:
    a = [EXAMPLES["spec-01"], EXAMPLES["spec-15"]]
    b = [EXAMPLES["spec-01"], replace(a[1], units=_units(a[1], 2, form_reading="かた"))]
    result = compare(a, b, audit_share=0.0)
    s = result.summary()
    assert (s["records"], s["records_agreed"], s["units"], s["units_agreed"]) == (2, 1, 8, 7)
    assert s["field_disagreements"] == {"form_reading": 1}


def test_audit_draw_is_exactly_a_tenth_and_reproducible() -> None:
    ids = [f"r{i}" for i in range(2000)]
    first = audit_ids(ids)
    assert first == audit_ids(reversed(ids))
    assert len(first) == 200


def test_tools_queue_agreed_units_most_tools_miss() -> None:
    r = EXAMPLES["spec-02"]  # 食べちゃった, one unit
    split = Prediction(r.id, (PredictedUnit(0, 2, "食べ"), PredictedUnit(2, 6, "ちゃった")))
    whole = Prediction(r.id, (PredictedUnit(0, 6, "食べちゃった"),))
    assert tool_items(r, r, [{r.id: split}, {r.id: split}, {r.id: whole}], quorum=2)[0].note == "1/3 tools"
    assert tool_items(r, r, [{r.id: whole}, {r.id: whole}, {r.id: split}], quorum=2) == []


def test_a_garbled_or_stale_prediction_reproduces_no_unit() -> None:
    r = EXAMPLES["spec-02"]  # 食べちゃった, one unit
    ok = Prediction(r.id, (PredictedUnit(0, 6, "食べちゃった"),))
    garbled = replace(ok, status="garbled")  # the units a garbled record kept
    stale = Prediction(r.id, (PredictedUnit(0, 6, "たべちゃった"),))  # a run made on older text
    for failed in (garbled, stale):
        (item,) = tool_items(r, r, [{r.id: ok}, {r.id: failed}], quorum=2)
        assert item.note == "1/2 tools"


def test_merge_applies_decisions() -> None:
    a = EXAMPLES["spec-07"]
    joined = Unit(0, 5, "そうですか", "expression", (2137720,), "そうですか", "そうですか", "そうですか")
    b = replace(a, units=(joined,))
    items = compare_record(a, b)
    assert merge_record(a, b, items, {}) is None
    take_b = merge_record(a, b, items, {items[0].id: Decision(items[0].id, "b")})
    assert take_b is not None and take_b.units == (joined,) and take_b.label.status == "adjudicated"
    take_a = merge_record(a, b, items, {items[0].id: Decision(items[0].id, "a")})
    assert take_a is not None and take_a.units == a.units


def test_merge_reports_waiting_records() -> None:
    a = [EXAMPLES["spec-15"]]
    b = [replace(a[0], units=_units(a[0], 2, form_reading="かた"))]
    items = compare(a, b, audit_share=0.0).items
    merged, waiting = merge(a, b, items, {})
    assert (merged, waiting) == ([], ["spec-15"])


def test_review_records_decisions_and_resumes(tmp_path: Path) -> None:
    a = EXAMPLES["spec-15"]
    b = replace(a, units=_units(a, 2, form_reading="かた"))
    queue = tmp_path / "queue.jsonl"
    queue.write_text(
        json.dumps(compare_record(a, b)[0].to_dict(), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    decisions = tmp_path / "decisions.jsonl"
    answers = iter(["x", "a"])
    shown: list[str] = []
    assert review(queue, decisions, {a.id: a.text}, ask=lambda _: next(answers), say=shown.append) == 1
    assert load_decisions(decisions)[f"{a.id}:4-5:field"].choice == "a"
    assert "【方】" in "\n".join(shown)
    assert review(queue, decisions, {a.id: a.text}, ask=lambda _: "q", say=shown.append) == 0


def test_prepare_writes_skeletons_and_sheets(tmp_path: Path, dictionary: Dictionary) -> None:
    from monosashi.schema import Source

    s = Sentence("t-1", "食べてみた", Source("t", "1", "CC-BY-SA-4.0", "x"), "conversation", "open",
                 hints=(Hint("te-auxiliary", 0, 5),))  # fmt: skip
    names = batches.prepare([s, replace(s, id="t-2")], tmp_path, dictionary, batch_size=1)
    assert names == ["batch-001", "batch-002"]
    skeleton = json.loads((tmp_path / "batch-001.input.jsonl").read_text(encoding="utf-8"))
    assert skeleton["units"] == [] and skeleton["label"]["status"] == "draft"
    sheet = (tmp_path / "batch-001.sheets.md").read_text(encoding="utf-8")
    assert "[0:5] 食べてみた → te-auxiliary" in sheet and "chain=-て,-みる,-た" in sheet


def test_split_points_are_merged_not_compared() -> None:
    a = EXAMPLES["spec-01"]
    b = replace(a, units=_units(a, 2, split_points=(4, 5)))
    assert compare_record(a, b) == []
    merged = merge_record(a, b, [], {})
    assert merged is not None and merged.units[2].split_points == (4, 5)


def test_merge_never_puts_targets_on_a_function_unit() -> None:
    a = EXAMPLES["spec-15"]  # こっち|の|方
    b = replace(a, units=_units(a, 1, kind="word", entries=(1469800,), form="の", reading="の", form_reading="の",
                                targets=("heteronym",)))  # fmt: skip
    (item,) = compare_record(a, b)
    merged = merge_record(a, b, [item], {item.id: Decision(item.id, "a")})
    assert merged is not None and merged.units[1].kind == "particle" and merged.units[1].targets == ()


def test_ok_is_refused_for_a_field_or_boundary_item() -> None:
    a = EXAMPLES["spec-15"]
    b = replace(a, units=_units(a, 2, form_reading="かた"))
    (item,) = compare_record(a, b)
    with pytest.raises(ValueError, match="not ok"):
        merge_record(a, b, [item], {item.id: Decision(item.id, "ok")})


def test_heteronym_targets_are_ruled_on_not_unioned() -> None:
    a = EXAMPLES["spec-15"]
    b = replace(a, units=_units(a, 2, targets=()))
    (item,) = compare_record(a, b)
    assert item.fields == ("targets",)
    merged = merge_record(a, b, [item], {item.id: Decision(item.id, "b")})
    assert merged is not None and merged.units[2].targets == ()


def test_agreed_units_that_fail_validation_are_queued(dictionary: Dictionary) -> None:
    a = EXAMPLES["spec-02"]
    broken = replace(a, units=_units(a, 0, chain=("-ちゃう",)))  # missing -た: chain-deinflects fails
    result = compare([broken], [broken], dictionary=dictionary, audit_share=0.0)
    assert [i.type for i in result.items] == ["validator"]
    assert "chain" in result.items[0].note


def test_tools_check_agreed_units_of_disputed_records_too() -> None:
    a = EXAMPLES["spec-01"]
    b = replace(a, units=_units(a, 0, form_reading="かれ"))  # a dispute on 彼女
    nothing = {a.id: Prediction(a.id, ())}
    result = compare([a], [b], tools={"t1": nothing, "t2": nothing}, quorum=2, audit_share=0.0)
    items = result.items
    assert result.tools_flagged == sum(i.type == "tools" for i in items)
    assert {i.type for i in items} == {"field", "tools"}
    assert all(i.start != 0 for i in items if i.type == "tools")  # 彼女 is disputed, not a tools item


def test_records_labeled_by_one_side_only_are_refused() -> None:
    with pytest.raises(ValueError, match="B only"):
        compare([EXAMPLES["spec-01"]], [EXAMPLES["spec-01"], EXAMPLES["spec-02"]])


def test_queue_round_trips(tmp_path: Path) -> None:
    a = EXAMPLES["spec-07"]
    joined = Unit(0, 5, "そうですか", "expression", (2137720,), "そうですか", "そうですか", "そうですか")
    items = compare_record(a, replace(a, units=(joined,)))
    dump_queue(tmp_path / "q.jsonl", items)
    assert load_queue(tmp_path / "q.jsonl") == items


def test_review_refuses_a_bad_edit_and_takes_only_a_or_b_when_flagging(
    tmp_path: Path, dictionary: Dictionary
) -> None:
    from monosashi.review import decision_checker

    a = EXAMPLES["spec-15"]
    b = replace(a, units=_units(a, 2, form_reading="かた"))
    items = compare_record(a, b)
    queue = tmp_path / "queue.jsonl"
    dump_queue(queue, items)
    check = decision_checker([a], [b], items, dictionary)
    decisions = tmp_path / "decisions.jsonl"
    answers = iter(["e", '[{"start": 0}]', "e", '[{"start": 0, "end": 3, "surface": "こっち", "kind": "word"}]',
                    "f", "is this right?", "ok", "f", "again", "b"])  # fmt: skip
    shown: list[str] = []
    assert (
        review(queue, decisions, {a.id: a.text}, ask=lambda _: next(answers), say=shown.append, check=check)
        == 1
    )
    assert sum("refused" in line for line in shown) == 2  # not a unit, then outside the item
    d = load_decisions(decisions)[items[0].id]
    assert (d.choice, d.flag) == ("b", "again")


def test_review_stops_cleanly_on_end_of_input(tmp_path: Path) -> None:
    a = EXAMPLES["spec-15"]
    b = replace(a, units=_units(a, 2, form_reading="かた"))
    queue = tmp_path / "queue.jsonl"
    dump_queue(queue, compare_record(a, b))

    def eof(_: str) -> str:
        raise EOFError

    assert review(queue, tmp_path / "d.jsonl", {a.id: a.text}, ask=eof, say=lambda _: None) == 0


# Queue, merge and review rulings for spec 0.3: every target compared, every unit no tool
# reproduces queued, a final spot check, agent tag rulings and the review screen.


def test_a_targets_only_difference_is_a_targets_item() -> None:
    a = EXAMPLES["spec-01"]
    b = replace(a, units=_units(a, 0, targets=("suffix",)))
    (item,) = compare_record(a, b)
    assert (item.type, item.start, item.fields) == ("targets", 0, ("targets",))
    c = replace(a, units=_units(a, 0, targets=("suffix",), form="かのじょ"))
    (item,) = compare_record(a, c)
    assert (item.type, item.fields) == ("field", ("form", "targets"))


def test_interjection_and_expression_on_one_entry_agree() -> None:
    a = EXAMPLES["spec-10"]  # すげー: entry 2722660 is exp + int
    assert compare_record(a, replace(a, units=_units(a, 0, kind="expression"))) == []
    bare = replace(a, units=_units(a, 0, entries=()))
    word = replace(a, units=_units(a, 0, kind="word"))
    (item,) = compare_record(bare, word)
    assert (item.type, item.fields) == ("field", ("kind", "entries"))


def test_every_unit_no_tool_reproduces_is_queued() -> None:
    a = EXAMPLES["spec-01"]
    nothing = {a.id: Prediction(a.id, ())}
    result = compare([a], [a], tools={"t1": nothing, "t2": nothing, "t3": nothing}, audit_share=0.0)
    assert result.tools_flagged == 3  # 彼女, 一人暮らし, 始めてしまった
    assert [i.start for i in result.items if i.type == "tools"] == [0, 3, 9]


def test_compare_refuses_a_tool_run_without_every_record() -> None:
    a, b = EXAMPLES["spec-01"], EXAMPLES["spec-02"]
    with pytest.raises(ValueError, match="runs/partial has no prediction for spec-02"):
        compare([a, b], [a, b], tools={"runs/partial": {a.id: Prediction(a.id, ())}})


def test_spot_items_come_from_untouched_records_and_stay_put() -> None:
    base = EXAMPLES["spec-12"]  # 三本, one unit
    records = [replace(base, id=f"r{i:03}") for i in range(80)]
    hit = (PredictedUnit(0, 2, "三本"),)
    tool = {r.id: Prediction(r.id, hit if i % 2 else ()) for i, r in enumerate(records)}
    b = [replace(records[0], units=_units(records[0], 0, form_reading="さん")), *records[1:]]
    result = compare(records, b, tools={"t": tool})
    spots = [i for i in result.items if i.type == "spot"]
    assert len(spots) == SPOT_COUNT == 20
    touched = {i.record_id for i in result.items if i.type != "spot"}
    assert {"audit", "tools", "field"} <= {i.type for i in result.items}
    assert not touched & {i.record_id for i in spots}
    assert all((i.start, i.end) == (0, 2) for i in spots)
    again = compare(list(reversed(records)), list(reversed(b)), tools={"t": tool})
    assert [i for i in again.items if i.type == "spot"] == spots
    spot = spots[0]
    record = next(r for r in records if r.id == spot.record_id)
    merged = merge_record(record, record, [spot], {spot.id: Decision(spot.id, "ok")})
    assert merged is not None and merged.label.status == "audited"


def test_review_leaves_tag_agent_rulings_unless_rechecked(tmp_path: Path) -> None:
    a = EXAMPLES["spec-15"]  # こっち|の|方
    b = replace(a, units=_units(a, 2, targets=()))
    b = replace(b, units=_units(b, 0, form_reading="こち"))
    items = compare_record(a, b)
    assert [i.type for i in items] == ["field", "targets"]
    queue = tmp_path / "queue.jsonl"
    dump_queue(queue, items)
    tag = items[1]
    line = {"item": tag.id, "choice": "a", "by": "tag-agent"}
    (tmp_path / "decisions-tags-001.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    decisions = tmp_path / "decisions.jsonl"
    shown: list[str] = []
    assert review(queue, decisions, {a.id: a.text}, ask=lambda _: "b", say=shown.append) == 1
    assert shown[0].startswith("1 of 2 items")
    assert set(load_decisions(decisions)) == {items[0].id}
    assert review(queue, decisions, {a.id: a.text}, ask=lambda _: "b", say=shown.append, recheck_tags=1) == 1
    owner = load_decisions(decisions)[tag.id]
    assert (owner.choice, owner.by) == ("b", "owner")
    assert load_all_decisions(tmp_path)[tag.id] == owner


def test_owner_decisions_override_tag_agent_decisions(tmp_path: Path) -> None:
    agent = [{"item": f"{r}:0-1:targets", "choice": "a", "by": "tag-agent"} for r in ("x", "y")]
    lines = "".join(json.dumps(d) + "\n" for d in agent)
    (tmp_path / "decisions-tags-001.jsonl").write_text(lines, encoding="utf-8")
    owner = {"item": "x:0-1:targets", "choice": "b", "by": "owner"}
    (tmp_path / "decisions.jsonl").write_text(json.dumps(owner) + "\n", encoding="utf-8")
    decided = load_all_decisions(tmp_path)
    assert (decided["x:0-1:targets"].choice, decided["x:0-1:targets"].by) == ("b", "owner")
    assert (decided["y:0-1:targets"].choice, decided["y:0-1:targets"].by) == ("a", "tag-agent")


def test_a_targets_ruling_merges_to_exactly_the_chosen_side() -> None:
    a = EXAMPLES["spec-01"]
    a = replace(a, units=_units(a, 0, targets=("suffix",)))
    b = replace(a, units=_units(a, 0, targets=()))
    b = replace(b, units=_units(b, 2, targets=("compound",), split_points=()))
    items = compare_record(a, b)
    assert [(i.type, i.start) for i in items] == [("targets", 0), ("targets", 3)]
    merged = merge_record(a, b, items, {i.id: Decision(i.id, "b") for i in items})
    assert merged is not None
    assert merged.units[0].targets == ()
    assert (merged.units[2].targets, merged.units[2].split_points) == (("compound",), (5,))


def test_a_field_ruling_takes_no_targets_from_the_other_side() -> None:
    a = EXAMPLES["spec-15"]  # こっち|の|方
    b = replace(a, units=_units(a, 2, targets=(), form_reading="かた"))
    (item,) = compare_record(a, b)
    merged = merge_record(a, b, [item], {item.id: Decision(item.id, "b")})
    assert merged is not None and merged.units[2].targets == ()


def test_merge_keeps_only_entry_ids_both_labelers_list() -> None:
    a = EXAMPLES["spec-10"]  # すげー, normalized to すごい
    norm = a.units[0].normalized
    assert norm is not None
    a1 = replace(a, units=_units(a, 0, entries=(1, 2), normalized=replace(norm, entries=(7, 8))))
    b1 = replace(a, units=_units(a, 0, entries=(1, 3), normalized=replace(norm, entries=(7, 9))))
    assert compare_record(a1, b1) == []
    merged = merge_record(a1, b1, [], {})
    assert merged is not None and merged.units[0].entries == (1,)
    assert merged.units[0].normalized is not None and merged.units[0].normalized.entries == (7,)


def test_label_merge_needs_no_tools_after_compare_with_tools(
    tmp_path: Path, index_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from monosashi import cli
    from monosashi.predictions import dump_predictions
    from monosashi.schema import dump_records

    monkeypatch.setattr(cli, "_labels_dir", lambda: tmp_path / "labels")
    run_dir = tmp_path / "labels" / "r"
    agreed, a14 = EXAMPLES["spec-01"], EXAMPLES["spec-14"]  # 方 carries heteronym
    b14 = replace(a14, units=_units(a14, 1, targets=()))
    for side, records in (("A", [agreed, a14]), ("B", [agreed, b14])):
        (run_dir / f"labels-{side}").mkdir(parents=True)
        dump_records(run_dir / f"labels-{side}" / "batch-001.jsonl", records)
    # The tool reproduces every unit but 彼女, so spec-01 gets a tools item and no spot item.
    tool = tmp_path / "runs" / "t"
    dump_predictions(
        tool / "predictions.jsonl",
        [
            Prediction(
                r.id, tuple(PredictedUnit(u.start, u.end, u.surface) for u in r.units if u.surface != "彼女")
            )
            for r in (agreed, a14)
        ],
    )
    index = ["--index", str(index_path)]
    assert cli.main([*index, "label", "compare", "r", "--tools", str(tool)]) == 0
    items = {i.type: i for i in load_queue(run_dir / "queue.jsonl")}
    assert sorted(items) == ["targets", "tools"]
    agent = {"item": items["targets"].id, "choice": "b", "by": "tag-agent"}
    (run_dir / "decisions-tags-001.jsonl").write_text(json.dumps(agent) + "\n", encoding="utf-8")
    owner = {"item": items["tools"].id, "choice": "ok", "by": "owner"}
    (run_dir / "decisions.jsonl").write_text(json.dumps(owner) + "\n", encoding="utf-8")
    out = tmp_path / "core"
    assert cli.main([*index, "label", "merge", "r", "--out", str(out)]) == 0
    merged = {r.id: r for r in load_records(out / "conversation.jsonl")}
    assert set(merged) == {agreed.id, a14.id}
    assert merged[a14.id].units[1].targets == ()


def test_merged_seed_records_go_to_the_private_twin(tmp_path: Path) -> None:
    from monosashi import cli

    open_record, seed = EXAMPLES["spec-01"], replace(EXAMPLES["spec-14"], slice="seed")
    out = tmp_path / "data" / "core"
    written = cli._write_gold(out, [open_record, seed])
    assert [r.id for p in out.glob("*.jsonl") for r in load_records(p)] == [open_record.id]
    private = tmp_path / "data" / "private" / "core"
    assert [r.id for p in private.glob("*.jsonl") for r in load_records(p)] == [seed.id]
    assert sum(written.values()) == 2


def test_an_agreed_advisory_unit_is_queued_for_review(dictionary: Dictionary) -> None:
    from helpers import record
    from monosashi.schema import record_from_dict

    rec = record_from_dict(
        record(
            "三歳年上",
            [
                {"start": 0, "end": 2, "surface": "三歳", "kind": "word", "entries": [1294940], "form": "歳",
                 "reading": "さんさい", "form_reading": "さい", "split_points": [1], "targets": ["counter"]},
                {"start": 2, "end": 4, "surface": "年上", "kind": "word", "entries": [1468870], "form": "年上",
                 "reading": "としうえ", "form_reading": "としうえ"},
            ],
        )
    )  # fmt: skip
    result = compare([rec], [rec], dictionary=dictionary, audit_share=0.0)
    (item,) = result.items
    assert (item.type, item.start, item.end) == ("validator", 0, 2)
    assert item.note.startswith("[advisory] [counter-whole-entry]")
    # An advisory is no disagreement: the record still counts as agreed, and can be audited.
    s = result.summary()
    assert (s["records_agreed"], s["units_agreed"], s["field_disagreements"]) == (1, 2, {})
    audited = compare([rec], [rec], dictionary=dictionary, audit_share=1.0)
    assert [i.type for i in audited.items] == ["audit", "validator"]


def test_review_screen_shows_glosses_and_each_labelers_unit(dictionary: Dictionary) -> None:
    a = EXAMPLES["spec-01"]
    b = replace(a, units=_units(a, 2, split_points=()))  # split points are merged, not compared
    nothing = [{a.id: Prediction(a.id, ())}]
    by_start = {i.start: i for i in tool_items(a, b, nothing, quorum=1)}
    assert by_start[3].b == (b.units[2],)
    shown = render_item(by_start[9].to_dict(), a.text, dictionary=dictionary)
    assert "entries=1307550 (始める: to start …)" in shown
    a_side, b_side = render_item(by_start[3].to_dict(), a.text).split("\nB:\n")
    assert "split_points=5" in a_side and "一人暮らし" in b_side and "split_points" not in b_side


def test_a_tag_edit_on_the_shown_base_keeps_only_what_both_labelers_list(
    tmp_path: Path, dictionary: Dictionary
) -> None:
    from monosashi.review import tag_chunk

    a = EXAMPLES["spec-01"]
    a = replace(a, units=_units(a, 2, entries=(1613340, 999), split_points=(), targets=("suffix",)))
    b = replace(a, units=_units(a, 2, entries=(1613340,), split_points=(5,), targets=()))
    items = compare_record(a, b)
    assert [i.type for i in items] == ["targets"]
    out = tmp_path / "decisions-tags-001.jsonl"
    shown = tag_chunk([a], [b], items, 1, 25, out, dictionary)
    base = json.loads(shown.split("Edit base (the merged unit): ")[1].splitlines()[0])
    edit = {
        "item": items[0].id,
        "choice": "edit",
        "units": [{**base, "targets": ["compound"]}],
        "by": "tag-agent",
    }
    merged = merge_record(a, b, items, {items[0].id: decision_from_dict(edit)})
    assert merged is not None
    unit = merged.units[2]
    assert (unit.entries, unit.split_points, unit.targets) == ((1613340,), (5,), ("compound",))
    out.write_text(json.dumps(edit, ensure_ascii=False) + "\n", encoding="utf-8")
    assert tag_chunk([a], [b], items, 1, 25, out, dictionary) == "1 of 1 decided, 0 problem(s)"


def test_the_tag_workflow_imports_names_that_exist() -> None:
    """The tag workflow runs Python of its own; a rename would break it only at run time.

    The workflow is local to the owner's checkout (.claude/workflows), so a clone skips this."""
    path = repo_root() / ".claude" / "workflows" / "tag_workflow.js"
    if not path.exists():
        pytest.skip("the tag workflow is local to the owner's checkout")
    script = path.read_text(encoding="utf-8")
    (python,) = re.findall(r"^const ITEMS_SCRIPT = `(.*?)`$", script, re.DOTALL | re.MULTILINE)
    imports = [node for node in ast.walk(ast.parse(python)) if isinstance(node, ast.ImportFrom)]
    names = [(node.module or "", alias.name) for node in imports for alias in node.names]
    assert ("monosashi.review", "tag_chunk") in names
    missing = [f"{m}.{n}" for m, n in names if not hasattr(importlib.import_module(m), n)]
    assert missing == []


# --- blind bundles -------------------------------------------------------------------------------

BY_TEXT = {r.text: r for r in EXAMPLES.values()}


def _blind_sentences(count: int = 8) -> list[Sentence]:
    """Spec examples posing as sentences from varied sources, registers and slices."""
    registers, slices = sorted(REGISTERS), sorted(SLICES)
    return [
        Sentence(f"real-{i:02d}", r.text, Source(f"corpus-{i % 3}", f"ref-{i}", "CC-BY-2.0-FR", f"author {i}"),
                 registers[i % len(registers)], slices[i % len(slices)])
        for i, r in enumerate(list(EXAMPLES.values())[:count])
    ]  # fmt: skip


def _label_bundle(bundle: Path, units: Callable[[Record], tuple[Unit, ...]]) -> None:
    """What a labeler does: fill every input skeleton's units into labels/NAME.jsonl."""
    for path in sorted(bundle.glob("*.input.jsonl")):
        name = path.name.removesuffix(".input.jsonl")
        dump_records(
            bundle / "labels" / f"{name}.jsonl", [replace(r, units=units(r)) for r in load_records(path)]
        )


def _gold_units(r: Record) -> tuple[Unit, ...]:
    return BY_TEXT[r.text].units


def _blind_run(tmp_path: Path, dictionary: Dictionary, count: int, batch_size: int) -> tuple[Path, Path]:
    run_dir, bundles = tmp_path / "labels" / "run1", tmp_path / "bundles"
    blind.prepare(_blind_sentences(count), run_dir, bundles, dictionary, batch_size=batch_size)
    return run_dir, bundles


def test_blind_round_trip_restores_every_real_field(tmp_path: Path, dictionary: Dictionary) -> None:
    sentences = _blind_sentences()
    run_dir, bundles = tmp_path / "labels" / "run1", tmp_path / "bundles"
    names = blind.prepare(sentences, run_dir, bundles, dictionary, batch_size=3)
    assert names == ["batch-001", "batch-002", "batch-003"]
    a, b = bundles / "A", bundles / "B"
    files = {p.relative_to(a).as_posix() for p in a.rglob("*")}
    assert files == {p.relative_to(b).as_posix() for p in b.rglob("*")}
    assert files == {"SPEC.md", "INSTRUCTIONS.md", "spec-examples.jsonl", "labels"} | {
        f"{n}.{part}" for n in names for part in ("input.jsonl", "sheets.md", "senses.md")
    }
    assert (a / "SPEC.md").read_bytes() == (repo_root() / "SPEC.md").read_bytes()
    instructions = (a / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert "{monosashi}" not in instructions
    assert f"{blind.MONOSASHI} validate <BUNDLE>/labels/NAME.jsonl" in instructions
    meta = json.loads((run_dir / "blind.json").read_text(encoding="utf-8"))
    assert meta["spec_version"] == SPEC_VERSION
    assert list(meta["ids"]) == [f"run1-{n:04d}" for n in range(1, 9)]
    real_order = list(meta["ids"].values())
    assert sorted(real_order) == [s.id for s in sentences] and real_order != [s.id for s in sentences]

    def b_units(r: Record) -> tuple[Unit, ...]:  # B gets 食べちゃった's chain wrong
        gold = BY_TEXT[r.text]
        return _units(gold, 0, chain=("-ちゃう",)) if r.text == "食べちゃった。" else gold.units

    _label_bundle(a, _gold_units)
    _label_bundle(b, b_units)
    issues = blind.collect(run_dir, bundles, sentences, dictionary)

    expected = {
        s.id: Record(
            s.id, s.text, s.source, s.register, s.slice, BY_TEXT[s.text].units, Label("draft", SPEC_VERSION)
        )
        for s in sentences
    }
    for labeler in ("A", "B"):
        out = run_dir / f"labels-{labeler}"
        assert sorted(p.name for p in out.iterdir()) == [f"{n}.jsonl" for n in names]
        collected = [r for n in names for r in load_records(out / f"{n}.jsonl")]
        assert [r.id for r in collected] == real_order
        if labeler == "A":
            assert {r.id: r for r in collected} == expected
    opaque = next(o for o, real in meta["ids"].items() if real == "real-01")  # 食べちゃった。
    broken = f"labels-B/{names[(int(opaque[-4:]) - 1) // 3]}.jsonl"
    assert set(issues) == {f"labels-{x}/{n}.jsonl" for x in "AB" for n in names}
    assert [k for k, v in issues.items() if v] == [broken]
    assert all(line.startswith("real-01 unit 0: [") for line in issues[broken])


def test_blind_bundle_hides_ids_sources_and_seed_answers(tmp_path: Path, dictionary: Dictionary) -> None:
    seed = Sentence("ichiran-test-0042", "食べてみた", Source("ichiran-tests", "tests.lisp:L12", "MIT", "ATTRIB-SEED"),
                    "game-net", "seed", original={"expected": "食べ|てみ|た SEED-ANSWER"},
                    hints=(Hint("te-auxiliary", 0, 5),))  # fmt: skip
    other = Sentence("tatoeba-77", "食べちゃった。", Source("tatoeba", "REF-Q", "CC-BY-2.0-FR", "ATTRIB-OPEN"),
                     "literature", "plain")  # fmt: skip
    run_dir, bundles = tmp_path / "labels" / "run1", tmp_path / "bundles"
    blind.prepare([seed, other], run_dir, bundles, dictionary)
    leaks = ["ichiran", "tests.lisp", "SEED-ANSWER", "original", "tatoeba", "REF-Q", "ATTRIB", "game-net",
             "literature", '"seed"', '"plain"']  # fmt: skip
    batch_files = [p for x in "AB" for p in sorted((bundles / x).glob("batch-*"))]
    assert len(batch_files) == 6
    for path in batch_files:
        text = path.read_text(encoding="utf-8")
        assert [leak for leak in leaks if leak in text] == [], path.name
    skeletons = [r for x in "AB" for r in load_records(bundles / x / "batch-001.input.jsonl")]
    assert {(r.source, r.register, r.slice) for r in skeletons} == {
        (Source("blind", r.id, "CC-BY-SA-4.0", "withheld while labeling"), "conversation", "open")
        for r in skeletons
    }
    sheet = (bundles / "A" / "batch-001.sheets.md").read_text(encoding="utf-8")
    assert "→ te-auxiliary" in sheet and "## run1-0001" in sheet  # the tagger's hints stay


def _labels_change(change: Callable[[list[Record]], list[Record]]) -> Callable[[Path, Path], None]:
    def apply(run_dir: Path, labels: Path) -> None:
        dump_records(labels, change(list(load_records(labels))))

    return apply


def _meta_change(change: Callable[[dict[str, Any]], object]) -> Callable[[Path, Path], None]:
    def apply(run_dir: Path, labels: Path) -> None:
        path = run_dir / "blind.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        change(meta)
        path.write_text(json.dumps(meta), encoding="utf-8")

    return apply


def _digest_change(path: str) -> Callable[[Path, Path], None]:
    """As if ``path``, which prepare must have frozen, changed after prepare."""

    def change(meta: dict[str, Any]) -> None:
        assert path in meta["digests"], f"{path} is not frozen"
        meta["digests"][path] = "0"

    return _meta_change(change)


# Each changes labeler B's batch-001.jsonl after labeling, or blind.json after prepare.
DRIFTS: dict[str, tuple[Callable[[Path, Path], object], str]] = {
    "edited text": (
        _labels_change(lambda rs: [replace(rs[0], text=rs[0].text + "！"), *rs[1:]]),
        "text changed",
    ),
    "dropped record": (_labels_change(lambda rs: rs[:-1]), "missing"),
    "extra record": (_labels_change(lambda rs: [*rs, rs[0]]), "extra"),
    "reordered records": (_labels_change(lambda rs: rs[::-1]), "out of order"),
    "missing batch": (lambda run_dir, labels: labels.unlink(), "batch-001 is not labeled"),
    "renamed batch": (
        lambda run_dir, labels: labels.rename(labels.with_name("batch-009.jsonl")),
        "no such batch",
    ),
    "changed kana.py": (_digest_change("src/monosashi/kana.py"), "kana.py"),
    # INSTRUCTIONS.md has labelers run the candidate sheet and look entries up in the pinned JMdict.
    "changed candidates.py": (_digest_change("src/monosashi/label/candidates.py"), "candidates.py"),
    "changed JMdict pin": (_digest_change("data/sources.toml"), "sources.toml"),
    "changed spec version": (_meta_change(lambda m: m.update(spec_version="0.2")), "spec 0.2"),
}


@pytest.mark.parametrize("drift", DRIFTS)
def test_blind_collect_refuses_drift_and_writes_nothing(
    drift: str, tmp_path: Path, dictionary: Dictionary
) -> None:
    run_dir, bundles = _blind_run(tmp_path, dictionary, count=4, batch_size=4)
    for x in "AB":
        _label_bundle(bundles / x, _gold_units)
    change, message = DRIFTS[drift]
    change(run_dir, bundles / "B" / "labels" / "batch-001.jsonl")
    with pytest.raises(ValueError, match=message):
        blind.collect(run_dir, bundles, _blind_sentences(4), dictionary)
    assert sorted(p.name for p in run_dir.iterdir()) == ["blind.json"]


def test_blind_digests_follow_the_validator_and_candidate_sheet_imports(
    tmp_path: Path, dictionary: Dictionary
) -> None:
    import monosashi.cli  # noqa: F401  (loaded in this process, but never by the validator or the sheet)

    run_dir, _ = _blind_run(tmp_path, dictionary, count=1, batch_size=1)
    digests = json.loads((run_dir / "blind.json").read_text(encoding="utf-8"))["digests"]
    for path in ("SPEC.md", "src/monosashi/validate.py", "src/monosashi/counters.py",
                 "src/monosashi/kana.py", "src/monosashi/deinflect/_vendor/transforms.py",
                 "src/monosashi/label/candidates.py", "data/sources.toml"):  # fmt: skip
        assert digests[path] == hashlib.sha256((repo_root() / path).read_bytes()).hexdigest()
    assert "src/monosashi/cli.py" not in digests and "src/monosashi/label/blind.py" not in digests


def _leftover(path: str) -> Callable[[Path, Path], Path]:
    def setup(run_dir: Path, bundles: Path) -> Path:
        (run_dir / path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / path).write_text("{}\n", encoding="utf-8")
        return bundles

    return setup


def _bundle_b_exists(run_dir: Path, bundles: Path) -> Path:
    (bundles / "B").mkdir(parents=True)
    return bundles


IN_REPO = repo_root() / "data" / "labels" / "t7-never-written" / "bundles"
# Each sets up a run that prepare must refuse, and returns the bundle root to pass.
REFUSALS: dict[str, tuple[Callable[[Path, Path], Path], type[Exception], str]] = {
    "bundle inside the repo": (lambda run_dir, bundles: IN_REPO, ValueError, "inside the repository"),
    "run with blind.json": (_leftover("blind.json"), FileExistsError, "blind.json"),
    "run with labels": (_leftover("labels-A/batch-040.jsonl"), FileExistsError, "labels-A"),
    "existing bundle": (_bundle_b_exists, FileExistsError, "bundles/B"),
}  # fmt: skip


@pytest.mark.parametrize("refusal", REFUSALS)
def test_blind_prepare_refuses_a_used_or_unsafe_place(
    refusal: str, tmp_path: Path, dictionary: Dictionary
) -> None:
    setup, error, message = REFUSALS[refusal]
    run_dir = tmp_path / "labels" / "run1"
    bundle_root = setup(run_dir, tmp_path / "bundles")
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(error, match=message):
        blind.prepare(_blind_sentences(1), run_dir, bundle_root, dictionary)
    assert sorted(tmp_path.rglob("*")) == before and not IN_REPO.parent.exists()


def test_blind_prepare_says_why_the_frozen_modules_could_not_be_listed(
    tmp_path: Path, dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(blind, "_FROZEN_MODULES", "import sys; sys.exit('validate.py: no such rule')")
    with pytest.raises(RuntimeError, match="no such rule"):
        _blind_run(tmp_path, dictionary, count=1, batch_size=1)
    assert list(tmp_path.iterdir()) == []


def test_blind_prepare_leaves_no_half_written_bundle(
    tmp_path: Path, dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[str] = []

    def write_one_then_fail(
        name: str, batch: Sequence[Sentence], out_dir: Path, dictionary: Dictionary
    ) -> None:
        if written:
            raise OSError("disk full")
        written.append(name)
        real_write_batch(name, batch, out_dir, dictionary)

    real_write_batch = batches.write_batch
    monkeypatch.setattr(batches, "write_batch", write_one_then_fail)
    with pytest.raises(OSError, match="disk full"):
        _blind_run(tmp_path, dictionary, count=4, batch_size=2)
    assert written == ["batch-001"]
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_blind_prepare_removes_the_bundles_when_blind_json_cannot_be_written(
    tmp_path: Path, dictionary: Dictionary
) -> None:
    (tmp_path / "labels").write_text("a file where the run directory's parent should be", encoding="utf-8")
    with pytest.raises(OSError):
        _blind_run(tmp_path, dictionary, count=2, batch_size=1)
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [tmp_path / "labels"]


def test_word_and_interjection_agree_on_one_int_entry() -> None:
    """了解 (int, n, vs) may be a word or an interjection (SPEC.md §3); other kinds still differ."""
    word = Unit(0, 2, "了解", "word", (1570080,), "了解", "りょうかい", "りょうかい")
    assert kinds_agree(word, replace(word, kind="interjection"))
    assert not kinds_agree(word, replace(word, kind="interjection", entries=()))
    assert not kinds_agree(word, replace(word, kind="name"))

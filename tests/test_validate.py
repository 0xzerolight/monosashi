from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from helpers import benkyou_shiteiru, hajimete_shimatta, record, sugee, tanaka_san
from monosashi.jmdict import Dictionary
from monosashi.schema import record_from_dict
from monosashi.validate import ADVISORY_RULES, advisory_issues, validate_files, validate_record

Data = dict[str, Any]


def rules(data: Data, dictionary: Dictionary) -> set[str]:
    return {issue.rule for issue in validate_record(record_from_dict(data), dictionary)}


@pytest.mark.parametrize("make", [hajimete_shimatta, sugee, benkyou_shiteiru, tanaka_san])
def test_correct_records_have_no_issues(make: Callable[[], Data], dictionary: Dictionary) -> None:
    issues = validate_record(record_from_dict(make()), dictionary)
    assert issues == [], [str(i) for i in issues]


def _unit(data: Data, index: int) -> dict[str, Any]:
    unit: dict[str, Any] = data["units"][index]
    return unit


def _break(change: Callable[[Data], None]) -> Data:
    data = copy.deepcopy(hajimete_shimatta())
    change(data)
    return data


BREAKAGES: dict[str, Callable[[Data], None]] = {
    "text-normalized": lambda d: d.update(text=d["text"].replace("。", "～")),
    "span-surface": lambda d: _unit(d, 0).update(surface="彼"),
    "coverage": lambda d: d["units"].pop(1),
    "span-symbol": lambda d: _unit(d, 4).update(end=17, surface="始めてしまった。"),
    "kind": lambda d: _unit(d, 1).update(kind="particle-ish"),
    "function-entries": lambda d: _unit(d, 1).update(entries=[2028920]),
    "content-fields": lambda d: _unit(d, 0).pop("reading"),
    "reading-kana": lambda d: _unit(d, 0).update(reading="カノジョ"),
    "split-points": lambda d: _unit(d, 2).update(split_points=[3]),
    "targets": lambda d: _unit(d, 2).update(targets=["compounds"]),
    "chain-ids": lambda d: _unit(d, 4).update(chain=["-て", "-shimau", "-た"]),
    "entries-exist": lambda d: _unit(d, 0).update(entries=[1999999]),
    "form-spelling": lambda d: _unit(d, 0).update(form="かのじょう"),
    "form-reading": lambda d: _unit(d, 2).update(form_reading="ひとりくらし"),
    "chain-deinflects": lambda d: _unit(d, 4).update(chain=["-て", "-た"]),
    "chain-missing": lambda d: _unit(d, 4).pop("chain"),
    "register": lambda d: d.update(register="anime"),
    "slice": lambda d: d.update(slice="real"),
    "kind-expression": lambda d: _unit(d, 2).update(kind="expression"),
    "label-spec": lambda d: d["label"].update(spec="0.0"),
    "license": lambda d: d["source"].update(license="CC-BY-NC-4.0"),
    "label-status": lambda d: d["label"].update(status="final"),
    "text-empty": lambda d: d.update(text="", units=[]),
    "span-bounds": lambda d: _unit(d, 0).update(end=99),
    "entries-duplicate": lambda d: _unit(d, 0).update(entries=[1483150, 1483150]),
    "function-targets": lambda d: _unit(d, 1).update(targets=["prefix"]),
    "function-normalized": lambda d: _unit(d, 1).update(
        normalized={"form": "は", "form_reading": "は", "entries": [2028920]}
    ),
}


@pytest.mark.parametrize("rule", sorted(BREAKAGES))
def test_each_rule_catches_its_breakage(rule: str, dictionary: Dictionary) -> None:
    assert rule in rules(_break(BREAKAGES[rule]), dictionary)


def test_overlapping_units_are_out_of_order(dictionary: Dictionary) -> None:
    data = hajimete_shimatta()
    _unit(data, 2).update(start=2, surface="は一人暮らし")
    assert "span-order" in rules(data, dictionary)


def test_kana_surface_needs_kana_form_and_its_own_reading(dictionary: Dictionary) -> None:
    data = record(
        "すごい",
        [{"start": 0, "end": 3, "surface": "すごい", "kind": "word", "entries": [1374550], "form": "凄い",
          "reading": "すごーい", "form_reading": "すごい"}],
    )  # fmt: skip
    assert {"form-orthography", "reading-kana-surface"} <= rules(data, dictionary)


def test_chain_split_across_units_is_not_maximal(dictionary: Dictionary) -> None:
    def split(d: Data) -> None:
        d["units"][4:] = [
            {"start": 9, "end": 12, "surface": "始めて", "kind": "word", "entries": [1307550], "form": "始める",
             "reading": "はじめて", "form_reading": "はじめる", "chain": ["-て"]},
            {"start": 12, "end": 16, "surface": "しまった", "kind": "auxiliary"},
        ]  # fmt: skip

    assert "chain-maximal" in rules(_break(split), dictionary)


def test_noun_followed_by_suru_must_join(dictionary: Dictionary) -> None:
    data = record(
        "勉強している",
        [
            {"start": 0, "end": 2, "surface": "勉強", "kind": "word", "entries": [1512670], "form": "勉強",
             "reading": "べんきょう", "form_reading": "べんきょう"},
            {"start": 2, "end": 6, "surface": "している", "kind": "auxiliary"},
        ],
    )  # fmt: skip
    assert "chain-maximal" in rules(data, dictionary)


def test_normalized_must_name_a_real_standard_word(dictionary: Dictionary) -> None:
    data = sugee()
    _unit(data, 0)["normalized"]["form"] = "すげぇ"  # a spelling of すげー's entry, not of 凄い
    assert "normalized-form" in rules(data, dictionary)
    data = sugee()
    _unit(data, 0)["normalized"]["form_reading"] = "すげー"
    assert "normalized-reading" in rules(data, dictionary)
    data = sugee()
    _unit(data, 0)["normalized"]["entries"] = []
    assert "normalized-entries" in rules(data, dictionary)


def test_normalized_ids_must_exist(dictionary: Dictionary) -> None:
    data = sugee()
    _unit(data, 0)["normalized"]["entries"] = [1999999]
    assert "normalized-exist" in rules(data, dictionary)


def test_an_all_exp_entry_is_not_a_word(dictionary: Dictionary) -> None:
    data = record(
        "かもしれない",
        [{"start": 0, "end": 6, "surface": "かもしれない", "kind": "word", "entries": [1002970],
          "form": "かもしれない", "reading": "かもしれない", "form_reading": "かもしれない"}],
    )  # fmt: skip
    assert rules(data, dictionary) == {"kind-expression"}


def test_names_check_jmnedict_not_jmdict(dictionary: Dictionary) -> None:
    data = tanaka_san()
    _unit(data, 0)["entries"] = [1483150]  # a JMdict id; no such JMnedict entry
    assert "entries-exist" in rules(data, dictionary)


def test_validate_files_reports_duplicate_ids_and_schema_errors(
    tmp_path: Path, dictionary: Dictionary
) -> None:
    good = tmp_path / "a.jsonl"
    line = json.dumps(hajimete_shimatta(), ensure_ascii=False)
    good.write_text(line + "\n" + line + "\n", encoding="utf-8")
    broken = tmp_path / "b.jsonl"
    broken.write_text('{"id": "x"}\n', encoding="utf-8")
    found = {issue.rule for issue in validate_files([good, broken], dictionary)}
    assert found == {"id-duplicate", "schema"}


def test_a_word_with_an_exp_sense_may_stay_a_word(dictionary: Dictionary) -> None:
    from monosashi.validate import _has_content_pos

    assert _has_content_pos(("adv", "exp", "int"))  # ちょっと
    assert _has_content_pos(("exp", "v5r"))  # 気に入る may be a word or an expression
    assert not _has_content_pos(("exp",))  # かもしれない, ですか
    assert not _has_content_pos(("exp", "int"))  # すげー


def _sansai_toshiue() -> Data:
    """三歳年上 'three years older': 三歳 is not the entry 'three-year-old' (SPEC.md §4.4)."""
    return record(
        "三歳年上",
        [
            {"start": 0, "end": 2, "surface": "三歳", "kind": "word", "entries": [1294940], "form": "歳",
             "reading": "さんさい", "form_reading": "さい", "split_points": [1], "targets": ["counter"]},
            {"start": 2, "end": 4, "surface": "年上", "kind": "word", "entries": [1468870], "form": "年上",
             "reading": "としうえ", "form_reading": "としうえ"},
        ],
    )  # fmt: skip


def test_counter_whole_entry_is_an_advisory(dictionary: Dictionary) -> None:
    rec = record_from_dict(_sansai_toshiue())
    assert validate_record(rec, dictionary) == []
    advisories = advisory_issues(rec, dictionary)
    assert [(a.unit, a.rule) for a in advisories] == [(0, "counter-whole-entry")]
    assert {"counter-whole-entry"} == ADVISORY_RULES
    assert advisory_issues(record_from_dict(hajimete_shimatta()), dictionary) == []


def test_validate_files_returns_advisories_only_on_request(tmp_path: Path, dictionary: Dictionary) -> None:
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps(_sansai_toshiue(), ensure_ascii=False) + "\n", encoding="utf-8")
    assert validate_files([path], dictionary) == []
    assert [i.rule for i in validate_files([path], dictionary, advisories=True)] == ["counter-whole-entry"]

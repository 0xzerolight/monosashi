"""Seed parsers for the three test suites, and seed gold records without their text."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import hajimete_shimatta, sugee
from monosashi.schema import record_from_dict
from monosashi.sources.seeds import (
    SUITES,
    parse_anki_miner,
    parse_ichiran,
    parse_jiten,
    to_sentences,
    with_text,
    without_text,
)

ICHIRAN = """(define-parallel-test segmentation-test
  (assert-segment "お茶はいかがですか" "お茶" "は" "いかが" "です" "か")
  (assert-segment "弟にまかせて荷物まるごと"
                  "弟" "に" "まかせて" "荷物" "まるごと")
  (assert-segment "歩いたぁ" "歩いた" :gap) ;; たぁ non-sticky
  (assert-segment "say \\"hi\\"" "say")
  )
(defun f (s) (assert-segment s s))
"""


def test_ichiran_reads_literal_assertions_only() -> None:
    cases = list(parse_ichiran(ICHIRAN))
    assert [(c.line, c.text) for c in cases] == [
        (2, "お茶はいかがですか"),
        (3, "弟にまかせて荷物まるごと"),
        (5, "歩いたぁ"),
        (6, 'say "hi"'),
    ]
    assert cases[1].original == {"split": ["弟", "に", "まかせて", "荷物", "まるごと"]}
    assert cases[2].original == {"split": ["歩いた", None]}


JITEN = """    public static IEnumerable<object[]> SegmentationCases()
    {
        // Compound particles that Sudachi splits
        // (complete sentences)
        yield return ["彼が遅刻したばかりに......", new[] { "彼", "が", "遅刻した", "ばかりに" }];
        // yield return ["めんどくそがる", new[] { "めんどくそがる" }];
        yield return
        [
            "てか最近",
            new[] { "てか", "最近" }
        ];
        yield return ["あるか?\\n俺はない。", new string[] { "ある", "か", "俺", "は", "ない" }];
    }
"""


def test_jiten_reads_live_cases_with_their_notes() -> None:
    cases = list(parse_jiten(JITEN))
    assert [(c.line, c.text) for c in cases] == [
        (5, "彼が遅刻したばかりに......"),
        (7, "てか最近"),
        (12, "あるか?\n俺はない。"),  # a C# escape, and a typed new string[]
    ]
    assert cases[0].original == {
        "split": ["彼", "が", "遅刻した", "ばかりに"],
        "note": "Compound particles that Sudachi splits (complete sentences)",
    }
    assert "note" not in cases[1].original


def test_anki_miner_rows_and_sentences() -> None:
    source = '{"id":"co01","sentence":"すげえ","expected":["すごい"],"category":"colloquial"}\n\n'
    cases = list(parse_anki_miner(source))
    assert cases[0].original == {"id": "co01", "expected": ["すごい"], "category": "colloquial"}
    (s,) = to_sentences(
        SUITES["anki_miner"], iter(cases), path="p.jsonl", version="ff4d11d14a4e9b", url="https://x/p.jsonl",
        id_of="row-id",
    )  # fmt: skip
    assert (s.id, s.slice, s.source.license, s.source.url) == (
        "anki_miner-co01",
        "seed",
        "CC-BY-SA-4.0",
        "https://x/p.jsonl#L1",
    )


def test_suite_seeds_are_numbered_and_normalized() -> None:
    cases = list(parse_ichiran('(assert-segment "すご～い" "すご～い")'))
    (s,) = to_sentences(SUITES["ichiran"], iter(cases), path="tests.lisp", version="d00bee6", url="https://x")
    assert (s.id, s.text, s.register) == ("ichiran-0001", "すご〜い", "comic")  # line 1


def test_jiten_parser_refuses_a_case_it_cannot_read() -> None:
    with pytest.raises(ValueError, match="live"):
        list(parse_jiten('yield return ["x", new List<string> { "x" }];'))


def test_seed_ids_are_source_lines() -> None:
    cases = list(parse_ichiran('\n\n(assert-segment "食べた" "食べた")'))
    (s,) = to_sentences(SUITES["ichiran"], iter(cases), path="tests.lisp", version="d00bee6", url="https://x")
    assert s.id == "ichiran-0003"


@pytest.mark.parametrize("build", [hajimete_shimatta, sugee])
def test_seed_records_publish_without_text_and_get_it_back(build: Callable[[], dict[str, Any]]) -> None:
    record = record_from_dict(build())
    published = without_text(record)
    assert record.text not in str(published)
    assert all("surface" not in u for u in published["units"])
    assert with_text(published, record.text) == record

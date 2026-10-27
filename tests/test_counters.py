"""What counts as a counter after a number (SPEC.md §4.4)."""

from __future__ import annotations

import re

from monosashi.counters import COUNTER_WORDS, is_counter_entry, is_number_counter
from monosashi.jmdict import Dictionary, Entry, repo_root


def _entry(dictionary: Dictionary, seq: int) -> Entry:
    entry = dictionary.entry(seq)
    assert entry is not None
    return entry


def test_counter_words_are_the_spec_list() -> None:
    spec = (repo_root() / "SPEC.md").read_text(encoding="utf-8")
    listed = re.search(r"one of these words, which JMdict tags otherwise: ([^.]+)\.", spec)
    assert listed is not None
    assert frozenset(listed.group(1).split(", ")) == COUNTER_WORDS


def test_counter_entries_are_ctr_or_listed(dictionary: Dictionary) -> None:
    assert is_counter_entry(_entry(dictionary, 1522150))  # 本, ctr
    assert is_counter_entry(_entry(dictionary, 2842624))  # 代目, ctr
    assert is_counter_entry(_entry(dictionary, 1315840))  # 時 (とき), by the list
    assert not is_counter_entry(_entry(dictionary, 1373990))  # 世紀
    assert not is_counter_entry(_entry(dictionary, 2827650))  # 日間
    assert not is_counter_entry(_entry(dictionary, 1199780))  # 回目, suf
    assert not is_counter_entry(_entry(dictionary, 1584460))  # 万 counts only after digits


def test_number_counters(dictionary: Dictionary) -> None:
    def counts(surface: str, form: str, seq: int) -> bool:
        return is_number_counter(surface, form, [_entry(dictionary, seq)])

    assert counts("二十本", "本", 1522150)
    assert counts("3代目", "代目", 2842624)
    assert counts("50万", "万", 1584460)
    assert counts("５０万", "万", 1584460)
    assert not counts("五十万", "万", 1584460)  # a number alone (§4.4)
    assert not counts("21得点", "得点", 1454590)
    assert not counts("何世紀", "世紀", 1373990)
    assert not counts("2回目", "回目", 1199780)  # 2回|目
    assert not counts("本", "本", 1522150)
    assert not is_number_counter("三は", "は", [])

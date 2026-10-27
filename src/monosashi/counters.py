"""What counts as a counter after a number (SPEC.md §4.4).

A number joins a following noun as one unit only when the noun counts: JMdict
tags its entry ``ctr``, or it is one of the words JMdict tags otherwise. The
validator, the candidate sheet and the tagger share this one definition.
"""

from __future__ import annotations

from collections.abc import Sequence

from monosashi.jmdict import JMDICT, Entry
from monosashi.kana import DIGITS, NUMERALS, is_hiragana

# Counters JMdict does not tag ctr. SPEC.md §4.4 prints the same list.
COUNTER_WORDS = frozenset(
    {"月", "分", "秒", "番", "割", "時", "円", "号", "位", "目", "人", "週間", "時間", "か月"}
)  # fmt: skip
# These count only after a number written in digits: 50万, but 五十万 is a number alone.
DIGIT_COUNTERS = frozenset({"万", "億", "兆"})


def is_counter_entry(entry: Entry) -> bool:
    """A JMdict entry tagged ``ctr``, or one with a spelling in ``COUNTER_WORDS``."""
    return entry.source == JMDICT and ("ctr" in entry.pos or bool(entry.spellings & COUNTER_WORDS))


def is_number_counter(surface: str, form: str, entries: Sequence[Entry]) -> bool:
    """A number before its counter, with the counter as form: 二十本 with form 本.

    The rest of the surface must be a number, and the counter one of ``entries``
    that counts (``is_counter_entry``), or 万, 億 or 兆 after digits (50万). A kana
    counter must be つ: 百は is a number and a particle.
    """
    if not surface.endswith(form) or surface == form:
        return False
    if all(is_hiragana(ch) for ch in form) and form != "つ":
        return False
    number = surface[: -len(form)]
    if form in DIGIT_COUNTERS and all(ch in DIGITS for ch in number):
        return True
    return all(ch in NUMERALS for ch in number) and any(is_counter_entry(e) for e in entries)

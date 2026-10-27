"""The JMdict candidate sheet a labeler gets for each sentence.

For every substring that is a JMdict spelling, directly or after deinflection,
the sheet lists the entry, the form it reaches and the chain that gets there.
Labelers pick among these instead of recalling entry ids, which they cannot do
reliably. The sheet is a convenience, not the spec: a gold unit may also be a
word with no entry, and the validator, not the sheet, decides what is legal.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from monosashi.counters import DIGIT_COUNTERS, is_counter_entry
from monosashi.deinflect import SURU, deinflect, pos_condition_flags, stops_at_te_auxiliary
from monosashi.deinflect._vendor.engine import conditions_match_mask
from monosashi.jmdict import JMDICT, JMNEDICT, Dictionary, Entry, Sense
from monosashi.kana import (
    DIGITS,
    NUMERALS,
    has_kanji,
    is_hiragana,
    is_katakana,
    is_symbol,
    stretch_key,
    strip_marks,
    to_hiragana,
    widen,
)

MAX_SPAN = 16
MAX_ENTRIES_PER_SPAN = 6
MAX_NAMES_PER_SPAN = 3
MAX_COUNTER = 3


@dataclass(frozen=True, slots=True)
class Candidate:
    start: int
    end: int
    surface: str
    form: str  # the gold form the surface reaches (SPEC.md §5)
    chain: tuple[str, ...]
    entry: Entry


_VS_FLAGS = pos_condition_flags(["vs-i"])


def _fits(entry: Entry, conditions: int, chain: tuple[str, ...], via_suru: bool) -> bool:
    """Whether a deinflection result may land on ``entry`` (the rules of ``chains_to``)."""
    if via_suru:
        return "vs" in entry.pos and (not chain or conditions_match_mask(conditions, _VS_FLAGS))
    if not chain:
        return True
    flags = pos_condition_flags(entry.pos)
    if not flags:
        # exp-only expressions (かもしれない) inflect too, but never through て + an auxiliary
        return "exp" in entry.pos and not stops_at_te_auxiliary(chain, conditions)
    return conditions_match_mask(conditions, flags)


def _collect(
    variants: dict[str, None],
    start: int,
    end: int,
    surface: str,
    wide: str,
    lone_kana: bool,
    dictionary: Dictionary,
    found: dict[tuple[str, int, tuple[str, ...]], Candidate],
) -> None:
    for variant in variants:
        for result in deinflect(variant):
            if lone_kana and not result.chain:
                continue
            lookups = [(result.text, False)]
            if result.text.endswith(SURU) and len(result.text) > len(SURU):
                lookups.append((result.text[: -len(SURU)], True))
            for spelling, via_suru in lookups:
                fitting = [
                    e
                    for e in dictionary.lookup(spelling, JMDICT)
                    if _fits(e, result.conditions, result.chain, via_suru)
                ]
                for entry in fitting[:MAX_ENTRIES_PER_SPAN]:
                    key = (entry.source, entry.seq, result.chain)
                    form = entry.preferred_form(spelling)
                    if spelling == wide != surface and form == wide:
                        form = surface  # ASCII stays ASCII: 3つ is a spelling of ３つ (SPEC.md §2)
                    found.setdefault(key, Candidate(start, end, surface, form, result.chain, entry))


def _katakana_stem(surface: str) -> bool:
    """Katakana first, then only hiragana if anything: ワカった yes, はメ no."""
    i = 0
    while i < len(surface) and is_katakana(surface[i]):
        i += 1
    return i > 0 and all(is_hiragana(ch) for ch in surface[i:])


_MARKS = frozenset("ー〜ぁぃぅぇぉ")
# A doubled あ/え/お, or a tripled い/う: いい and うう are spellings of their own.
_DOUBLED_VOWEL = re.compile(r"([あえお])\1|([いう])\2\2")


def _looks_stretched(hira: str) -> bool:
    """A stretch mark, a small vowel or a repeated bare vowel (すごおおい, ねえええ, かわいいい)."""
    return bool(_MARKS & set(hira[1:])) or bool(_DOUBLED_VOWEL.search(hira))


def _span_candidates(text: str, start: int, end: int, dictionary: Dictionary) -> list[Candidate]:
    surface = text[start:end]
    # A lone hiragana is a particle or an okurigana fragment far more often than
    # a word; listing its dozens of homophone entries would bury the sheet.
    # Its deinflections (し -> する) stay.
    lone_kana = len(surface) == 1 and is_hiragana(surface)
    # The surface as written, widened (3つ) and, for a katakana stem with kana
    # after it (ワカった, ヤバい), in hiragana; the first variant to reach an entry
    # names the form. Only when none of those reaches one, and the surface shows a
    # stretch, is it read as one (すご〜かった, すごおおかった): きれい is a word,
    # not a stretched きれ, and がある is not がる.
    hira = to_hiragana(surface)
    wide = widen(surface)
    direct = [surface, wide] + ([hira] if _katakana_stem(surface) else [])
    stretched = [strip_marks(hira), stretch_key(hira)] if _looks_stretched(hira) else []
    found: dict[tuple[str, int, tuple[str, ...]], Candidate] = {}
    for variants in (direct, stretched):
        _collect(dict.fromkeys(variants), start, end, surface, wide, lone_kana, dictionary, found)
        if found:
            break
    # An expression whose ている is contracted keeps its entry, with no chain: に決まってる
    # is に決まっている (SPEC.md §4.3). The table would strip the いる instead.
    for contracted, full in (("てる", "ている"), ("でる", "でいる")):
        if surface.endswith(contracted):
            spelling = surface[: -len(contracted)] + full
            for entry in dictionary.lookup(spelling, JMDICT):
                if "exp" in entry.pos:
                    found.setdefault(
                        (entry.source, entry.seq, ()),
                        Candidate(start, end, surface, entry.preferred_form(spelling), (), entry),
                    )
    # Names only for spans that look like one: two or more characters with kanji or katakana.
    if len(surface) >= 2 and (has_kanji(surface) or all(is_katakana(ch) for ch in surface)):
        for entry in dictionary.lookup(surface, JMNEDICT)[:MAX_NAMES_PER_SPAN]:
            found.setdefault(
                (entry.source, entry.seq, ()), Candidate(start, end, surface, surface, (), entry)
            )
    return list(found.values())


def is_counter_word(counter: str) -> bool:
    """A counter is not kana, except つ: 百は and 三に are a number and a particle."""
    return counter == "つ" or not all(is_hiragana(ch) for ch in counter)


def _counter_candidates(text: str, dictionary: Dictionary) -> list[Candidate]:
    """A number with the counter after it, when JMdict has no entry for the pair (SPEC.md §4.4).

    二十本 has no entry, so the sheet offers 二十本 with the counter's entry and form 本.
    A counter is what ``counters.is_counter_entry`` says: 回目 (suf) is not one, so
    2回目 is 2回|目. After digits 万, 億 and 兆 count too: 50万 with entry and form 万.
    A pair JMdict lists whole (三本, ３つ) is already on the sheet as its own span.
    """
    out: list[Candidate] = []
    i = 0
    while i < len(text):
        if text[i] not in NUMERALS:
            i += 1
            continue
        j = i
        while j < len(text) and text[j] in NUMERALS:
            j += 1
        # A numeral inside a word (順二さん) starts no number.
        if i > 0 and has_kanji(text[i - 1]):
            i = j
            continue
        # After digits, 万, 億 and 兆 are counters too when they end the number (50万, 50万円 as
        # 50万 + 円); inside one (5万3000円) they are part of it.
        d = i
        while d < j and text[d] in DIGITS:
            d += 1
        if i < d == j - 1 and text[d] in DIGIT_COUNTERS:
            for entry in dictionary.lookup(text[d], JMDICT):
                if "num" in entry.pos:
                    out.append(Candidate(i, d + 1, text[i : d + 1], text[d], (), entry))
        for k in range(j + 1, min(len(text), j + MAX_COUNTER) + 1):
            whole = text[i:k]
            counter = text[j:k]
            if not is_counter_word(counter):
                continue
            if dictionary.lookup(whole, JMDICT) or dictionary.lookup(widen(whole), JMDICT):
                continue
            for entry in dictionary.lookup(counter, JMDICT):
                if is_counter_entry(entry):
                    out.append(Candidate(i, k, whole, entry.preferred_form(counter), (), entry))
        i = j
    return out


def candidate_sheet(text: str, dictionary: Dictionary, max_span: int = MAX_SPAN) -> list[Candidate]:
    """Candidates for every substring of ``text`` up to ``max_span`` characters, in text order."""
    out: list[Candidate] = []
    for start in range(len(text)):
        if is_symbol(text[start]):
            continue
        for end in range(start + 1, min(len(text), start + max_span) + 1):
            if is_symbol(text[end - 1]):
                break
            out += _span_candidates(text, start, end, dictionary)
    out += _counter_candidates(text, dictionary)
    return sorted(out, key=lambda c: (c.start, c.end))


def render_sheet(text: str, candidates: list[Candidate]) -> str:
    """The plain-text sheet shown in a labeler prompt, one candidate per line."""
    lines = [f"TEXT {text}"]
    for c in candidates:
        e = c.entry
        readings = "・".join(sorted(e.readings_of(c.form))) or "?"
        chain = f" chain={','.join(c.chain)}" if c.chain else ""
        star = " ★" if e.common else ""
        source = "name " if e.is_name else ""
        lines.append(
            f"[{c.start}:{c.end}] {c.surface} -> {source}{e.seq} {c.form}【{readings}】"
            f" ({' '.join(e.pos)}){chain} {e.gloss[:60]}{star}"
        )
    return "\n".join(lines)


def _format_sense(n: int, sense: Sense) -> str:
    """``N) gloss; gloss (pos; misc) [info; info] {only spelling}``, each part only when present."""
    parts = [f"{n}) {'; '.join(sense.glosses)}"]
    tags = "; ".join(" ".join(t) for t in (sense.pos, sense.misc) if t)
    if tags:
        parts.append(f"({tags})")
    if sense.info:
        parts.append(f"[{'; '.join(sense.info)}]")
    if sense.kanji or sense.kana:
        parts.append(f"{{only {', '.join(sense.kanji + sense.kana)}}}")
    return " ".join(parts)


def format_senses(entry: Entry) -> str:
    """Every sense of ``entry`` on one line, ``1) gloss; gloss (pos; misc) [info] 2) ...``, nothing truncated."""
    return " ".join(_format_sense(n, s) for n, s in enumerate(entry.senses, 1))


def render_senses(entries: Iterable[Entry]) -> str:
    """One line per distinct entry: ``seq: `` and its ``format_senses``.

    JMdict entries come first, by id, then JMnedict ones, marked ``name`` as on the sheet.
    """
    distinct = {(e.source, e.seq): e for e in entries}
    ordered = sorted(distinct.values(), key=lambda e: (e.is_name, e.seq))
    return "\n".join(f"{'name ' if e.is_name else ''}{e.seq}: {format_senses(e)}" for e in ordered)

"""Meaning checks for gold records (SPEC.md §Validation).

Every rule has a short id so labelers, tests and the review queue can refer to
it. ``validate_record`` never raises on bad data; it reports issues. Advisories
(``ADVISORY_RULES``) come from ``advisory_issues`` instead: they flag a label for
review without failing it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from monosashi import SPEC_VERSION
from monosashi.counters import is_number_counter
from monosashi.deinflect import deinflect, reach, transform_ids
from monosashi.jmdict import JMDICT, JMNEDICT, Dictionary, Entry
from monosashi.kana import (
    DIGIT_COMMAS,
    DIGITS,
    LENGTH_DASH,
    SPACES,
    WAVE_DASH,
    drop_kanji_stretch,
    fold_reading,
    full_size_vowels,
    has_kanji,
    has_katakana_letter,
    is_hiragana,
    is_kana_text,
    is_katakana,
    is_normalized,
    is_reading,
    is_symbol,
    marks_to_vowels,
    read_inner_symbols,
    stretch_key,
    strip_marks,
    to_hiragana,
    voiced,
    widen,
)
from monosashi.licenses import ALLOWED_SOURCE_LICENSES
from monosashi.schema import (
    CONTENT_KINDS,
    FUNCTION_KINDS,
    LABEL_STATUSES,
    REGISTERS,
    SLICES,
    UNIT_KINDS,
    Record,
    SchemaError,
    Unit,
    load_records,
)
from monosashi.taxonomy import CATEGORIES

# Rules that flag a label for review but never fail it (SPEC.md §8).
ADVISORY_RULES = frozenset({"counter-whole-entry"})


@dataclass(frozen=True, slots=True)
class Issue:
    record_id: str
    unit: int | None  # index into record.units, None for record-level issues
    rule: str
    message: str

    def __str__(self) -> str:
        where = self.record_id if self.unit is None else f"{self.record_id} unit {self.unit}"
        return f"{where}: [{self.rule}] {self.message}"


def _entries_for(unit: Unit, dictionary: Dictionary) -> list[Entry]:
    source = JMNEDICT if unit.kind == "name" else JMDICT
    return list(dictionary.entries(unit.entries, source))


def _check_record_fields(record: Record) -> Iterable[Issue]:
    def issue(rule: str, message: str) -> Issue:
        return Issue(record.id, None, rule, message)

    if not record.text:
        yield issue("text-empty", "text is empty")
    if not is_normalized(record.text):
        yield issue("text-normalized", "text is not normalized (NFC, fullwidth katakana, 〜)")
    if record.register not in REGISTERS:
        yield issue("register", f"unknown register {record.register!r}")
    if record.slice not in SLICES:
        yield issue("slice", f"unknown slice {record.slice!r}")
    if record.label.status not in LABEL_STATUSES:
        yield issue("label-status", f"unknown label status {record.label.status!r}")
    if record.label.spec != SPEC_VERSION:
        yield issue("label-spec", f"labeled against spec {record.label.spec}, current is {SPEC_VERSION}")
    if record.source.license not in ALLOWED_SOURCE_LICENSES:
        yield issue("license", f"source license {record.source.license!r} is not on the allowlist")


def _check_spans(record: Record) -> Iterable[Issue]:
    text = record.text
    covered = [False] * len(text)
    previous_end = 0
    for i, unit in enumerate(record.units):
        if not (0 <= unit.start < unit.end <= len(text)):
            yield Issue(record.id, i, "span-bounds", f"span [{unit.start}, {unit.end}) is outside the text")
            continue
        if text[unit.start : unit.end] != unit.surface:
            yield Issue(
                record.id,
                i,
                "span-surface",
                f"text[{unit.start}:{unit.end}] is {text[unit.start : unit.end]!r}",
            )
        if unit.start < previous_end:
            yield Issue(record.id, i, "span-order", "units overlap or are out of order")
        previous_end = max(previous_end, unit.end)
        if is_symbol(unit.surface[0]) or is_symbol(unit.surface[-1]):
            yield Issue(
                record.id, i, "span-symbol", "a unit may not start or end with punctuation or a symbol"
            )
        for k in range(1, len(unit.surface) - 1):
            named = unit.kind == "name" or "name" in unit.targets
            if is_symbol(unit.surface[k]) and not _inner_symbol_allowed(unit.surface, k, named):
                yield Issue(
                    record.id,
                    i,
                    "span-inner-symbol",
                    f"{unit.surface[k]!r} inside a unit must split one word (SPEC.md §1)",
                )
        for k in range(unit.start, unit.end):
            covered[k] = True
    for k, ch in enumerate(text):
        if covered[k] or is_symbol(ch):
            continue
        # A 〜 after anything but kana marks a range (10時〜12時) and may stand
        # outside any unit; after kana it stretches that word (ね〜) and belongs to it.
        previous = text[k - 1] if k else ""
        if ch == WAVE_DASH and not (previous and (is_hiragana(previous) or is_katakana(previous))):
            continue
        yield Issue(record.id, None, "coverage", f"character {ch!r} at {k} belongs to no unit")


# The separators a name may hold besides a space (SPEC.md §1), and their fullwidth forms.
_NAME_SEPARATORS = "・=＝-－"


def _is_kana(ch: str) -> bool:
    return is_hiragana(ch) or is_katakana(ch)


def _inner_symbol_allowed(surface: str, k: int, name: bool) -> bool:
    """SPEC.md §1: a line-break space, a digit-group comma, a ― between kana,
    Aozora's ／＼, or a separator inside a name."""
    ch, before, after = surface[k], surface[k - 1], surface[k + 1]
    if ch in SPACES:
        return True
    if ch in DIGIT_COMMAS:
        return before in DIGITS and after in DIGITS
    if ch == LENGTH_DASH:
        run = surface[:k].rstrip(LENGTH_DASH), surface[k:].lstrip(LENGTH_DASH)
        return all(run) and _is_kana(run[0][-1]) and _is_kana(run[1][0])
    if ch == "／":
        return k >= 2 and after == "＼"  # it repeats the two characters before it
    if ch == "＼":
        return before == "／"
    return name and ch in _NAME_SEPARATORS


def _check_unit_fields(record: Record, i: int, unit: Unit) -> Iterable[Issue]:
    def issue(rule: str, message: str) -> Issue:
        return Issue(record.id, i, rule, message)

    if unit.kind not in UNIT_KINDS:
        yield issue("kind", f"unknown kind {unit.kind!r}")
        return
    if unit.kind in FUNCTION_KINDS:
        if unit.entries:
            yield issue("function-entries", "function units carry no entry ids")
        if unit.normalized is not None:
            yield issue("function-normalized", "function units carry no normalized form")
        if unit.targets:
            yield issue("function-targets", "function units carry no targets (SPEC.md §4.8)")
    if unit.kind in CONTENT_KINDS - {"name"}:
        for key in ("form", "reading", "form_reading"):
            if getattr(unit, key) is None:
                yield issue("content-fields", f"{unit.kind} unit is missing {key}")
    for key in ("reading", "form_reading"):
        value = getattr(unit, key)
        if value is not None and not is_reading(value):
            yield issue("reading-kana", f"{key} {value!r} must be hiragana")
    if (
        unit.reading is not None
        and is_kana_text(unit.surface)
        and unit.reading != to_hiragana(read_inner_symbols(unit.surface))
        and unit.kind != "name"
    ):
        yield issue(
            "reading-kana-surface", f"a kana surface reads as itself in hiragana, not {unit.reading!r}"
        )
    if len(set(unit.entries)) != len(unit.entries):
        yield issue("entries-duplicate", "an entry id is listed twice")
    previous = unit.start
    for point in unit.split_points:
        if not previous < point < unit.end:
            yield issue("split-points", f"split point {point} must fall strictly inside the unit, ascending")
        previous = point
    for target in unit.targets:
        if target not in CATEGORIES:
            yield issue("targets", f"unknown category {target!r}")
    unknown = sorted(set(unit.chain) - transform_ids())
    if unknown:
        yield issue("chain-ids", f"unknown transform id(s) {', '.join(unknown)}")


def _check_orthography(record: Record, i: int, unit: Unit) -> Iterable[Issue]:
    """The form keeps the surface's script: a kana surface has a kana form (SPEC.md §Form)."""
    if unit.form is None or unit.kind == "name":
        return
    if not has_kanji(unit.surface) and has_kanji(unit.form):
        yield Issue(record.id, i, "form-orthography", f"kana surface {unit.surface!r} needs a kana form")


def _all_readings(entry: Entry) -> frozenset[str]:
    return frozenset(to_hiragana(r).replace("・", "") for _, r in entry.pairs)


def _form_readings(entry: Entry, form: str) -> frozenset[str]:
    """The readings a form_reading may take: the form's own, or any of the entry's for a
    digit form, which reads as it does in context (４ read よん, SPEC.md §4.4)."""
    if form and all(ch in DIGITS for ch in form):
        return _all_readings(entry)
    return entry.readings_of(form)


def _rendaku(unit: Unit, previous: Unit | None) -> bool:
    """A voiced first kana right after another content unit: 皿 read ざら in 灯明|皿 (SPEC.md §5)."""
    if previous is None or previous.end != unit.start or previous.kind not in CONTENT_KINDS:
        return False
    if not unit.reading or not unit.form_reading:
        return False
    first = voiced(unit.form_reading[0])
    return first is not None and unit.reading == first + unit.form_reading[1:]


def _check_dictionary(
    record: Record,
    i: int,
    unit: Unit,
    dictionary: Dictionary,
    previous: Unit | None,
    next_unit: Unit | None,
) -> Iterable[Issue]:
    def issue(rule: str, message: str) -> Issue:
        return Issue(record.id, i, rule, message)

    entries = _entries_for(unit, dictionary)
    missing = sorted(set(unit.entries) - {e.seq for e in entries})
    if missing:
        source = "JMnedict" if unit.kind == "name" else "JMdict"
        yield issue("entries-exist", f"not in the pinned {source}: {', '.join(map(str, missing))}")
    if unit.normalized is not None:
        normalized_entries = list(dictionary.entries(unit.normalized.entries))
        if len(normalized_entries) != len(unit.normalized.entries):
            yield issue("normalized-exist", "a normalized entry id is not in the pinned JMdict")
        if not unit.normalized.entries:
            yield issue("normalized-entries", "normalized needs at least one entry id")
        elif not any(e.has_spelling(unit.normalized.form) for e in normalized_entries):
            yield issue("normalized-form", f"{unit.normalized.form!r} is not a spelling of its entries")
        elif not any(
            unit.normalized.form_reading in e.readings_of(unit.normalized.form) for e in normalized_entries
        ):
            yield issue(
                "normalized-reading", f"{unit.normalized.form_reading!r} is not a reading of its form"
            )
    if unit.kind == "name" or unit.kind in FUNCTION_KINDS or unit.form is None:
        return
    # SPEC.md §Kinds: an expression needs an exp-tagged entry, and a unit whose
    # entries are only expressions is an expression (or an interjection, for exp+int
    # entries such as すげー), never a plain word. JMdict's POS are the union over
    # senses, so ちょっと (adv, exp) is a word that also has an exp sense.
    if entries:
        any_exp = any("exp" in e.pos for e in entries)
        all_exp = all("exp" in e.pos and not _has_content_pos(e.pos) for e in entries)
        if unit.kind == "expression" and not any_exp:
            yield issue("kind-expression", f"entries {list(unit.entries)} are not tagged exp; this is a word")
        elif unit.kind == "word" and all_exp:
            yield issue(
                "kind-expression", f"entries {list(unit.entries)} are tagged exp; this is an expression"
            )
    form = unit.form
    spelled = [e for e in entries if e.has_spelling(form)]
    reached = _reach(
        unit.surface,
        entries,
        elongation="elongation" in unit.targets,
        reading=unit.reading,
        # With a chain the kanji may read otherwise than in the form (来えへん, けえへん).
        form_reading=None if unit.chain else unit.form_reading,
    )
    if entries and not spelled:
        hint = f"; the surface gives {sorted(reached.expected)[0]!r}" if reached.expected else ""
        yield issue("form-spelling", f"{form!r} is not a spelling of entries {list(unit.entries)}{hint}")
    if (
        spelled
        and unit.form_reading is not None
        and not any(unit.form_reading in _form_readings(e, form) for e in spelled)
    ):
        yield issue("form-reading", f"{unit.form_reading!r} is not a reading of {form!r}")
    # SPEC.md §5: the gold form is what the surface as written reaches: its own
    # spelling (往く, スゴイ), or the standard spelling for a search-only one
    # (すご〜い -> すごい, つき合った -> 付き合う).
    wrong_form = bool(
        spelled and reached.expected and widen(form) not in {widen(x) for x in reached.expected}
    )
    if wrong_form:
        yield issue(
            "form-orthography",
            f"{unit.surface!r} gives the form {sorted(reached.expected)[0]!r}, not {form!r}",
        )
    elif not reached.expected and spelled and form not in {e.preferred_form(form) for e in spelled}:
        standard = sorted({e.preferred_form(form) for e in spelled})[0]
        yield issue("form-search-only", f"{form!r} is a search-only spelling; the form is {standard!r}")
    elif not reached.expected and spelled and _VIA_READING & set(unit.targets):
        forms = _unlisted_forms(unit, spelled)
        if form not in forms:
            standard = sorted(forms)[0]
            yield issue(
                "form-orthography", f"{unit.surface!r} is an unlisted spelling; the form is {standard!r}"
            )
    if (
        unit.surface == form
        and not unit.chain
        and unit.reading is not None
        and unit.form_reading is not None
        and unit.reading != unit.form_reading
        and not _rendaku(unit, previous)
    ):
        yield issue("reading-form-reading", "the surface is the form, so reading and form_reading agree")
    # A wrong form already explains any chain mismatch, so only maximality is checked.
    yield from _check_chain(record, i, unit, entries, reached, next_unit, check_form=not wrong_form)


@dataclass(frozen=True, slots=True)
class _Reach:
    """What a surface reaches through deinflection (SPEC.md §4.1, §5).

    ``expected``: the gold forms reached by the first surface variant that reaches
    any (the surface as written wins over its hiragana or unstretched variants).
    ``chains``: every spelling and gold form reached by any variant, with chains.
    """

    expected: frozenset[str]
    chains: dict[str, frozenset[tuple[str, ...]]]

    def chains_for(self, form: str) -> set[tuple[str, ...]]:
        wide = widen(form)
        return {c for key, chains in self.chains.items() if widen(key) == wide for c in chains}


# POS that make an exp-tagged entry a word as well (ちょっと: adv, exp; あがる: v5r, exp).
_CONTENT_POS = frozenset({"n", "adv", "adv-to", "pn", "num", "ctr", "conj"})
_CONTENT_POS_PREFIXES = ("adj-", "v1", "v2", "v4", "v5", "vk", "vs", "vz")


def _has_content_pos(pos: Sequence[str]) -> bool:
    return any(p in _CONTENT_POS or p.startswith(_CONTENT_POS_PREFIXES) for p in pos)


# A run of small っ/ッ, which an emphatic っ makes of a word's own one (ずっっと).
_SOKUON_RUN = re.compile(r"([っッ])[っッ]+")


def _variants(
    surface: str,
    stretch: bool = True,
    *,
    elongation: bool = False,
    reading: str | None = None,
    form_reading: str | None = None,
) -> list[str]:
    """The surface as written, ASCII widened (3つ), in hiragana (ヤった), without
    stretch marks (すご〜かった) and, with ``stretch``, as a stretch (SPEC.md §4.8):
    reduced to its vowel skeleton (すごおおい), with ー as its vowel (気をつけねー), and
    without a vowel that ``reading`` shows stretching a kanji (気い, 見いひん; see
    ``drop_kanji_stretch``). With ``elongation`` too, without an emphatic っ (写るーっ,
    ほんっと, ずっっと) and with small vowels full-size (わぉ); only a unit tagged
    ``elongation`` gets these.

    Without ``stretch`` (chain-maximal) the pair of two units is never read as a stretch.
    """
    hira = to_hiragana(surface)
    # Without ー/〜 only, too: strip_marks also drops a final small vowel, which
    # turns あり得ねぇー into あり得ね, while あり得ねぇ still deinflects.
    marks_only = hira.replace("ー", "").replace("〜", "")
    variants = [surface, widen(surface), hira, marks_only, strip_marks(hira)]
    if stretch:
        variants += [stretch_key(hira), marks_to_vowels(hira)]
        kanji = drop_kanji_stretch(hira, reading, form_reading)
        if kanji is not None:
            variants.append(kanji)
        if elongation:
            # In the surface's own script as well: ホンット reaches ホント.
            for base in (surface.replace("ー", "").replace("〜", ""), marks_only):
                final = base.rstrip("っッ")
                inner = final.replace("っ", "").replace("ッ", "")
                for cut in (final, _SOKUON_RUN.sub(r"\1", final), inner):
                    variants += [cut, stretch_key(cut)]
                variants.append(full_size_vowels(inner))
    return list(dict.fromkeys(variants))


def _reach(
    surface: str,
    entries: Sequence[Entry],
    stretch: bool = True,
    *,
    elongation: bool = False,
    reading: str | None = None,
    form_reading: str | None = None,
) -> _Reach:
    expected: set[str] = set()
    chains: dict[str, set[tuple[str, ...]]] = {}
    skeleton = stretch_key(surface)
    katakana = has_katakana_letter(surface)
    variants = _variants(surface, stretch, elongation=elongation, reading=reading, form_reading=form_reading)
    for variant in variants:
        if not entries:
            # No entry to take POS from: any deinflection counts, and no form is expected.
            for d in deinflect(variant):
                chains.setdefault(d.text, set()).add(d.chain)
            continue
        gold: set[str] = set()
        for entry in entries:
            reached = reach(variant, entry.spellings, entry.pos)
            if variant == skeleton:
                # A stretch reaches every spelling with its vowel skeleton, in its
                # script: ねえええ reaches ね, ねー and ねえ.
                for spelling in entry.spellings:
                    if stretch_key(spelling) == skeleton and has_katakana_letter(spelling) == katakana:
                        reached.setdefault(spelling, []).append(())
            for spelling, found in reached.items():
                preferred = entry.preferred_form(spelling)
                gold.add(preferred)
                for key in (spelling, preferred):
                    chains.setdefault(key, set()).update(found)
        if gold and not expected:
            expected = gold
    return _Reach(frozenset(expected), {k: frozenset(v) for k, v in chains.items()})


# Targets under which a spelling JMdict lacks relates to its form through the reading (§5).
_VIA_READING = frozenset({"kanji-variant", "archaic-classical"})


def _reading_chains(unit: Unit, entries: Sequence[Entry]) -> set[tuple[str, ...]]:
    """Chains by which an unlisted spelling's reading reaches its form_reading (SPEC.md §5).

    塗みれた (form 塗れる) relates through まみれた -> まみれる, by `-た`. Only for a
    unit tagged ``kanji-variant`` or ``archaic-classical`` whose form_reading is a
    reading of its form. Both readings are compared with ヴ as バ and ゆう as いう
    (ヴォイド, どーゆう), and as stretches.
    """
    form, reading, form_reading = unit.form, unit.reading, unit.form_reading
    if not _VIA_READING & set(unit.targets) or form is None or reading is None or form_reading is None:
        return set()
    spelled = [e for e in entries if form_reading in e.readings_of(form)]
    reading, target = fold_reading(reading), fold_reading(form_reading)
    chains: set[tuple[str, ...]] = set()
    for entry in spelled:
        targets = [target] + (_without_particle(form, target) if "exp" in entry.pos else [])
        if any(stretch_key(reading) == stretch_key(t) for t in targets):
            chains.add(())
        for variant in _variants(reading, elongation="elongation" in unit.targets):
            for found in reach(variant, targets, entry.pos).values():
                chains.update(found)
    return chains


_PHRASE_PARTICLES = "がをにの"


def _without_particle(form: str, form_reading: str) -> list[str]:
    """``form_reading`` without one particle the phrase spells in kana (SPEC.md §5): 腹減って
    reads as 腹が減る (はらがへる) with its が dropped, お腹すいて as お腹が空く."""
    inner = range(1, len(form_reading) - 1)
    return [
        form_reading[:k] + form_reading[k + 1 :]
        for k in inner
        if form_reading[k] in _PHRASE_PARTICLES and form_reading[k] in form
    ]


def _unlisted_forms(unit: Unit, spelled: Sequence[Entry]) -> set[str]:
    """The form an unlisted spelling takes (SPEC.md §5): per entry, its first standard
    spelling in the surface's script that the reading relates to by the unit's chain
    (カンヴァス: カンバス, not キャンバス), else its first (当てがった: 宛がう)."""
    forms: set[str] = set()
    for entry in spelled:
        spellings = entry.standard_spellings(unit.surface)
        related = [
            s
            for s in spellings
            if any(
                unit.chain in _reading_chains(replace(unit, form=s, form_reading=r), [entry])
                for r in entry.readings_of(s)
            )
        ]
        forms.add((related or spellings)[0])
    return forms


# A sentence-final particle stays out of a chain it would join only through a
# contracted -いる or -おく: 買って|よ, not 買ってよ as ていよ (SPEC.md §4.1).
_SENTENCE_FINAL = frozenset({"よ", "ね", "ねえ", "ねぇ"})
_CONTRACTED = frozenset({"-いる", "-おく"})


def _check_chain(
    record: Record,
    i: int,
    unit: Unit,
    entries: Sequence[Entry],
    reached: _Reach,
    next_unit: Unit | None,
    *,
    check_form: bool,
) -> Iterable[Issue]:
    assert unit.form is not None

    def issue(rule: str, message: str) -> Issue:
        return Issue(record.id, i, rule, message)

    chains = reached.chains_for(unit.form) | _reading_chains(unit, entries)
    # Relations other rules report: two spellings of one entry (form-orthography
    # decides which is the form), or a form that is no spelling (form-spelling).
    same_entry = any(e.has_spelling(unit.surface) and e.has_spelling(unit.form) for e in entries)
    unspelled = bool(entries) and not any(e.has_spelling(unit.form) for e in entries)
    if check_form and unit.chain:
        if unit.chain not in chains:
            found = " or ".join("(" + ", ".join(c) + ")" for c in sorted(chains) if c) or "none"
            yield issue(
                "chain-deinflects",
                f"{unit.surface!r} does not reach {unit.form!r} by that chain; found {found}",
            )
    elif (
        check_form
        and not unit.chain
        and widen(unit.surface) != widen(unit.form)
        and () not in chains
        and not is_number_counter(unit.surface, unit.form, entries)
        and not same_entry
        and not unspelled
    ):
        if chains:
            yield issue("chain-missing", f"{unit.surface!r} inflects {unit.form!r}; record its chain")
        else:
            yield issue(
                "form-relation",
                f"nothing relates {unit.surface!r} to {unit.form!r}: no chain, spelling, stretch or counter",
            )
    if next_unit is None or next_unit.start != unit.end:
        return
    # Only a chain absorbs the next unit; reading the pair as a vowel stretch would
    # make 思う|とおり look like 思うとる and これで|ええ like a stretched これで.
    # Stretch marks still count: 食べ|たーい is 食べたーい.
    absorbing = _reach(unit.surface + next_unit.surface, entries, stretch=False).chains_for(unit.form)
    if next_unit.surface in _SENTENCE_FINAL:
        absorbing = {c for c in absorbing if not _CONTRACTED & set(c)}
    if absorbing:
        yield issue("chain-maximal", f"the unit continues into the next unit {next_unit.surface!r}")


def _read_inner(unit: Unit) -> Unit:
    """The unit with its surface's inner symbols read as §1 says (頑張 って -> 頑張って); a word
    JMdict lists as a name drops its separators too (エール・フランス -> エールフランス)."""
    surface = read_inner_symbols(unit.surface)
    if "name" in unit.targets and unit.kind != "name":
        surface = "".join(ch for ch in surface if ch not in _NAME_SEPARATORS)
    return unit if surface == unit.surface else replace(unit, surface=surface)


def validate_record(record: Record, dictionary: Dictionary) -> list[Issue]:
    issues = list(_check_record_fields(record))
    issues += _check_spans(record)
    units = [_read_inner(u) for u in record.units]
    for i, unit in enumerate(units):
        issues += _check_unit_fields(record, i, unit)
        issues += _check_orthography(record, i, unit)
        if unit.kind in UNIT_KINDS:
            previous = units[i - 1] if i else None
            next_unit = units[i + 1] if i + 1 < len(units) else None
            # A unit with no entry has its surface as written for its form (44,276, SPEC.md
            # §4.4), so its dictionary checks see that surface, not the one read for lookups.
            checked = unit if unit.entries else record.units[i]
            issues += _check_dictionary(record, i, checked, dictionary, previous, next_unit)
    return issues


def advisory_issues(record: Record, dictionary: Dictionary) -> list[Issue]:
    """Issues that flag a unit for review without failing it (``ADVISORY_RULES``).

    ``counter-whole-entry``: a number + counter labeled with the counter's entry
    although JMdict lists the whole span. That is right when none of the whole
    entry's senses fits (三歳年上), which only a reviewer can judge (SPEC.md §4.4).
    """
    issues: list[Issue] = []
    for i, unit in enumerate(map(_read_inner, record.units)):
        if unit.kind not in CONTENT_KINDS - {"name"} or unit.form is None:
            continue
        if is_number_counter(unit.surface, unit.form, _entries_for(unit, dictionary)) and (
            dictionary.lookup(unit.surface, JMDICT) or dictionary.lookup(widen(unit.surface), JMDICT)
        ):
            issues.append(
                Issue(
                    record.id,
                    i,
                    "counter-whole-entry",
                    f"JMdict has {unit.surface!r} itself; use that entry if one of its senses fits"
                    " (SPEC.md §4.4)",
                )
            )
    return issues


def validate_files(paths: Iterable[Path], dictionary: Dictionary, *, advisories: bool = False) -> list[Issue]:
    """Validate JSONL files; also reports schema errors and duplicate ids across files.

    With ``advisories``, the advisory issues (``ADVISORY_RULES``) are included too.
    """
    issues: list[Issue] = []
    seen: dict[str, Path] = {}
    for path in paths:
        try:
            records = list(load_records(path))
        except SchemaError as exc:
            issues.append(Issue(str(path), None, "schema", str(exc)))
            continue
        for record in records:
            if record.id in seen:
                issues.append(Issue(record.id, None, "id-duplicate", f"id also used in {seen[record.id]}"))
            seen[record.id] = path
            issues += validate_record(record, dictionary)
            if advisories:
                issues += advisory_issues(record, dictionary)
    return issues

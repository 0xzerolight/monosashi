"""Scoring a tool's predictions against gold records (SPEC.md §7).

Every metric is a ratio of two counts summed over records, so a record's
contribution is a small ``Counter`` and the paired bootstrap only resamples
those counters. The counters are named ``<metric>.ok`` and ``<metric>.n``
(``.tp``, ``.pred`` and ``.gold`` for an F1).
"""

from __future__ import annotations

import random
import statistics
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache

from monosashi.counters import is_number_counter
from monosashi.deinflect import SURU, deinflect
from monosashi.jmdict import JMDICT, JMNEDICT, Dictionary, Entry
from monosashi.kana import has_kanji, is_symbol, read_inner_symbols, to_hiragana, widen
from monosashi.predictions import FAILED, OPTIONAL_FIELDS, Description, PredictedUnit, Prediction, against
from monosashi.schema import CONTENT_KINDS, FUNCTION_KINDS, Record, Unit

BOOTSTRAP_SAMPLES = 1000
BOOTSTRAP_SEED = 20261015

# Metric name -> what it measures; the report shows them in this order.
METRICS = {
    "card": "card-ready rate, strict",
    "card_lenient": "card-ready rate, lenient",
    "junk": "junk rate (lower is better)",
    "seg": "segmentation F1, strict",
    "seg_lenient": "segmentation F1, lenient (boundaries)",
    "content": "content-unit F1",
    "form": "form accuracy, exact spans",
    "reading": "reading accuracy, exact spans",
    "form_reading": "form_reading accuracy, exact spans",
    "form_tiled": "form accuracy, tiled",
    "reading_tiled": "reading accuracy, tiled",
    "form_reading_tiled": "form_reading accuracy, tiled",
    "entry": "entry accuracy",
    "normalized": "normalization accuracy",
}
F1_METRICS = frozenset({"seg", "seg_lenient", "content"})
# Transforms that change a verb's voice: the derived-verb alternatives of §7 run through these only.
VOICE_TRANSFORMS = frozenset({"potential", "potential or passive", "passive", "causative", "short causative"})
# A chain starting with these accepts the entry it passes through too: 多い + -すぎる accepts
# 多すぎる, 恥ずかしい + -がる accepts 恥ずかしがる (§7 Derived verbs).
PASSED_THROUGH = VOICE_TRANSFORMS | {"-すぎる", "-がる"}


def _hira(text: str | None) -> str | None:
    return None if text is None else to_hiragana(text)


def _symbol_only(text: str, start: int, end: int) -> bool:
    return all(is_symbol(ch) for ch in text[start:end])


def _reads_as(reading: str | None, gold: str | None) -> bool:
    """The tool gave a reading, and in hiragana it is the gold one."""
    return reading is not None and to_hiragana(reading) == gold


def _has_no_card(unit: Unit) -> bool:
    """An interjection with no entry: a laugh, a call or a shout (シシシ, どおおおおっ) or a
    stammered fragment (§4.8). There is no dictionary card to make for it."""
    return unit.kind == "interjection" and not unit.entries


def _paired(spelling: str, reading: str, chain: tuple[str, ...]) -> set[tuple[str, str]]:
    """A spelling and its reading deinflected by exactly ``chain``, paired only through rules that
    end in the same conditions: される gives (する, する) and (す, す), never (する, す)."""
    by_conditions: dict[int, tuple[set[str], set[str]]] = {}
    for side, text in enumerate((spelling, reading)):
        for d in deinflect(text):
            if d.chain == chain:
                by_conditions.setdefault(d.conditions, (set(), set()))[side].add(d.text)
    return {(s, r) for spellings, readings in by_conditions.values() for s in spellings for r in readings}


def _voice_runs(chain: tuple[str, ...]) -> list[tuple[str, ...]]:
    """The chain's leading runs of voice transforms, or -すぎる and -がる: (causative, passive, -た)
    has (causative,) and (causative, passive)."""
    runs = []
    for i, transform in enumerate(chain):
        if transform not in PASSED_THROUGH:
            break
        runs.append(chain[: i + 1])
    return runs


@dataclass(frozen=True, slots=True)
class _Tool:
    fields: frozenset[str]
    partition: bool

    def has(self, field: str) -> bool:
        return field in self.fields


def _is_content(unit: PredictedUnit, tool: _Tool, gold_function_spans: set[tuple[int, int]]) -> bool:
    """A unit's own kind decides; without one, every unit of a content-only tool is a card,
    and a partition tool's unit is content unless it is exactly a gold function unit."""
    if tool.has("kind") and unit.kind is not None:
        return unit.kind not in FUNCTION_KINDS
    return not tool.partition or (unit.start, unit.end) not in gold_function_spans


class Scorer:
    """Scores predictions against gold, looking spellings up in the pinned dictionary."""

    def __init__(self, dictionary: Dictionary) -> None:
        self.dictionary = dictionary

    def _accepted_entries(self, unit: Unit) -> list[Entry]:
        """The unit's entries and its normalized entries (JMnedict for a name)."""
        ids = (*unit.entries, *(unit.normalized.entries if unit.normalized else ()))
        return list(self.dictionary.entries(ids, JMNEDICT if unit.kind == "name" else JMDICT))

    def accepted_forms(self, unit: Unit) -> frozenset[str]:
        """Every spelling a tool may give as this unit's form, widened (§7 Accepted forms)."""
        forms = {s for e in self._accepted_entries(unit) for s in e.spellings}
        if unit.form is not None:
            forms.add(unit.form)
            if self._suru_form(unit) is not None:
                forms.add(unit.form + SURU)  # 勉強している: 勉強 or 勉強する
        if self._counter_form(unit):
            forms.add(unit.surface)  # 二十本, form 本: the whole surface too
        return frozenset(widen(f) for f in forms)

    def _counter_form(self, unit: Unit) -> bool:
        """A number + counter whose form is the counter: 二十本, form 本 (§4.4)."""
        if unit.form is None or unit.kind == "name":
            return False
        entries = list(self.dictionary.entries(unit.entries, JMDICT))
        return is_number_counter(read_inner_symbols(unit.surface), unit.form, entries)

    def _suru_form(self, unit: Unit) -> str | None:
        """勉強する for a noun + する unit (勉強している, form 勉強), widened; else None."""
        if unit.form is None or self._noun_end(unit) is None:
            return None
        return widen(unit.form + SURU)

    def _noun_end(self, unit: Unit) -> int | None:
        """Where the noun of a noun + する unit ends, or None.

        The unit's entry is a vs noun and the rest of the surface deinflects to
        する by the unit's chain: 勉強|した. A stretched vs noun with no する
        (了解っ) has no noun end.
        """
        if unit.form is None or unit.surface == unit.form:
            return None
        if not any("vs" in e.pos for e in self.dictionary.entries(unit.entries, JMDICT)):
            return None
        for i in range(1, len(unit.surface)):
            if any(d.text == SURU and d.chain == unit.chain for d in deinflect(unit.surface[i:])):
                return unit.start + i
        return None

    def form_ok(self, unit: Unit, form: str | None) -> bool:
        return form is not None and widen(form) in self.accepted_forms(unit)

    def normalized_forms(self, unit: Unit) -> frozenset[str]:
        """The spellings of the unit's normalized entries, widened."""
        ids = unit.normalized.entries if unit.normalized else ()
        return frozenset(widen(s) for e in self.dictionary.entries(ids, JMDICT) for s in e.spellings)

    def form_reading_ok(self, unit: Unit, form: str | None, form_reading: str | None) -> bool:
        """The gold form_reading, or the one that goes with the alternative form the tool gave.

        A spelling of a normalized entry brings the normalized form_reading
        (すごい, すごい for すげー), and the noun + する form brings the gold
        form_reading + する (勉強する, べんきょうする), so a coherent card passes.
        """
        reading = _hira(form_reading)
        if reading is None or unit.form_reading is None:
            return False
        if reading == unit.form_reading:
            return True
        if form is None:
            return False
        normalized = unit.normalized
        if normalized and reading == normalized.form_reading and widen(form) in self.normalized_forms(unit):
            return True
        return reading == unit.form_reading + SURU and widen(form) == self._suru_form(unit)

    def _one_entry(self, unit: Unit, form: str, form_reading: str) -> bool:
        """The form and form_reading are a spelling and a reading of one accepted entry (§7).

        The noun + する form counts as the noun's spelling, read as the noun + する:
        勉強する goes with べんきょうする. 凄い with すげー, which only the variant
        entry reads, is no pair.
        """
        reading = to_hiragana(form_reading)
        if widen(form) == self._suru_form(unit):
            if not reading.endswith(SURU):
                return False
            form, reading = form[: -len(SURU)], reading[: -len(SURU)]
        return any(
            e.has_spelling(form) and reading in {to_hiragana(k).replace("・", "") for k in e.kana}
            for e in self._accepted_entries(unit)
        )

    def voice_alternatives(self, unit: Unit) -> frozenset[tuple[str, str]]:
        """The other verb a derived-verb or voice-chain unit accepts, as (widened spelling, reading) pairs.

        A unit whose form is a verb derived by a voice transform accepts the base
        verb, from its form or any kanji spelling of its entry: 使える (chain
        negative) accepts 使う and 遣う, read つかう. A bare kana spelling would
        reach homophones of other entries (かえる -> かう), so only the form's own
        counts. A unit whose chain starts with voice transforms
        accepts the derived verb: 行う with chain passive, -た accepts 行われる, read
        おこなわれる (``_card_pair_ok`` takes its other spellings). Both come from
        the deinflector's traces, spelling and reading through the same rules, so
        each alternative is a pair (§7 Derived verbs).
        """
        if unit.form is None or unit.form_reading is None:
            return frozenset()
        entries = self.dictionary.entries(unit.entries, JMDICT)
        spelled = {
            (unit.form, unit.form_reading),
            *((s, to_hiragana(r)) for e in entries for s, r in e.pairs if has_kanji(s)),
        }
        pairs = set()
        for spelling, reading in spelled:
            voices = {d.chain for d in deinflect(spelling) if d.chain and set(d.chain) <= VOICE_TRANSFORMS}
            pairs |= {pair for voice in voices for pair in _paired(spelling, reading, voice)}
        if unit.reading is not None:
            base = (unit.form, unit.form_reading)
            for voice in _voice_runs(unit.chain):
                rest = unit.chain[len(voice) :]
                pairs |= {p for p in _paired(unit.surface, unit.reading, rest) if base in _paired(*p, voice)}
        return frozenset((widen(s), to_hiragana(r)) for s, r in pairs)

    def _entry_card_ok(self, unit: Unit, form: str, form_reading: str) -> bool:
        """An accepted form and form_reading that belong to one accepted entry."""
        return (
            self.form_ok(unit, form)
            and self.form_reading_ok(unit, form, form_reading)
            and self._one_entry(unit, form, form_reading)
        )

    def _card_pair_ok(self, unit: Unit, form: str | None, form_reading: str | None) -> bool:
        """The form and form_reading make a card for the unit, or a card of its base or derived verb."""
        if form is None or form_reading is None:
            return False
        if self._entry_card_ok(unit, form, form_reading):
            return True
        # A voice chain takes the derived verb in any of its spellings: 為れる (される) for
        # する + passive, since it deinflects to 為る (する) by the chain's voice transforms.
        reading = to_hiragana(form_reading)
        for voice in _voice_runs(unit.chain):
            if any(self._entry_card_ok(unit, s, r) for s, r in _paired(form, reading, voice)):
                return True
        return (widen(form), reading) in self.voice_alternatives(unit)

    def card_ok(self, g: Unit, u: PredictedUnit, fields: Collection[str] = OPTIONAL_FIELDS) -> bool:
        """Whether the tool's unit ``u`` is a card for the gold content unit ``g`` (§7 Card-ready rate).

        The one card-ready test, for strict and lenient scoring alike. ``fields``
        are the ones the tool says it outputs; a field it doesn't declare is not
        read. Only a unit the tool offers as content earns a card. It needs ``g``'s
        span, or the noun's span for a noun + する unit, and an accepted form and
        form_reading that belong together, except where §7 lists other ways to pass.
        """
        if ("kind" in fields and u.kind in FUNCTION_KINDS) or u.start != g.start:
            return False
        if u.end != g.end:
            # Noun + する: the noun alone, 勉強 for 勉強した.
            return u.end == self._noun_end(g) and self._card_pair_ok(g, u.form, u.form_reading)
        has_reading = "reading" in fields
        if not g.entries:
            # No dictionary form to check: the reading in context, whatever the form. A tool
            # that outputs no reading stands in its form_reading where nothing inflects, and
            # the gold form with its form_reading where something does (ググった: ググる, ぐぐる).
            if has_reading:
                return _reads_as(u.reading, g.reading)
            if not g.chain:
                return _reads_as(u.form_reading, g.reading)
            return (
                u.form is not None
                and g.form is not None
                and widen(u.form) == widen(g.form)
                and _reads_as(u.form_reading, g.form_reading)
            )
        if self._counter_form(g):
            if u.form is not None and widen(u.form) == widen(g.surface):
                # The whole surface as form (二十本), read as in context.
                return _reads_as(u.reading if has_reading else u.form_reading, g.reading)
            # The counter as form (本) also needs the sound-changed reading (にじゅっぽん).
            return (
                has_reading
                and _reads_as(u.reading, g.reading)
                and self._card_pair_ok(g, u.form, u.form_reading)
            )
        return self._card_pair_ok(g, u.form, u.form_reading)

    def record_counts(self, record: Record, prediction: Prediction | None, tool: _Tool) -> Counter[str]:
        text = record.text
        c: Counter[str] = Counter()
        gold = list(record.units)
        pred = (
            []
            if prediction is None or prediction.status in FAILED
            else [u for u in prediction.units if not _symbol_only(text, u.start, u.end)]
        )
        gold_spans = {(u.start, u.end) for u in gold}
        gold_function_spans = {(u.start, u.end) for u in gold if u.kind not in CONTENT_KINDS}
        by_span = {(u.start, u.end): u for u in pred}
        content_gold = [u for u in gold if u.kind in CONTENT_KINDS]
        content_pred = [u for u in pred if _is_content(u, tool, gold_function_spans)]
        content_gold_spans = {(u.start, u.end) for u in content_gold}

        # Pieces of accepted splits: inside one gold content unit, cut only at its split points,
        # or at the end of a noun + する unit's noun (勉強|した).
        cuts_of = []
        for g in content_gold:
            cuts = {g.start, g.end, *g.split_points}
            noun_end = self._noun_end(g)
            if noun_end is not None:
                cuts.add(noun_end)
            cuts_of.append((g, cuts))

        def split_piece(u: PredictedUnit) -> bool:
            for g, cuts in cuts_of:
                inside = g.start <= u.start and u.end <= g.end and (u.start, u.end) != (g.start, g.end)
                if inside and u.start in cuts and u.end in cuts:
                    return True
            return False

        def tiles(g: Unit) -> list[PredictedUnit] | None:
            inside = sorted((u for u in pred if g.start <= u.start and u.end <= g.end), key=lambda u: u.start)
            pos = g.start
            for u in inside:
                if u.start != pos:
                    return None
                pos = u.end
            return inside if inside and pos == g.end else None

        # Card-ready (names and interjections with no entry excluded) and accuracy on exact and tiled spans.
        for g in content_gold:
            span = (g.start, g.end)
            exact = by_span.get(span)
            if g.kind != "name" and not _has_no_card(g) and tool.has("form") and tool.has("form_reading"):
                ok = any(self.card_ok(g, u, tool.fields) for u in pred if u.start == g.start)
                c["card.n"] += 1
                c["card.ok"] += ok
                pieces = tiles(g)
                cut_at_splits = (
                    exact is None
                    and pieces is not None
                    and len(pieces) > 1
                    and {u.end for u in pieces[:-1]} <= set(g.split_points)
                )
                # Lenient leaves out a unit cut only at its split points, unless it passes anyway.
                if ok or not cut_at_splits:
                    c["card_lenient.n"] += 1
                    c["card_lenient.ok"] += ok
            if g.kind != "name":
                pieces = tiles(g)
                for field, gold_value in (
                    ("form", g.form),
                    ("reading", g.reading),
                    ("form_reading", g.form_reading),
                ):
                    if not tool.has(field) or gold_value is None:
                        continue
                    c[f"{field}.total"] += 1
                    if exact is not None:
                        c[f"{field}.n"] += 1
                        c[f"{field}.ok"] += self._field_ok(g, field, exact)
                    if pieces is not None:
                        c[f"{field}_tiled.n"] += 1
                        c[f"{field}_tiled.ok"] += self._tiled_ok(g, field, pieces, tool, gold_function_spans)
                    c[f"{field}_tiled.total"] += 1
            if tool.has("entries") and g.entries:
                c["entry.total"] += 1
                if exact is not None and exact.entries:
                    first = exact.entries[0]
                    if not (self.dictionary.exists(first, JMDICT) or self.dictionary.exists(first, JMNEDICT)):
                        c["entry.mismatch"] += 1
                    else:
                        # An id of the other dictionary (a JMdict id for a name) is wrong, not a mismatch.
                        allowed = {*g.entries, *(g.normalized.entries if g.normalized else ())}
                        c["entry.n"] += 1
                        c["entry.ok"] += first in allowed
            if g.normalized is not None and exact is not None and (tool.has("form") or tool.has("entries")):
                c["normalized.n"] += 1
                c["normalized.ok"] += bool(
                    (exact.form is not None and widen(exact.form) in self.normalized_forms(g))
                    or (exact.entries and exact.entries[0] in g.normalized.entries)
                )

        # Junk: content units that are no gold content unit and no piece of an accepted split.
        c["junk.n"] += len(content_pred)
        c["junk.ok"] += sum(
            1 for u in content_pred if (u.start, u.end) not in content_gold_spans and not split_piece(u)
        )

        # Content-unit F1.
        matched = sum(1 for u in content_pred if (u.start, u.end) in content_gold_spans)
        c["content.tp"] += matched
        c["content.pred"] += len(content_pred)
        c["content.gold"] += len(content_gold)

        if tool.partition:
            pred_spans = {(u.start, u.end) for u in pred}
            c["seg.tp"] += len(pred_spans & gold_spans)
            c["seg.pred"] += len(pred_spans)
            c["seg.gold"] += len(gold_spans)
            splits = {p for u in gold for p in u.split_points}
            gold_b = _boundaries(text, gold) - splits
            pred_b = _boundaries(text, pred) - splits
            c["seg_lenient.tp"] += len(gold_b & pred_b)
            c["seg_lenient.pred"] += len(pred_b)
            c["seg_lenient.gold"] += len(gold_b)
        return c

    def _field_ok(self, g: Unit, field: str, u: PredictedUnit) -> bool:
        if field == "form":
            return self.form_ok(g, u.form)
        if field == "form_reading":
            return self.form_reading_ok(g, u.form, u.form_reading)
        return bool(_hira(getattr(u, field)) == getattr(g, field))

    def _tiled_ok(
        self,
        g: Unit,
        field: str,
        pieces: Sequence[PredictedUnit],
        tool: _Tool,
        function_spans: set[tuple[int, int]],
    ) -> bool:
        if field == "reading":
            readings = [_hira(u.reading) for u in pieces]
            return None not in readings and "".join(r for r in readings if r is not None) == g.reading
        first = next((u for u in pieces if _is_content(u, tool, function_spans)), pieces[0])
        return self._field_ok(g, field, first)


def _boundaries(text: str, units: Iterable[PredictedUnit | Unit]) -> set[int]:
    """Inner unit edges, leaving out the text's ends and edges next to a symbol."""
    n = len(text)
    out = set()
    for u in units:
        for i in (u.start, u.end):
            if 0 < i < n and not is_symbol(text[i - 1]) and not is_symbol(text[i]):
                out.add(i)
    return out


def metric_value(counts: Mapping[str, int], metric: str) -> float | None:
    if metric in F1_METRICS:
        tp, pred, gold = (
            counts.get(f"{metric}.tp", 0),
            counts.get(f"{metric}.pred", 0),
            counts.get(f"{metric}.gold", 0),
        )
        if pred + gold == 0:
            return None
        return 2 * tp / (pred + gold)
    n = counts.get(f"{metric}.n", 0)
    return None if n == 0 else counts.get(f"{metric}.ok", 0) / n


def coverage(counts: Mapping[str, int], metric: str) -> float | None:
    total = counts.get(f"{metric}.total", 0)
    return None if total == 0 else counts.get(f"{metric}.n", 0) / total


@dataclass(frozen=True)
class ToolScores:
    """One tool's per-record counters, with the records and predictions they came from."""

    name: str
    description: Description
    records: list[Record]
    predictions: dict[str, Prediction]
    counts: list[Counter[str]]

    def total(self) -> Counter[str]:
        out: Counter[str] = Counter()
        for c in self.counts:
            out.update(c)
        return out

    def value(self, metric: str) -> float | None:
        return metric_value(self.total(), metric)

    def median_ms(self) -> float | None:
        """Over this score's records, so a subset's row times the same records it scores."""
        timed = (self.predictions.get(r.id) for r in self.records)
        ms = [p.ms for p in timed if p is not None and p.ms is not None]
        return statistics.median(ms) if ms else None

    def statuses(self) -> Counter[str]:
        return Counter(
            self.predictions[r.id].status if r.id in self.predictions else "missing" for r in self.records
        )


def score_tool(
    scorer: Scorer,
    name: str,
    description: Description,
    records: Sequence[Record],
    predictions: Iterable[Prediction],
) -> ToolScores:
    texts = {r.id: r.text for r in records}
    by_id = {p.id: against(p, texts.get(p.id)) for p in predictions}
    tool = _Tool(frozenset(description.fields), description.partition)
    counts = [scorer.record_counts(r, by_id.get(r.id), tool) for r in records]
    return ToolScores(name, description, list(records), by_id, counts)


UNIT_METRICS = ("card", "card_lenient", "form", "reading", "form_reading", "form_tiled", "reading_tiled",
                "form_reading_tiled", "entry", "normalized")  # fmt: skip


def category_scores(scorer: Scorer, scores: ToolScores, category: str) -> ToolScores:
    """The same tool scored on the units whose targets name ``category`` (§7 Breakdowns).

    Only unit metrics count here; segmentation and junk are about whole records.
    """
    tool = _Tool(frozenset(scores.description.fields), scores.description.partition)
    records, counts = [], []
    for record in scores.records:
        units = tuple(u for u in record.units if category in u.targets)
        if not units:
            continue
        c = scorer.record_counts(replace(record, units=units), scores.predictions.get(record.id), tool)
        records.append(record)
        counts.append(Counter({k: v for k, v in c.items() if k.split(".")[0] in UNIT_METRICS}))
    return ToolScores(scores.name, scores.description, records, scores.predictions, counts)


def subset(scores: ToolScores, keep: Callable[[Record], bool]) -> ToolScores:
    """The same tool scored on the records ``keep`` accepts (a register or a slice)."""
    pairs = [(r, c) for r, c in zip(scores.records, scores.counts, strict=True) if keep(r)]
    return ToolScores(
        scores.name, scores.description, [r for r, _ in pairs], scores.predictions, [c for _, c in pairs]
    )


@lru_cache(maxsize=4)
def _draws(n: int, samples: int, seed: int) -> tuple[tuple[int, ...], ...]:
    """``samples`` resamples of ``n`` record indices; every tool and metric uses the same ones."""
    rng = random.Random(seed)
    return tuple(tuple(rng.randrange(n) for _ in range(n)) for _ in range(samples))


def _resampled(tool: ToolScores, metric: str, draws: Sequence[Sequence[int]]) -> list[float | None]:
    """The metric on each resample, from one column of per-record counts per counter."""
    parts = ("tp", "pred", "gold") if metric in F1_METRICS else ("ok", "n")
    columns = {f"{metric}.{p}": [c[f"{metric}.{p}"] for c in tool.counts] for p in parts}
    return [
        metric_value({key: sum(map(column.__getitem__, keep)) for key, column in columns.items()}, metric)
        for keep in draws
    ]


def bootstrap(
    tools: Sequence[ToolScores], metric: str, samples: int = BOOTSTRAP_SAMPLES, seed: int = BOOTSTRAP_SEED
) -> dict[str, tuple[float, float]]:
    """95% intervals per tool from one shared resampling of records, so tools are compared paired."""
    if not tools or not tools[0].counts:
        return {}
    draws = _draws(len(tools[0].counts), samples, seed)
    out = {}
    for tool in tools:
        values = sorted(v for v in _resampled(tool, metric, draws) if v is not None)
        if values:
            out[tool.name] = (values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))])
    return out


def paired_difference(
    a: ToolScores, b: ToolScores, metric: str, samples: int = BOOTSTRAP_SAMPLES, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float] | None:
    """95% interval for value(a) - value(b) over the same record resamples."""
    if not a.counts:
        return None
    draws = _draws(len(a.counts), samples, seed)
    pairs = zip(_resampled(a, metric, draws), _resampled(b, metric, draws), strict=True)
    diffs = sorted(va - vb for va, vb in pairs if va is not None and vb is not None)
    if not diffs:
        return None
    return diffs[int(0.025 * (len(diffs) - 1))], diffs[int(0.975 * (len(diffs) - 1))]

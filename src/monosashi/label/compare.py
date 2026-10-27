"""Agreement between two blind labelings, and the queue the owner adjudicates.

Labelings are compared per unit and per field, never per record, so one
disagreement on one particle does not send a whole record to review:

- units with the same span are compared on ``COMPARED_FIELDS`` and on all
  their targets (SPEC.md §6). A unit that differs only in its targets
  queues a ``targets`` item, which a tag agent may settle
  (the tag workflow); any other difference queues a ``field`` item,
  whose fields include ``targets`` when those differ too;
- units whose spans differ are grouped into the smallest region both sides
  cover, which queues one ``boundary`` item;
- an agreed unit that fails validation queues a ``validator`` item, so the
  owner can fix what both labelers got past the validator together; so does
  an advisory (``ADVISORY_RULES``), its note starting ``[advisory]``;
- ``AUDIT_SHARE`` of the fully agreed records, drawn by a hash of their ids, is
  queued whole (``audit``);
- every agreed content unit that fewer than ``quorum`` learner-unit tools
  reproduce is queued (``tools``), with each labeler's unit on its side;
- ``SPOT_COUNT`` of the records no other item touches, drawn by a hash of
  their ids, are queued whole (``spot``), so the owner sees a sample of what
  would otherwise become gold unseen.

``split_points`` are never queued: the merge takes both labelers' (§4.3).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from monosashi.jmdict import Dictionary
from monosashi.predictions import FAILED, Prediction, against
from monosashi.schema import CONTENT_KINDS, Record, Unit, mapping, unit_from_dict, unit_to_dict
from monosashi.validate import advisory_issues, validate_record

COMPARED_FIELDS = ("kind", "entries", "form", "reading", "form_reading", "chain", "normalized")
AUDIT_SHARE = 0.10
SPOT_COUNT = 20
ITEM_TYPES = ("boundary", "field", "targets", "validator", "audit", "spot", "tools")
# Items that need the tool runs: tools items, and spot items, drawn from records no other item touches.
TOOL_DEPENDENT_ITEMS = frozenset({"spot", "tools"})
ADVISORY = "[advisory] "


@dataclass(frozen=True)
class QueueItem:
    record_id: str
    type: str
    start: int
    end: int
    a: tuple[Unit, ...]
    b: tuple[Unit, ...]
    fields: tuple[str, ...] = ()
    note: str = ""

    @property
    def id(self) -> str:
        return f"{self.record_id}:{self.start}-{self.end}:{self.type}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "record": self.record_id,
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "fields": list(self.fields),
            "a": [unit_to_dict(u) for u in self.a],
            "b": [unit_to_dict(u) for u in self.b],
            "note": self.note,
        }


def item_from_dict(data: Mapping[str, Any]) -> QueueItem:
    path = f"queue item {data.get('id', '?')}"
    return QueueItem(
        record_id=str(data["record"]),
        type=str(data["type"]),
        start=int(data["start"]),
        end=int(data["end"]),
        a=tuple(unit_from_dict(mapping(u, path), path) for u in data["a"]),
        b=tuple(unit_from_dict(mapping(u, path), path) for u in data["b"]),
        fields=tuple(str(f) for f in data.get("fields", [])),
        note=str(data.get("note", "")),
    )


def load_queue(path: Path) -> list[QueueItem]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [item_from_dict(json.loads(line)) for line in lines if line.strip()]


def kinds_agree(a: Unit, b: Unit) -> bool:
    """Word vs expression is not a disagreement (both are cards, and JMdict's exp tag is
    the union over senses, so the spec lets either stand), nor is interjection vs
    expression or word on the same first entry, which is then tagged int as well as
    exp or a content part of speech (了解, おおきに; SPEC.md §3)."""
    kinds = {a.kind, b.kind}
    if len(kinds) == 1 or kinds == {"word", "expression"}:
        return True
    same_entry = bool(a.entries) and a.entries[:1] == b.entries[:1]
    return kinds in ({"interjection", "expression"}, {"interjection", "word"}) and same_entry


def field_value(unit: Unit, name: str) -> object:
    """The value two labelers must agree on: entries agree on their first id, targets as a set."""
    if name == "entries":
        return unit.entries[:1]
    if name == "normalized":
        n = unit.normalized
        return None if n is None else (n.form, n.form_reading, n.entries[:1])
    if name == "targets":
        return frozenset(unit.targets)
    return getattr(unit, name)


def differing_fields(a: Unit, b: Unit) -> tuple[str, ...]:
    """The fields of ``COMPARED_FIELDS``, then ``targets``, on which two units of one span disagree."""
    return tuple(
        name
        for name in (*COMPARED_FIELDS, "targets")
        if (not kinds_agree(a, b) if name == "kind" else field_value(a, name) != field_value(b, name))
    )


def _spans(record: Record) -> dict[tuple[int, int], Unit]:
    return {(u.start, u.end): u for u in record.units}


def _regions(units: Sequence[Unit]) -> list[tuple[int, int]]:
    """Merge overlapping spans into regions."""
    regions: list[list[int]] = []
    for u in sorted(units, key=lambda u: u.start):
        if regions and u.start < regions[-1][1]:
            regions[-1][1] = max(regions[-1][1], u.end)
        else:
            regions.append([u.start, u.end])
    return [(a, b) for a, b in regions]


def compare_record(a: Record, b: Record) -> list[QueueItem]:
    """Every disagreement between two labelings of the same sentence."""
    if a.text != b.text:
        raise ValueError(f"{a.id}: the two labelings have different texts")
    sa, sb = _spans(a), _spans(b)
    items = []
    for span in sorted(sa.keys() & sb.keys()):
        ua, ub = sa[span], sb[span]
        differing = differing_fields(ua, ub)
        if differing:
            kind = "targets" if differing == ("targets",) else "field"
            items.append(QueueItem(a.id, kind, *span, (ua,), (ub,), differing))
    only = [sa[s] for s in sa.keys() - sb.keys()] + [sb[s] for s in sb.keys() - sa.keys()]
    for start, end in _regions(only):
        in_a = tuple(u for _, u in sorted(sa.items()) if start <= u.start and u.end <= end)
        in_b = tuple(u for _, u in sorted(sb.items()) if start <= u.start and u.end <= end)
        items.append(QueueItem(a.id, "boundary", start, end, in_a, in_b))
    return sorted(items, key=lambda i: (i.start, i.type))


def rank(record_id: str) -> int:
    return int.from_bytes(hashlib.sha256(record_id.encode("utf-8")).digest()[:8], "big")


def audit_ids(agreed: Iterable[str], share: float = AUDIT_SHARE) -> frozenset[str]:
    """Exactly ``round(share * n)`` of the agreed records: those with the lowest id hashes.

    The draw depends only on the ids, so it is the same however often compare runs.
    """
    ids = sorted(set(agreed), key=rank)
    return frozenset(ids[: round(share * len(ids))])


def tool_items(
    a: Record,
    b: Record,
    tools: Sequence[Mapping[str, Prediction]],
    quorum: int,
    spans: Iterable[tuple[int, int]] | None = None,
) -> list[QueueItem]:
    """Content units on spans both labelings share (all of them, or those on ``spans``) that
    fewer than ``quorum`` learner-unit tools reproduce span for span. Each tool must have a
    prediction for the record. A prediction the scorer counts as failed (garbled, crashed,
    timed out, or made on older text) reproduces nothing."""
    allowed = None if spans is None else set(spans)
    sb = _spans(b)
    scored = (against(predictions[a.id], a.text) for predictions in tools)
    reproduced = [{(u.start, u.end) for u in p.units} for p in scored if p.status not in FAILED]
    items = []
    for unit in a.units:
        span = (unit.start, unit.end)
        if unit.kind not in CONTENT_KINDS or span not in sb or (allowed is not None and span not in allowed):
            continue
        hits = sum(span in spans_of for spans_of in reproduced)
        if hits < quorum:
            note = f"{hits}/{len(tools)} tools"
            items.append(QueueItem(a.id, "tools", *span, (unit,), (sb[span],), note=note))
    return items


def validator_items(
    a: Record, b: Record, dictionary: Dictionary, covered: set[tuple[int, int]]
) -> list[QueueItem]:
    """Units that fail validation, or draw an advisory, on a span no other item covers
    (both labelers agree there). A note lists the failures first, then the advisories,
    each marked ``[advisory]``."""
    spans: dict[tuple[int, int], tuple[list[str], list[str]]] = {}
    for record in (a, b):
        found = [(issue, False) for issue in validate_record(record, dictionary)]
        found += [(issue, True) for issue in advisory_issues(record, dictionary)]
        for issue, advisory in found:
            if issue.unit is None:
                span = (0, len(record.text))
            else:
                u = record.units[issue.unit]
                span = (u.start, u.end)
            if not any(s <= span[0] and span[1] <= e for s, e in covered):
                failures, advisories = spans.setdefault(span, ([], []))
                (advisories if advisory else failures).append(f"[{issue.rule}] {issue.message}")
    sa, sb = _spans(a), _spans(b)
    items = []
    for (start, end), (failures, advisories) in sorted(spans.items()):
        in_a = tuple(u for s, u in sorted(sa.items()) if start <= s[0] and s[1] <= end)
        in_b = tuple(u for s, u in sorted(sb.items()) if start <= s[0] and s[1] <= end)
        note = "; ".join(dict.fromkeys([*failures, *(ADVISORY + n for n in advisories)]))
        items.append(QueueItem(a.id, "validator", start, end, in_a, in_b, note=note))
    return items


def advisory_only(item: QueueItem) -> bool:
    """A validator item raised only by advisories: both labelers agree, and the owner checks."""
    return item.type == "validator" and item.note.startswith(ADVISORY)


@dataclass
class Comparison:
    records: int = 0
    agreed_records: int = 0
    units: int = 0
    agreed_units: int = 0
    items: list[QueueItem] = field(default_factory=list)
    by_field: dict[str, int] = field(default_factory=dict)
    # Per category: shared units whose targets name it on either side, and on both.
    targets_either: Counter[str] = field(default_factory=Counter)
    targets_both: Counter[str] = field(default_factory=Counter)
    tools_flagged: int = 0

    def summary(self) -> dict[str, Any]:
        types: dict[str, int] = {}
        for item in self.items:
            types[item.type] = types.get(item.type, 0) + 1
        return {
            "records": self.records,
            "records_agreed": self.agreed_records,
            "record_agreement": round(self.agreed_records / self.records, 4) if self.records else None,
            "units": self.units,
            "units_agreed": self.agreed_units,
            "unit_agreement": round(self.agreed_units / self.units, 4) if self.units else None,
            "field_disagreements": dict(sorted(self.by_field.items())),
            "target_agreement": {
                c: {
                    "either": n,
                    "both": self.targets_both[c],
                    "agreement": round(self.targets_both[c] / n, 4),
                }
                for c, n in sorted(self.targets_either.items())
            },
            "tools_flagged": self.tools_flagged,
            "queue": types,
        }


def compare(
    a: Iterable[Record],
    b: Iterable[Record],
    tools: Mapping[str, Mapping[str, Prediction]] | None = None,
    quorum: int = 1,
    audit_share: float = AUDIT_SHARE,
    dictionary: Dictionary | None = None,
    spot_count: int = SPOT_COUNT,
) -> Comparison:
    """Compare two labelings record by record (matched by id) and build the queue.

    Unit agreement counts units of the union of both labelings: a unit is agreed
    when both sides have its span and agree on every compared field. With a
    dictionary, agreed units that fail validation or draw an advisory are queued
    as well; an advisory is no disagreement. ``tools`` maps each tool run's name to
    its predictions by record id, and must cover every record.
    """
    records_a = list(a)
    by_id_b = {r.id: r for r in b}
    only_b = sorted(set(by_id_b) - {r.id for r in records_a})
    if only_b:
        raise ValueError(f"labeled by B only: {', '.join(only_b[:5])}")
    tools = tools or {}
    runs = list(tools.values())
    for name, predictions in tools.items():
        missing = [r.id for r in records_a if r.id not in predictions]
        if missing:
            raise ValueError(f"tool run {name} has no prediction for {', '.join(missing[:5])}")
    out = Comparison()
    # Per record: A, B, whether they fully agree, and the spans some item already covers.
    pending: list[tuple[Record, Record, bool, set[tuple[int, int]]]] = []
    for ra in records_a:
        rb = by_id_b.get(ra.id)
        if rb is None:
            raise ValueError(f"{ra.id}: labeled by A only")
        items = compare_record(ra, rb)
        if dictionary is not None:
            items += validator_items(ra, rb, dictionary, {(i.start, i.end) for i in items})
        out.records += 1
        span_union = {(u.start, u.end) for u in (*ra.units, *rb.units)}
        disputes = [i for i in items if not advisory_only(i)]
        disputed = {(u.start, u.end) for i in disputes for u in (*i.a, *i.b)}
        disputed |= {(i.start, i.end) for i in disputes}
        out.units += len(span_union)
        out.agreed_units += len(span_union - disputed)
        sb = _spans(rb)
        for ua in ra.units:
            ub = sb.get((ua.start, ua.end))
            if ub is not None:
                out.targets_either.update(set(ua.targets) | set(ub.targets))
                out.targets_both.update(set(ua.targets) & set(ub.targets))
        for item in disputes:
            for f in item.fields or (item.type,):
                out.by_field[f] = out.by_field.get(f, 0) + 1
        out.items += items
        if not disputes:
            out.agreed_records += 1
        pending.append((ra, rb, not disputes, disputed | {(i.start, i.end) for i in items}))
    audits = audit_ids((r.id for r, _, agreed, _ in pending if agreed), audit_share)
    for ra, rb, _, queued in pending:
        if ra.id in audits:
            out.items.append(QueueItem(ra.id, "audit", 0, len(ra.text), ra.units, rb.units))
        elif runs:
            unqueued = {(u.start, u.end) for u in ra.units} - queued
            flagged = tool_items(ra, rb, runs, quorum, unqueued)
            out.tools_flagged += len(flagged)
            out.items += flagged
    # The spot draw ranks salted ids, so it does not just continue the audit's ranking.
    touched = {i.record_id for i in out.items}
    untouched = sorted(
        ((ra, rb) for ra, rb, _, _ in pending if ra.id not in touched), key=lambda p: rank(f"spot:{p[0].id}")
    )
    for ra, rb in untouched[:spot_count]:
        out.items.append(QueueItem(ra.id, "spot", 0, len(ra.text), ra.units, rb.units))
    out.items.sort(key=lambda i: (i.record_id, i.start, i.type))
    return out


def dump_queue(path: Path, items: Iterable[QueueItem]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            n += 1
    return n

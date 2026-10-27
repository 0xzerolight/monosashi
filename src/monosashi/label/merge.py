"""Gold records from two labelings and the decisions on the queue.

A decision is one JSON line per queue item: ``{"item", "choice", "units"?,
"flag"?, "seconds"?, "by"?}``. ``choice`` is ``a`` or ``b`` (take that
labeler's units for the item), ``ok`` (the agreed units of an audit, spot,
tools or validator item stand), or ``edit`` (``units`` replaces the item's
units). ``by`` names who decided: ``owner`` in ``decisions.jsonl``, which the
review loop writes, and ``tag-agent`` in the ``decisions-tags-NNN.jsonl``
files the tag workflow writes for ``targets`` items. Where both
decided an item, the owner's decision wins.

A record is merged only when every item on it is decided; its status is
``agreed`` with no items, ``audited`` when only an audit or a spot check
touched it, and ``adjudicated`` otherwise.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from monosashi.label.compare import QueueItem, kinds_agree
from monosashi.schema import (
    CONTENT_KINDS,
    Label,
    Record,
    SchemaError,
    Unit,
    mapping,
    unit_from_dict,
    value_of,
)

CHOICES = frozenset({"a", "b", "ok", "edit"})


@dataclass(frozen=True)
class Decision:
    item: str
    choice: str
    units: tuple[Unit, ...] = ()
    flag: str | None = None
    seconds: float | None = None
    by: str | None = None


def decision_from_dict(data: Mapping[str, object]) -> Decision:
    path = f"decision {data.get('item', '?')}"
    choice = value_of(data, "choice", str, path)
    if choice not in CHOICES:
        raise SchemaError(f"{path}: unknown choice {choice!r}")
    units = data.get("units") or []
    if not isinstance(units, list):
        raise SchemaError(f"{path}.units: expected a list")
    seconds = data.get("seconds")
    return Decision(
        item=value_of(data, "item", str, path),
        choice=choice,
        units=tuple(unit_from_dict(mapping(u, f"{path}.units"), f"{path}.units") for u in units),
        flag=value_of(data, "flag", str, path, optional=True),
        seconds=float(seconds)
        if isinstance(seconds, int | float) and not isinstance(seconds, bool)
        else None,
        by=value_of(data, "by", str, path, optional=True),
    )


def load_decisions(path: Path) -> dict[str, Decision]:
    """The last decision per item wins, so a correction is just another line."""
    out: dict[str, Decision] = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    d = decision_from_dict(mapping(json.loads(line), str(path)))
                    out[d.item] = d
    return out


def load_tag_decisions(run_dir: Path) -> dict[str, Decision]:
    """The tag agents' decisions, from every ``decisions-tags-*.jsonl`` in ``run_dir``."""
    out: dict[str, Decision] = {}
    for path in sorted(run_dir.glob("decisions-tags-*.jsonl")):
        out.update(load_decisions(path))
    return out


def load_all_decisions(run_dir: Path) -> dict[str, Decision]:
    """The tag agents' decisions, then the owner's (``decisions.jsonl``), which win."""
    return {**load_tag_decisions(run_dir), **load_decisions(run_dir / "decisions.jsonl")}


def _same_kind(a: Unit, b: Unit) -> bool:
    """Both content units of a kind the labelers agree on (``kinds_agree``)."""
    return a.kind in CONTENT_KINDS and b.kind in CONTENT_KINDS and kinds_agree(a, b)


def _shared(ids: tuple[int, ...], other: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(e for e in ids if e in other)


def merge_units(a: Unit, b: Unit) -> Unit:
    """``a`` merged with ``b``, the other labeler's unit on the same span.

    When both name the same first entry, only the ids both list stay, in
    ``entries`` and in the ``normalized`` entries alike. When both are the same
    kind of content unit, both sides' split points are kept; function units carry
    none (SPEC.md §4.8). Targets are compared like every other field, so
    ``a``'s stand.
    """
    if a.entries[:1] == b.entries[:1]:
        a = replace(a, entries=_shared(a.entries, b.entries))
    na, nb = a.normalized, b.normalized
    if na is not None and nb is not None and na.entries[:1] == nb.entries[:1]:
        a = replace(a, normalized=replace(na, entries=_shared(na.entries, nb.entries)))
    if _same_kind(a, b):
        a = replace(a, split_points=tuple(sorted({*a.split_points, *b.split_points})))
    return a


def _merged_with(units: Sequence[Unit], other: Sequence[Unit]) -> list[Unit]:
    """One side's units, each merged with the other side's unit on the same span."""
    by_span = {(u.start, u.end): u for u in other}
    return [merge_units(u, by_span[(u.start, u.end)]) if (u.start, u.end) in by_span else u for u in units]


# ``ok`` keeps the agreed units of an audit, spot, tools or validator item; a
# field, targets or boundary item has no agreed units, so it needs a, b or an edit.
OK_ITEMS = frozenset({"audit", "spot", "tools", "validator"})
# Whole-record checks: when only these touch a record, it is audited, not adjudicated.
CHECK_ITEMS = frozenset({"audit", "spot"})


def merge_record(
    a: Record, b: Record, items: Sequence[QueueItem], decisions: Mapping[str, Decision]
) -> Record | None:
    """The gold record, or None while an item on it is undecided."""
    if any(i.id not in decisions for i in items):
        return None
    sb = {(u.start, u.end): u for u in b.units}
    units = {
        (u.start, u.end): merge_units(u, sb[(u.start, u.end)]) for u in a.units if (u.start, u.end) in sb
    }
    status = "agreed"
    for item in items:
        d = decisions[item.id]
        if d.choice == "ok" and item.type not in OK_ITEMS:
            raise ValueError(f"{item.id}: a {item.type} item needs a, b or an edit, not ok")
        # A check alone leaves the record audited; any real dispute makes it adjudicated.
        status = (
            "adjudicated" if item.type not in CHECK_ITEMS else ("audited" if status == "agreed" else status)
        )
        if d.choice == "ok":
            continue
        for span in [s for s in units if item.start <= s[0] and s[1] <= item.end]:
            del units[span]
        chosen = {"a": _merged_with(item.a, item.b), "b": _merged_with(item.b, item.a), "edit": list(d.units)}
        for u in chosen[d.choice]:
            units[(u.start, u.end)] = u
    ordered = tuple(units[s] for s in sorted(units))
    for prev, nxt in itertools.pairwise(ordered):
        if nxt.start < prev.end:
            raise ValueError(f"{a.id}: merged units overlap at {nxt.start}")
    return replace(a, units=ordered, label=Label(status=status, spec=a.label.spec))


def merge(
    a: Iterable[Record], b: Iterable[Record], items: Iterable[QueueItem], decisions: Mapping[str, Decision]
) -> tuple[list[Record], list[str]]:
    """Merged records, and the ids still waiting on a decision."""
    by_record: dict[str, list[QueueItem]] = {}
    for item in items:
        by_record.setdefault(item.record_id, []).append(item)
    b_by_id = {r.id: r for r in b}
    merged, waiting = [], []
    for ra in a:
        record = merge_record(ra, b_by_id[ra.id], by_record.get(ra.id, []), decisions)
        if record is None:
            waiting.append(ra.id)
        else:
            merged.append(record)
    return merged, waiting

"""Gold records: the JSONL schema in SPEC.md §Records, as frozen dataclasses.

Parsing only checks shape and types; ``monosashi.validate`` checks meaning
(spans, entries, chains) against the text and the pinned dictionary.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Content units can become flashcards; function units carry no entry ids.
CONTENT_KINDS = frozenset({"word", "expression", "name", "interjection"})
FUNCTION_KINDS = frozenset({"particle", "auxiliary", "copula", "prefix", "suffix"})
UNIT_KINDS = CONTENT_KINDS | FUNCTION_KINDS

REGISTERS = frozenset({"conversation", "literature", "comic", "formal", "game-net"})
SLICES = frozenset({"open", "plain", "seed", "synthetic"})
LABEL_STATUSES = frozenset({"draft", "agreed", "adjudicated", "audited"})


class SchemaError(ValueError):
    """A record that does not have the documented shape."""


@dataclass(frozen=True, slots=True)
class Normalized:
    """The standard word behind a colloquial variant (すげー -> すごい)."""

    form: str
    form_reading: str
    entries: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Unit:
    start: int
    end: int
    surface: str
    kind: str
    entries: tuple[int, ...] = ()
    form: str | None = None
    reading: str | None = None
    form_reading: str | None = None
    chain: tuple[str, ...] = ()
    split_points: tuple[int, ...] = ()
    targets: tuple[str, ...] = ()
    normalized: Normalized | None = None

    @property
    def is_content(self) -> bool:
        return self.kind in CONTENT_KINDS


@dataclass(frozen=True, slots=True)
class Source:
    corpus: str
    ref: str
    license: str
    attribution: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class Label:
    status: str
    spec: str


@dataclass(frozen=True, slots=True)
class Record:
    id: str
    text: str
    source: Source
    register: str
    slice: str
    units: tuple[Unit, ...]
    label: Label

    @property
    def categories(self) -> frozenset[str]:
        return frozenset(t for u in self.units for t in u.targets)


# --- parsing -----------------------------------------------------------------


def value_of(data: Mapping[str, Any], key: str, kind: type, path: str, *, optional: bool = False) -> Any:
    if key not in data or data[key] is None:
        if optional:
            return None
        raise SchemaError(f"{path}.{key}: missing")
    value = data[key]
    # bool is an int subclass; an offset of True is a schema error, not 1.
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise SchemaError(f"{path}.{key}: expected {kind.__name__}, got {type(value).__name__}")
    return value


def tuple_of(data: Mapping[str, Any], key: str, kind: type, path: str) -> tuple[Any, ...]:
    raw = data.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SchemaError(f"{path}.{key}: expected a list")
    for i, item in enumerate(raw):
        if not isinstance(item, kind) or (kind is int and isinstance(item, bool)):
            raise SchemaError(f"{path}.{key}[{i}]: expected {kind.__name__}")
    return tuple(raw)


def mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaError(f"{path}: expected an object")
    return value


_UNIT_KEYS = frozenset(
    {
        "start",
        "end",
        "surface",
        "kind",
        "entries",
        "form",
        "reading",
        "form_reading",
        "chain",
        "split_points",
        "targets",
        "normalized",
    }
)
_RECORD_KEYS = frozenset({"id", "text", "source", "register", "slice", "units", "label"})


def unknown_keys(data: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise SchemaError(f"{path}: unknown field(s) {', '.join(extra)}")


def unit_from_dict(data: Mapping[str, Any], path: str = "unit") -> Unit:
    unknown_keys(data, _UNIT_KEYS, path)
    normalized = None
    if data.get("normalized") is not None:
        raw = mapping(data["normalized"], f"{path}.normalized")
        normalized = Normalized(
            form=value_of(raw, "form", str, f"{path}.normalized"),
            form_reading=value_of(raw, "form_reading", str, f"{path}.normalized"),
            entries=tuple_of(raw, "entries", int, f"{path}.normalized"),
        )
    return Unit(
        start=value_of(data, "start", int, path),
        end=value_of(data, "end", int, path),
        surface=value_of(data, "surface", str, path),
        kind=value_of(data, "kind", str, path),
        entries=tuple_of(data, "entries", int, path),
        form=value_of(data, "form", str, path, optional=True),
        reading=value_of(data, "reading", str, path, optional=True),
        form_reading=value_of(data, "form_reading", str, path, optional=True),
        chain=tuple_of(data, "chain", str, path),
        split_points=tuple_of(data, "split_points", int, path),
        targets=tuple_of(data, "targets", str, path),
        normalized=normalized,
    )


_SOURCE_KEYS = frozenset({"corpus", "ref", "license", "attribution", "url"})


def source_from_dict(data: Mapping[str, Any], path: str = "source") -> Source:
    unknown_keys(data, _SOURCE_KEYS, path)
    return Source(
        corpus=value_of(data, "corpus", str, path),
        ref=value_of(data, "ref", str, path),
        license=value_of(data, "license", str, path),
        attribution=value_of(data, "attribution", str, path),
        url=value_of(data, "url", str, path, optional=True),
    )


def record_from_dict(data: Mapping[str, Any]) -> Record:
    path = f"record {data.get('id', '?')}"
    unknown_keys(data, _RECORD_KEYS, path)
    source = mapping(value_of(data, "source", Mapping, path), f"{path}.source")
    label = mapping(value_of(data, "label", Mapping, path), f"{path}.label")
    units = value_of(data, "units", list, path)
    return Record(
        id=value_of(data, "id", str, path),
        text=value_of(data, "text", str, path),
        source=source_from_dict(source, f"{path}.source"),
        register=value_of(data, "register", str, path),
        slice=value_of(data, "slice", str, path),
        units=tuple(
            unit_from_dict(mapping(u, f"{path}.units[{i}]"), f"{path}.units[{i}]")
            for i, u in enumerate(units)
        ),
        label=Label(
            status=value_of(label, "status", str, f"{path}.label"),
            spec=value_of(label, "spec", str, f"{path}.label"),
        ),
    )


# --- serialization -------------------------------------------------------------


def unit_to_dict(unit: Unit) -> dict[str, Any]:
    out: dict[str, Any] = {"start": unit.start, "end": unit.end, "surface": unit.surface, "kind": unit.kind}
    if unit.entries:
        out["entries"] = list(unit.entries)
    for key in ("form", "reading", "form_reading"):
        value = getattr(unit, key)
        if value is not None:
            out[key] = value
    for key in ("chain", "split_points", "targets"):
        value = getattr(unit, key)
        if value:
            out[key] = list(value)
    if unit.normalized is not None:
        out["normalized"] = {
            "form": unit.normalized.form,
            "form_reading": unit.normalized.form_reading,
            "entries": list(unit.normalized.entries),
        }
    return out


def source_to_dict(source: Source) -> dict[str, Any]:
    out: dict[str, Any] = {
        "corpus": source.corpus,
        "ref": source.ref,
        "license": source.license,
        "attribution": source.attribution,
    }
    if source.url is not None:
        out["url"] = source.url
    return out


def record_to_dict(record: Record) -> dict[str, Any]:
    return {
        "id": record.id,
        "text": record.text,
        "source": source_to_dict(record.source),
        "register": record.register,
        "slice": record.slice,
        "units": [unit_to_dict(u) for u in record.units],
        "label": {"status": record.label.status, "spec": record.label.spec},
    }


def load_records(path: Path) -> Iterator[Record]:
    """Records from a JSONL file; blank lines are skipped."""
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SchemaError(f"{path}:{line_no}: invalid JSON ({exc.msg})") from exc
            try:
                yield record_from_dict(mapping(data, f"{path}:{line_no}"))
            except SchemaError as exc:
                raise SchemaError(f"{path}:{line_no}: {exc}") from exc


def dump_records(path: Path, records: Iterable[Record]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record_to_dict(record), ensure_ascii=False) + "\n")

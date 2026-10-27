"""What a tool says about a sentence: the adapter contract's output, as frozen dataclasses.

Every adapter, whatever it wraps, answers each ``{"id", "text"}`` line with
``{"id", "units": [...], "ms"}``. A unit has ``start``, ``end`` and
``surface`` (code point offsets into the text, end exclusive) and, when the
tool provides them, ``form``, ``reading``, ``form_reading``, ``entries`` and
``kind``. ``--describe`` says which of those fields the tool outputs, and
whether its units cover the whole sentence (a partition) or only content words.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from monosashi.schema import UNIT_KINDS, SchemaError, mapping, tuple_of, unknown_keys, value_of

OPTIONAL_FIELDS = ("form", "reading", "form_reading", "entries", "kind")
# ok: as the tool said. repaired: offsets were re-found from surfaces. garbled:
# the answer, or some of its units, did not fit the text. crash / timeout: no output.
STATUSES = frozenset({"ok", "repaired", "garbled", "crash", "timeout"})
# A record with one of these scores as if the tool had output nothing (SPEC.md §7);
# the units a garbled record kept stay on disk, to read.
FAILED = frozenset({"garbled", "crash", "timeout"})


@dataclass(frozen=True, slots=True)
class PredictedUnit:
    start: int
    end: int
    surface: str
    form: str | None = None
    reading: str | None = None
    form_reading: str | None = None
    entries: tuple[int, ...] = ()
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class Prediction:
    id: str
    units: tuple[PredictedUnit, ...]
    ms: float | None = None
    status: str = "ok"


@dataclass(frozen=True, slots=True)
class Description:
    name: str
    version: str
    dictionary: str
    dictionary_date: str
    partition: bool
    fields: tuple[str, ...]
    commit: str | None = None


_UNIT_KEYS = frozenset({"start", "end", "surface", *OPTIONAL_FIELDS})
_PREDICTION_KEYS = frozenset({"id", "units", "ms", "status"})
_DESCRIPTION_KEYS = frozenset(
    {"name", "version", "dictionary", "dictionary_date", "partition", "fields", "commit"}
)


def fits(text: str, unit: PredictedUnit) -> bool:
    """Whether ``text[start:end] == surface``, with the span inside the text."""
    return 0 <= unit.start < unit.end <= len(text) and text[unit.start : unit.end] == unit.surface


def against(prediction: Prediction, text: str | None) -> Prediction:
    """A prediction whose units do not fit the record's text (a run made on older text) is garbled."""
    if text is None or prediction.status in FAILED or all(fits(text, u) for u in prediction.units):
        return prediction
    return replace(prediction, status="garbled")


def unit_from_dict(data: Mapping[str, Any], path: str = "unit") -> PredictedUnit:
    unknown_keys(data, _UNIT_KEYS, path)
    kind = value_of(data, "kind", str, path, optional=True)
    if kind is not None and kind not in UNIT_KINDS:
        raise SchemaError(f"{path}.kind: unknown kind {kind!r}")
    return PredictedUnit(
        start=value_of(data, "start", int, path),
        end=value_of(data, "end", int, path),
        surface=value_of(data, "surface", str, path),
        form=value_of(data, "form", str, path, optional=True),
        reading=value_of(data, "reading", str, path, optional=True),
        form_reading=value_of(data, "form_reading", str, path, optional=True),
        entries=tuple_of(data, "entries", int, path),
        kind=kind,
    )


def unit_to_dict(unit: PredictedUnit) -> dict[str, Any]:
    out: dict[str, Any] = {"start": unit.start, "end": unit.end, "surface": unit.surface}
    for key in ("form", "reading", "form_reading", "kind"):
        value = getattr(unit, key)
        if value is not None:
            out[key] = value
    if unit.entries:
        out["entries"] = list(unit.entries)
    return out


def prediction_from_dict(data: Mapping[str, Any]) -> Prediction:
    path = f"prediction {data.get('id', '?')}"
    unknown_keys(data, _PREDICTION_KEYS, path)
    units = value_of(data, "units", list, path)
    ms = data.get("ms")
    if ms is not None and (isinstance(ms, bool) or not isinstance(ms, int | float)):
        raise SchemaError(f"{path}.ms: expected a number")
    status = data.get("status", "ok")
    if status not in STATUSES:
        raise SchemaError(f"{path}.status: unknown status {status!r}")
    return Prediction(
        id=value_of(data, "id", str, path),
        units=tuple(
            unit_from_dict(mapping(u, f"{path}.units[{i}]"), f"{path}.units[{i}]")
            for i, u in enumerate(units)
        ),
        ms=None if ms is None else float(ms),
        status=status,
    )


def prediction_to_dict(prediction: Prediction) -> dict[str, Any]:
    out: dict[str, Any] = {"id": prediction.id, "units": [unit_to_dict(u) for u in prediction.units]}
    if prediction.ms is not None:
        out["ms"] = round(prediction.ms, 3)
    if prediction.status != "ok":
        out["status"] = prediction.status
    return out


def description_from_dict(data: Mapping[str, Any]) -> Description:
    path = "description"
    unknown_keys(data, _DESCRIPTION_KEYS, path)
    fields = tuple_of(data, "fields", str, path)
    bad = sorted(set(fields) - set(OPTIONAL_FIELDS))
    if bad:
        raise SchemaError(f"{path}.fields: unknown field(s) {', '.join(bad)}")
    return Description(
        name=value_of(data, "name", str, path),
        version=value_of(data, "version", str, path),
        dictionary=value_of(data, "dictionary", str, path),
        dictionary_date=value_of(data, "dictionary_date", str, path),
        partition=value_of(data, "partition", bool, path),
        fields=fields,
        commit=value_of(data, "commit", str, path, optional=True),
    )


def description_to_dict(d: Description) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": d.name,
        "version": d.version,
        "dictionary": d.dictionary,
        "dictionary_date": d.dictionary_date,
        "partition": d.partition,
        "fields": list(d.fields),
    }
    if d.commit is not None:
        out["commit"] = d.commit
    return out


def load_predictions(path: Path) -> Iterator[Prediction]:
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if line.strip():
                try:
                    yield prediction_from_dict(mapping(json.loads(line), f"{path}:{line_no}"))
                except (json.JSONDecodeError, SchemaError) as exc:
                    raise SchemaError(f"{path}:{line_no}: {exc}") from exc


def dump_predictions(path: Path, predictions: Iterable[Prediction]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for p in predictions:
            fh.write(json.dumps(prediction_to_dict(p), ensure_ascii=False) + "\n")

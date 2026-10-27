"""The adapter contract's output schema."""

from __future__ import annotations

from pathlib import Path

import pytest

from monosashi.adapters.protocol import spans_in_order, to_hiragana
from monosashi.predictions import (
    PredictedUnit,
    Prediction,
    description_from_dict,
    dump_predictions,
    load_predictions,
    prediction_from_dict,
)
from monosashi.schema import SchemaError


def test_predictions_round_trip(tmp_path: Path) -> None:
    p = Prediction(
        "a", (PredictedUnit(0, 2, "食べ", "食べる", "たべ", "たべる", (1358280,), "word"),), 1.5, "repaired"
    )
    dump_predictions(tmp_path / "p.jsonl", [p])
    assert list(load_predictions(tmp_path / "p.jsonl")) == [p]


@pytest.mark.parametrize(
    "data",
    [
        {"id": "a", "units": [], "status": "lost"},
        {"id": "a", "units": [{"start": 0, "end": 1, "surface": "a", "lemma": "a"}]},
        {"id": "a", "units": [], "ms": True},
        {"id": "a", "units": [{"start": 0, "end": 1, "surface": "a", "kind": "noun"}]},
    ],
)
def test_bad_predictions_are_rejected(data: dict[str, object]) -> None:
    with pytest.raises(SchemaError):
        prediction_from_dict(data)


def test_description_rejects_unknown_fields() -> None:
    base = {"name": "x", "version": "1", "dictionary": "d", "dictionary_date": "2026", "partition": True}
    assert description_from_dict(base | {"fields": ["form"]}).fields == ("form",)
    with pytest.raises(SchemaError):
        description_from_dict(base | {"fields": ["pitch"]})


def test_protocol_helpers() -> None:
    assert spans_in_order("ははは", ["は", "は", "x", "は"]) == [(0, 1), (1, 2), None, (2, 3)]
    assert to_hiragana("タベル・ー") == "たべる・ー"

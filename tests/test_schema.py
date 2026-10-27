from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import hajimete_shimatta
from monosashi.schema import SchemaError, dump_records, load_records, record_from_dict, record_to_dict


def test_round_trip_is_lossless(tmp_path: Path) -> None:
    data = hajimete_shimatta()
    rec = record_from_dict(data)
    assert record_to_dict(rec) == data
    path = tmp_path / "r.jsonl"
    dump_records(path, [rec])
    assert list(load_records(path)) == [rec]
    assert rec.categories == {"compound", "inflection-chain", "te-auxiliary"}


def test_unknown_fields_are_rejected() -> None:
    data = hajimete_shimatta()
    data["units"][0]["lemma"] = "彼女"
    with pytest.raises(SchemaError, match="unknown field"):
        record_from_dict(data)


def test_wrong_types_are_rejected() -> None:
    data = hajimete_shimatta()
    data["units"][0]["start"] = True
    with pytest.raises(SchemaError, match="expected int"):
        record_from_dict(data)
    data = hajimete_shimatta()
    data["units"][0]["entries"] = ["1483150"]
    with pytest.raises(SchemaError, match=r"entries\[0\]"):
        record_from_dict(data)


def test_load_reports_the_line(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(hajimete_shimatta(), ensure_ascii=False) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(SchemaError, match=r"bad\.jsonl:2"):
        list(load_records(path))

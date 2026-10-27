"""Record builders shared by the tests."""

from __future__ import annotations

from typing import Any

from monosashi import SPEC_VERSION


def record(text: str, units: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    """A gold record dict with valid record-level fields, for tests to break one at a time."""
    data: dict[str, Any] = {
        "id": "t-1",
        "text": text,
        "source": {"corpus": "test", "ref": "1", "license": "CC-BY-SA-4.0", "attribution": "monosashi tests"},
        "register": "conversation",
        "slice": "synthetic",
        "units": units,
        "label": {"status": "draft", "spec": SPEC_VERSION},
    }
    data.update(overrides)
    return data


def hajimete_shimatta() -> dict[str, Any]:
    """彼女は一人暮らしを始めてしまった。 labeled correctly."""
    return record(
        "彼女は一人暮らしを始めてしまった。",
        [
            {"start": 0, "end": 2, "surface": "彼女", "kind": "word", "entries": [1483150], "form": "彼女",
             "reading": "かのじょ", "form_reading": "かのじょ"},
            {"start": 2, "end": 3, "surface": "は", "kind": "particle"},
            {"start": 3, "end": 8, "surface": "一人暮らし", "kind": "word", "entries": [1613340],
             "form": "一人暮らし", "reading": "ひとりぐらし", "form_reading": "ひとりぐらし",
             "split_points": [5], "targets": ["compound"]},
            {"start": 8, "end": 9, "surface": "を", "kind": "particle"},
            {"start": 9, "end": 16, "surface": "始めてしまった", "kind": "word", "entries": [1307550],
             "form": "始める", "reading": "はじめてしまった", "form_reading": "はじめる",
             "chain": ["-て", "-しまう", "-た"], "targets": ["inflection-chain", "te-auxiliary"]},
        ],
    )  # fmt: skip


def sugee() -> dict[str, Any]:
    """すげー！ with its own entry plus the normalized standard word."""
    return record(
        "すげー！",
        [
            {"start": 0, "end": 3, "surface": "すげー", "kind": "interjection", "entries": [2722660], "form": "すげー",
             "reading": "すげー", "form_reading": "すげー", "targets": ["colloquial-variant"],
             "normalized": {"form": "すごい", "form_reading": "すごい", "entries": [1374550]}},
        ],
        id="t-2",
    )  # fmt: skip


def benkyou_shiteiru() -> dict[str, Any]:
    """勉強している: noun + する, mapped to the noun's entry."""
    return record(
        "勉強している",
        [
            {"start": 0, "end": 6, "surface": "勉強している", "kind": "word", "entries": [1512670],
             "form": "勉強", "reading": "べんきょうしている", "form_reading": "べんきょう",
             "chain": ["-て", "-いる"], "targets": ["suru-verb", "te-auxiliary"]},
        ],
        id="t-3",
    )  # fmt: skip


def tanaka_san() -> dict[str, Any]:
    """田中さん: a JMnedict name and a function suffix."""
    return record(
        "田中さん",
        [
            {
                "start": 0,
                "end": 2,
                "surface": "田中",
                "kind": "name",
                "entries": [5543705],
                "targets": ["name"],
            },
            {"start": 2, "end": 4, "surface": "さん", "kind": "suffix"},
        ],
        id="t-4",
    )

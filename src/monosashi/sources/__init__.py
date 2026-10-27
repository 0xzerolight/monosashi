"""Unlabeled sentences, and the pinned corpora they come from.

A ``Sentence`` is what selection works with before labeling: normalized text,
its source and license, its register and slice, and, once tagged, the category
hints the tagger found. A sentence carries its attribution from the moment it
is read, so anything committed traces back to its source. Raw downloads stay in
the cache; only selected sentences are committed.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from monosashi.jmdict import repo_root
from monosashi.kana import is_normalized
from monosashi.licenses import ALLOWED_SOURCE_LICENSES
from monosashi.schema import (
    REGISTERS,
    SLICES,
    SchemaError,
    Source,
    mapping,
    source_from_dict,
    source_to_dict,
    unknown_keys,
    value_of,
)
from monosashi.taxonomy import CATEGORIES


@dataclass(frozen=True, slots=True)
class SourcePin:
    """One pinned download in ``data/sources.toml``; ``extra`` holds the group's own fields."""

    key: str
    url: str
    sha256: str
    license: str
    attribution: str
    version: str
    extra: Mapping[str, str]


def load_source_pins(group: str, path: Path | None = None) -> dict[str, SourcePin]:
    source = path or repo_root() / "data" / "sources.toml"
    with source.open("rb") as fh:
        data = tomllib.load(fh)
    common = {"url", "sha256", "license", "attribution", "version"}
    return {
        key: SourcePin(
            key=key,
            url=str(raw["url"]),
            sha256=str(raw["sha256"]),
            license=str(raw["license"]),
            attribution=str(raw["attribution"]),
            version=str(raw["version"]),
            extra={k: str(v) for k, v in raw.items() if k not in common},
        )
        for key, raw in data.get(group, {}).items()
    }


@dataclass(frozen=True, slots=True)
class Hint:
    """A category the tagger found, on the span of text that carries it."""

    category: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Sentence:
    id: str
    text: str
    source: Source
    register: str
    slice: str
    # A seed's own expected output (its test's split or card fronts), kept verbatim.
    original: Mapping[str, Any] | None = None
    hints: tuple[Hint, ...] = ()

    @property
    def categories(self) -> frozenset[str]:
        return frozenset(h.category for h in self.hints)


_SENTENCE_KEYS = frozenset({"id", "text", "source", "register", "slice", "original", "hints"})
_HINT_KEYS = frozenset({"category", "start", "end"})


def sentence_from_dict(data: Mapping[str, Any]) -> Sentence:
    path = f"sentence {data.get('id', '?')}"
    unknown_keys(data, _SENTENCE_KEYS, path)
    original = data.get("original")
    raw_hints = data.get("hints") or []
    if not isinstance(raw_hints, list):
        raise SchemaError(f"{path}.hints: expected a list")
    hints = []
    for i, raw in enumerate(raw_hints):
        hint = mapping(raw, f"{path}.hints[{i}]")
        unknown_keys(hint, _HINT_KEYS, f"{path}.hints[{i}]")
        hints.append(
            Hint(
                category=value_of(hint, "category", str, f"{path}.hints[{i}]"),
                start=value_of(hint, "start", int, f"{path}.hints[{i}]"),
                end=value_of(hint, "end", int, f"{path}.hints[{i}]"),
            )
        )
    return Sentence(
        id=value_of(data, "id", str, path),
        text=value_of(data, "text", str, path),
        source=source_from_dict(mapping(value_of(data, "source", Mapping, path), f"{path}.source")),
        register=value_of(data, "register", str, path),
        slice=value_of(data, "slice", str, path),
        original=None if original is None else mapping(original, f"{path}.original"),
        hints=tuple(hints),
    )


def sentence_to_dict(sentence: Sentence) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": sentence.id,
        "text": sentence.text,
        "source": source_to_dict(sentence.source),
        "register": sentence.register,
        "slice": sentence.slice,
    }
    if sentence.original is not None:
        out["original"] = dict(sentence.original)
    if sentence.hints:
        out["hints"] = [{"category": h.category, "start": h.start, "end": h.end} for h in sentence.hints]
    return out


def load_sentences(path: Path) -> Iterator[Sentence]:
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                yield sentence_from_dict(mapping(json.loads(line), f"{path}:{line_no}"))
            except (json.JSONDecodeError, SchemaError) as exc:
                raise SchemaError(f"{path}:{line_no}: {exc}") from exc


def dump_sentences(path: Path, sentences: Iterable[Sentence]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for sentence in sentences:
            fh.write(json.dumps(sentence_to_dict(sentence), ensure_ascii=False) + "\n")
            count += 1
    return count


def sentence_problems(sentence: Sentence) -> list[str]:
    """What is wrong with a sentence before it may be committed (empty when nothing is)."""
    problems = []
    if not sentence.text:
        problems.append("empty text")
    elif not is_normalized(sentence.text):
        problems.append("text is not normalized")
    if sentence.register not in REGISTERS:
        problems.append(f"unknown register {sentence.register!r}")
    if sentence.slice not in SLICES:
        problems.append(f"unknown slice {sentence.slice!r}")
    if sentence.source.license not in ALLOWED_SOURCE_LICENSES:
        problems.append(f"license {sentence.source.license!r} is not on the allowlist")
    for hint in sentence.hints:
        if hint.category not in CATEGORIES:
            problems.append(f"unknown category {hint.category!r}")
        if not 0 <= hint.start < hint.end <= len(sentence.text):
            problems.append(f"hint {hint.category} [{hint.start}:{hint.end}] is out of bounds")
    return problems

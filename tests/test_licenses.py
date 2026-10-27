"""License audit over the committed data (SPEC.md §8, rule `license`)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from monosashi.jmdict import repo_root
from monosashi.licenses import ALLOWED_SOURCE_LICENSES
from monosashi.schema import load_records
from monosashi.sources import load_sentences, sentence_problems

DATA = repo_root() / "data"
# Labeled records live in data/core and data/labels, and seed records without their text in
# data/seed-labels; every other data file holds sentences.
RECORD_DIRS = ("core", "labels", "seed-labels")


def _jsonl_files(*dirs: str) -> list[Path]:
    return sorted(p for d in dirs for p in (DATA / d).rglob("*.jsonl"))


def _sentence_files() -> list[Path]:
    return sorted(
        p
        for p in DATA.rglob("*.jsonl")
        if "private" not in p.parts and p.relative_to(DATA).parts[0] not in RECORD_DIRS
    )


def _record_files() -> list[Path]:
    """Gold records, and each labeler's records in a labeling run (its queue and decisions are not records)."""
    return _jsonl_files("core") + sorted((DATA / "labels").glob("*/labels-*/*.jsonl"))


def test_every_committed_record_has_an_allowed_license() -> None:
    bad = [
        f"{path.relative_to(DATA)}: {rec.id} ({rec.source.license})"
        for path in _record_files()
        for rec in load_records(path)
        if rec.source.license not in ALLOWED_SOURCE_LICENSES
    ]
    assert bad == []


def test_every_seed_label_has_an_allowed_license() -> None:
    bad = [
        f"{path.relative_to(DATA)}: {row['id']} ({row['source']['license']})"
        for path in _jsonl_files("seed-labels")
        for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())
        if row["source"]["license"] not in ALLOWED_SOURCE_LICENSES
    ]
    assert bad == []


@pytest.mark.parametrize("path", _sentence_files(), ids=lambda p: str(p.relative_to(DATA)))
def test_every_committed_sentence_is_clean(path: Path) -> None:
    bad = [(s.id, p) for s in load_sentences(path) for p in sentence_problems(s)]
    assert bad == []


def test_committed_sentence_ids_are_unique() -> None:
    ids = [s.id for d in ("seeds", "synthetic") for path in _jsonl_files(d) for s in load_sentences(path)]
    assert len(ids) == len(set(ids))


def test_every_pinned_source_has_a_sha256_and_license() -> None:
    with (DATA / "sources.toml").open("rb") as fh:
        sources = tomllib.load(fh)
    for group in sources.values():
        for key, source in group.items():
            assert len(source.get("sha256", "")) == 64, key
            assert source.get("license"), key

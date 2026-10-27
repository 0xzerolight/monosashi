"""Every worked example in SPEC.md is a record here, and it must stay valid."""

from __future__ import annotations

import re
from pathlib import Path

from monosashi.jmdict import Dictionary, repo_root
from monosashi.schema import load_records
from monosashi.taxonomy import CATEGORIES
from monosashi.validate import validate_files

EXAMPLES = Path(__file__).parent / "fixtures" / "spec-examples.jsonl"


def _spec() -> str:
    return (repo_root() / "SPEC.md").read_text(encoding="utf-8")


def test_spec_examples_validate(dictionary: Dictionary) -> None:
    issues = validate_files([EXAMPLES], dictionary)
    assert issues == [], [str(i) for i in issues]


def test_spec_md_shows_every_example() -> None:
    spec = _spec()
    missing = [r.id for r in load_records(EXAMPLES) if r.id not in spec]
    assert missing == []


def test_spec_defines_every_category() -> None:
    """SPEC §6 has one definition line per category, word for word as in taxonomy.py, and no others."""
    spec = _spec()
    section = spec[spec.index("\n## 6. ") : spec.index("\n## 7. ")]
    lines = re.findall(r"^- `([^`]+)`: (.+)$", section, flags=re.MULTILINE)
    assert [key for key, _ in lines] == list(CATEGORIES)
    assert dict(lines) == CATEGORIES

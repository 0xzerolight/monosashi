"""Seed sentences from three test suites, with each suite's own expected output.

Seeds are the hard cases other tools were built against: ichiran's segmentation
assertions (MIT), Jiten's segmentation cases (Apache-2.0, partly ported from
ichiran), and anki_miner's parse corpus. Each seed keeps its suite's expected
output in ``original`` for reference only; it is relabeled to SPEC.md like
every other sentence, and labelers never see ``original``.

``scripts/import_seeds.py`` runs these parsers into ``data/seeds/``, which is not
committed: the seeds quote song lyrics and novels. Their gold records are published
without that text (``without_text``) and get it back from ``data/seeds/`` (``with_text``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from monosashi.kana import normalize_text
from monosashi.schema import Record, Source, record_from_dict, record_to_dict
from monosashi.sources import Sentence


@dataclass(frozen=True, slots=True)
class Case:
    line: int
    text: str
    original: dict[str, object]


# --- ichiran: (assert-segment "text" "piece" … :gap) in tests.lisp ---------------------

_LISP_TOKEN = re.compile(r'\s+|;[^\n]*|"((?:[^"\\]|\\.)*)"|(:[\w-]+)|(\))|([^\s()";]+)')


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def parse_ichiran(source: str) -> Iterator[Case]:
    """Every literal ``assert-segment`` call. A call built from variables is skipped."""
    for match in re.finditer(r"\(assert-segment\b", source):
        pos = match.end()
        args: list[str | None] = []
        literal = True
        while pos < len(source):
            token = _LISP_TOKEN.match(source, pos)
            if token is None:
                literal = False
                break
            pos = token.end()
            string, keyword, close, symbol = token.groups()
            if close:
                break
            if string is not None:
                args.append(_unescape(string))
            elif keyword is not None:
                args.append(None if keyword == ":gap" else keyword)
            elif symbol is not None:
                literal = False
        text = args[0] if args else None
        if not literal or not isinstance(text, str):
            continue
        line = source.count("\n", 0, match.start()) + 1
        yield Case(line, text, {"split": args[1:]})


# --- Jiten: yield return ["text", new[] { "piece", … }]; in SegmentationCases() ----------

_CS_CASE = re.compile(
    r'yield return\s*\[\s*"((?:[^"\\]|\\.)*)"\s*,\s*new(?:\s*string)?\[\]\s*\{(.*?)\}\s*\]\s*;', re.S
)
_CS_LIVE = re.compile(r"\byield return\b")
_CS_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}
_CS_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)")
_CS_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
# A commented-out case above a live one is not its note.
_COMMENTED_CODE = ("yield return", "[", "]", '"', "new[]")


def _cs_unescape(s: str) -> str:
    """A C# string literal's text: \\n is a newline, \\u3042 is あ, \\" is a quote."""

    def one(m: re.Match[str]) -> str:
        code = m.group(1)
        return chr(int(code[1:], 16)) if code.startswith("u") else _CS_ESCAPES.get(code, code)

    return _CS_ESCAPE.sub(one, s)


def _strip_cs_comments(source: str) -> tuple[str, dict[int, str]]:
    """The source with // comments blanked (newlines kept), and each comment by line number."""
    out_lines, comments = [], {}
    for n, line in enumerate(source.split("\n"), 1):
        in_string, cut = False, None
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                in_string = not in_string
            elif not in_string and line.startswith("//", i):
                cut = i
                break
        if cut is None:
            out_lines.append(line)
        else:
            out_lines.append(line[:cut])
            comments[n] = line[cut + 2 :].strip()
    return "\n".join(out_lines), comments


def parse_jiten(source: str) -> Iterator[Case]:
    """Every live segmentation case; commented-out cases are skipped.

    A case's note is the run of comment lines directly above it.
    """
    stripped, comments = _strip_cs_comments(source)
    lines = stripped.split("\n")
    cases = list(_CS_CASE.finditer(stripped))
    live = len(_CS_LIVE.findall(stripped))
    if len(cases) != live:
        raise ValueError(f"Jiten tests: parsed {len(cases)} cases, but {live} yield returns are live")
    for match in cases:
        line = stripped.count("\n", 0, match.start()) + 1
        note_lines: list[str] = []
        above = line - 1
        while above in comments and not lines[above - 1].strip():
            if not comments[above].startswith(_COMMENTED_CODE):
                note_lines.insert(0, comments[above])
            above -= 1
        original: dict[str, object] = {"split": [_cs_unescape(s) for s in _CS_STRING.findall(match.group(2))]}
        if note_lines:
            original["note"] = " ".join(note_lines)
        yield Case(line, _cs_unescape(match.group(1)), original)


# --- anki_miner: parse-corpus JSONL rows -------------------------------------------------


def parse_anki_miner(source: str) -> Iterator[Case]:
    for n, line in enumerate(source.splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        original = {k: v for k, v in row.items() if k != "sentence"}
        yield Case(n, str(row["sentence"]), original)


# --- shared --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Suite:
    corpus: str
    license: str
    register: str
    attribution: str


SUITES = {
    "ichiran": Suite("ichiran", "MIT", "comic", "ichiran test suite (Timofei Shatrov)"),
    "jiten": Suite("jiten", "Apache-2.0", "game-net", "Jiten test suite (Sirush)"),
    "anki_miner": Suite(
        "anki_miner", "CC-BY-SA-4.0", "conversation", "anki_miner parse corpus (0xzerolight)"
    ),
}


def to_sentences(
    suite: Suite, cases: Iterator[Case], *, path: str, version: str, url: str, id_of: str = "line"
) -> Iterator[Sentence]:
    """Seed sentences for one suite file.

    A seed's id is its source line (ichiran-0040), so fixing the parser never
    renumbers other seeds; ``id_of="row-id"`` keys anki_miner seeds by their own ids.
    """
    for case in cases:
        own_id = case.original.get("id") if id_of == "row-id" else None
        sid = f"{suite.corpus}-{own_id}" if own_id else f"{suite.corpus}-{case.line:04d}"
        yield Sentence(
            id=sid,
            text=normalize_text(case.text),
            source=Source(
                corpus=suite.corpus,
                ref=f"{path}:{case.line}",
                license=suite.license,
                attribution=f"{suite.attribution}, {path} at {version[:12]}",
                url=f"{url}#L{case.line}",
            ),
            register=suite.register,
            slice="seed",
            original=case.original,
        )


# --- seed gold records without their text --------------------------------------------


def without_text(record: Record) -> dict[str, Any]:
    """A seed gold record as published: no text, and no unit surfaces, which quote it."""
    out = record_to_dict(record)
    del out["text"]
    for unit in out["units"]:
        del unit["surface"]
    return out


def with_text(data: Mapping[str, Any], text: str) -> Record:
    """The gold record that ``without_text`` stripped, given its seed sentence's text."""
    units = [{**u, "surface": text[u["start"] : u["end"]]} for u in data["units"]]
    return record_from_dict({**data, "text": text, "units": units})

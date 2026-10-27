"""Aozora Bunko: public-domain literature, new-orthography (新字新仮名) editions only.

Each work is pinned in ``data/sources.toml`` under ``[aozora.*]`` by its zip and
sha256. A work's text is Shift_JIS with Aozora's own markup: ruby (｜漢字《かんじ》),
editor notes (［＃…］) and references to characters outside JIS (※［＃…］). Ruby
readings and notes are dropped. A paragraph that still holds a ※ is skipped,
since the character it stood for is lost.

A line of dialogue (a 「…」 that opens the paragraph or follows the end of a
sentence) is one sentence. Narration is split after 。！？ outside brackets, and
a quoted term inside it (所謂「神憑り」で) stays where it is. A narration
fragment that starts with a quotative particle right after dialogue
(「…」と老爺は答えた) and any piece with unbalanced brackets are dropped.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

from monosashi.jmdict import cache_dir, fetch
from monosashi.kana import normalize_text
from monosashi.schema import Source
from monosashi.sources import Sentence, SourcePin, load_source_pins

LICENSE = "public-domain"

_RUBY = re.compile(r"《[^》]*》")
_NOTE = re.compile(r"［＃[^］]*］")
_RULE = re.compile(r"^-{20,}$")
_BRACKETS = {"「": "」", "『": "』", "（": "）", "(": ")"}
_ENDS = "。！？"
_QUOTATIVE = ("と", "って", "とか")


def body_lines(raw: str) -> Iterator[tuple[int, str]]:
    """(line number, text) for the body: after the notation block, before the colophon (底本：)."""
    lines = raw.splitlines()
    rules = [i for i, line in enumerate(lines) if _RULE.match(line.strip())]
    # The notation block between the first two rules is optional.
    start = rules[1] + 1 if len(rules) >= 2 else 0
    for i in range(start, len(lines)):
        line = lines[i]
        if line.startswith("底本："):
            return
        yield i + 1, line


def clean(line: str) -> str | None:
    """A paragraph without ruby or editor notes, or None when it holds a lost character."""
    text = _NOTE.sub("", _RUBY.sub("", line)).replace("｜", "")
    if "※" in text:
        return None
    return text.strip().lstrip("　")


def _balanced(text: str) -> bool:
    return all(text.count(o) == text.count(c) for o, c in _BRACKETS.items())


def split_paragraph(text: str) -> list[str]:
    """The paragraph's sentences: dialogue lines and narration sentences, in order."""
    pieces: list[str] = []
    narration = ""
    after_dialogue = False
    depth = 0
    i = 0

    def flush() -> None:
        nonlocal narration, after_dialogue
        piece = narration.strip()
        if piece and not (after_dialogue and piece.startswith(_QUOTATIVE)):
            pieces.append(piece)
        if piece:
            after_dialogue = False
        narration = ""

    while i < len(text):
        ch = text[i]
        opens_sentence = not narration.strip()
        if ch == "「" and depth == 0 and opens_sentence:
            close = _closing(text, i)
            if close is None:
                narration += text[i:]
                break
            pieces.append(text[i + 1 : close].strip())
            after_dialogue = True
            i = close + 1
            continue
        narration += ch
        if ch in _BRACKETS:
            depth += 1
        elif ch in _BRACKETS.values():
            depth = max(0, depth - 1)
        elif ch in _ENDS and depth == 0:
            flush()
        i += 1
    flush()
    return [p for p in pieces if p and _balanced(p)]


def _closing(text: str, start: int) -> int | None:
    """Index of the 」 that closes the 「 at ``start``, counting nested quotes."""
    depth = 0
    for j in range(start, len(text)):
        if text[j] == "「":
            depth += 1
        elif text[j] == "」":
            depth -= 1
            if depth == 0:
                return j
    return None


def read_work(archive: Path, pin: SourcePin) -> Iterator[Sentence]:
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n.endswith(".txt")]
        if len(names) != 1:
            raise ValueError(f"{archive.name}: expected one .txt member, found {len(names)}")
        raw = zf.read(names[0]).decode("cp932", errors="replace")
    card = pin.extra["card"]
    attribution = pin.attribution
    for line_no, line in body_lines(raw):
        text = clean(line)
        if not text or "�" in text:
            continue
        for k, piece in enumerate(split_paragraph(text)):
            yield Sentence(
                id=f"aoz-{card}-{line_no}-{k}",
                text=normalize_text(piece),
                source=Source(
                    corpus="aozora",
                    ref=f"{card}:{line_no}:{k}",
                    license=LICENSE,
                    attribution=attribution,
                    url=pin.extra["card_url"],
                ),
                register="literature",
                slice="open",
            )


def sentences(cache: Path | None = None) -> Iterator[Sentence]:
    cache = cache or cache_dir()
    for pin in load_source_pins("aozora").values():
        yield from read_work(fetch(pin, cache), pin)

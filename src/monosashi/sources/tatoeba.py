"""Tatoeba: everyday conversational sentences, CC BY 2.0 FR.

Only sentences whose owner declares native Japanese (skill level 5) are kept:
much of the Japanese side came in through the Tanaka Corpus import, and an
unowned or learner-owned sentence is more likely to be unnatural.
"""

from __future__ import annotations

import bz2
import io
import tarfile
from collections.abc import Iterator
from pathlib import Path

from monosashi.jmdict import cache_dir, fetch
from monosashi.kana import normalize_text
from monosashi.schema import Source
from monosashi.sources import Sentence, SourcePin, load_source_pins

SENTENCES = "tatoeba-sentences"
USER_LANGUAGES = "tatoeba-user-languages"
NATIVE_LEVEL = "5"
LICENSE = "CC-BY-2.0-FR"


def native_speakers(archive: Path, lang: str = "jpn") -> frozenset[str]:
    """Owners who declare ``lang`` at native level, from the user_languages export.

    The CSV is streamed out of the archive by its basename, never extracted.
    """
    with tarfile.open(archive, "r:bz2") as tar:
        member = next(m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "user_languages.csv")
        stream = tar.extractfile(member)
        if stream is None:
            raise ValueError(f"{archive.name}: cannot read {member.name}")
        natives = set()
        for line in io.TextIOWrapper(stream, encoding="utf-8"):
            # lang, skill level, username, details
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 3 and fields[0] == lang and fields[1] == NATIVE_LEVEL:
                natives.add(fields[2])
    return frozenset(natives)


def read_sentences(archive: Path, natives: frozenset[str], pin: SourcePin) -> Iterator[Sentence]:
    """Native-owned sentences from a per-language ``*_sentences_detailed.tsv.bz2`` export."""
    with bz2.open(archive, "rt", encoding="utf-8") as fh:
        for line in fh:
            # id, lang, text, owner, date added, date modified
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 4 or fields[3] not in natives:
                continue
            sid, text, owner = fields[0], fields[2], fields[3]
            yield Sentence(
                id=f"tat-{sid}",
                text=normalize_text(text),
                source=Source(
                    corpus="tatoeba",
                    ref=sid,
                    license=LICENSE,
                    attribution=f"Tatoeba sentence #{sid} by {owner} (export {pin.version})",
                    url=f"https://tatoeba.org/en/sentences/show/{sid}",
                ),
                register="conversation",
                slice="open",
            )


def sentences(cache: Path | None = None) -> Iterator[Sentence]:
    cache = cache or cache_dir()
    pins = load_source_pins("corpora")
    natives = native_speakers(fetch(pins[USER_LANGUAGES], cache))
    yield from read_sentences(fetch(pins[SENTENCES], cache), natives, pins[SENTENCES])

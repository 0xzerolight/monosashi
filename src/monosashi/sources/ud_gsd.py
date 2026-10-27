"""UD Japanese GSD: formal Wikipedia sentences, CC BY-SA 4.0. Only the raw text is used."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from monosashi.jmdict import cache_dir, fetch
from monosashi.kana import normalize_text
from monosashi.schema import Source
from monosashi.sources import Sentence, SourcePin, load_source_pins

LICENSE = "CC-BY-SA-4.0"
PREFIX = "ud-gsd-"


def read_conllu(path: Path, pin: SourcePin) -> Iterator[Sentence]:
    sent_id = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("# sent_id = "):
                sent_id = line.removeprefix("# sent_id = ").strip()
            elif line.startswith("# text = ") and sent_id is not None:
                yield Sentence(
                    id=f"gsd-{sent_id}",
                    text=normalize_text(line.removeprefix("# text = ").strip()),
                    source=Source(
                        corpus="ud-gsd",
                        ref=sent_id,
                        license=LICENSE,
                        attribution=f"UD Japanese GSD {pin.version}, sentence {sent_id}",
                        url=pin.extra["repo_url"],
                    ),
                    register="formal",
                    slice="open",
                )
                sent_id = None


def sentences(cache: Path | None = None) -> Iterator[Sentence]:
    cache = cache or cache_dir()
    for key, pin in load_source_pins("corpora").items():
        if key.startswith(PREFIX):
            yield from read_conllu(fetch(pin, cache), pin)

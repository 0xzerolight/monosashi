"""MeCab through fugashi, with unidic-lite, raw: one unit per token, no merging.

form is orthBase, reading is kana, form_reading is kanaBase. An unknown token
(no features) keeps its surface as its form and has no reading.

adapters/unidic3 runs ``units`` on the full UniDic in its own venv, so this
module must import nothing outside the standard library but fugashi.
"""

from __future__ import annotations

import functools
from importlib import metadata
from typing import Any

import fugashi

from monosashi.adapters.protocol import serve, to_hiragana
from monosashi.adapters.unidic_pos import kind_of


def units(tagger: fugashi.Tagger, text: str) -> list[dict[str, Any]]:
    """The units of ``text`` as ``tagger`` segments it, whichever UniDic it loads."""
    out = []
    pos = 0
    for word in tagger(text):
        pos += len(word.white_space)
        start, end = pos, pos + len(word.surface)
        pos = end
        f = word.feature
        kind = kind_of(f.pos1, f.pos2)
        if kind is None:
            continue
        unit: dict[str, Any] = {"start": start, "end": end, "surface": word.surface, "kind": kind}
        unit["form"] = f.orthBase or word.surface
        if f.kana:
            unit["reading"] = to_hiragana(f.kana)
        if f.kanaBase:
            unit["form_reading"] = to_hiragana(f.kanaBase)
        out.append(unit)
    return out


@functools.cache
def _tagger() -> fugashi.Tagger:
    # Built on first use, so importing ``units`` builds no tagger.
    return fugashi.Tagger()


def analyze(text: str) -> list[dict[str, Any]]:
    return units(_tagger(), text)


def main() -> None:
    serve(
        analyze,
        {
            "name": "fugashi-unidic-lite",
            "version": f"fugashi {metadata.version('fugashi')}, unidic-lite {metadata.version('unidic-lite')}",
            "dictionary": "UniDic 2.1.2 (unidic-lite)",
            "dictionary_date": "2013",
            "partition": True,
            "fields": ["form", "reading", "form_reading", "kind"],
        },
    )


if __name__ == "__main__":
    main()

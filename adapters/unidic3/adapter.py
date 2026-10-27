"""MeCab through fugashi, with the full UniDic 3.1, raw: one unit per token, no merging.

The mapping is fugashi-unidic-lite's (``monosashi.adapters.fugashi_unidic.units``),
field for field; only the dictionary differs. Runs in adapters/unidic3/.venv
(see README.md), with src/ on PYTHONPATH for the protocol and that mapping. The
tagger loads, by path, the dictionary ``python -m unidic download`` put in the
unidic package; ``--describe`` reports the version file that download wrote.
"""

from __future__ import annotations

import os
from importlib import metadata

import fugashi
import unidic

from monosashi.adapters.fugashi_unidic import units
from monosashi.adapters.protocol import Unit, serve

_tagger = fugashi.Tagger(f'-r "{os.path.join(unidic.DICDIR, "mecabrc")}" -d "{unidic.DICDIR}"')


def analyze(text: str) -> list[Unit]:
    return units(_tagger, text)


def main() -> None:
    # "unidic-3.1.0+2021-08-31": the release and date of the dicts.json entry downloaded.
    release, _, date = unidic.VERSION.removeprefix("unidic-").partition("+")
    serve(
        analyze,
        {
            "name": "unidic3",
            "version": f"fugashi {metadata.version('fugashi')}, unidic {metadata.version('unidic')}",
            "dictionary": f"UniDic {release} (unidic)",
            "dictionary_date": date,
            "partition": True,
            "fields": ["form", "reading", "form_reading", "kind"],
        },
    )


if __name__ == "__main__":
    main()

"""SudachiPy with SudachiDict-full, in split mode A or C (``--mode A`` / ``--mode C``).

form is dictionary_form, reading is reading_form. When the surface is the
dictionary form, form_reading is that same reading, read in context (あの方:
かた). Sudachi gives no reading for the dictionary form of an inflected word,
so its form_reading is the reading Sudachi gives the form when it is
tokenized on its own (cached), out of context, or nothing when the form does
not come back as one morpheme.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from importlib import metadata
from typing import Any

from sudachipy import Dictionary, SplitMode

from monosashi.adapters.protocol import serve, to_hiragana
from monosashi.adapters.unidic_pos import kind_of

MODE = sys.argv[sys.argv.index("--mode") + 1] if "--mode" in sys.argv else "C"
_SPLIT = {"A": SplitMode.A, "B": SplitMode.B, "C": SplitMode.C}[MODE]
_tokenizer = Dictionary(dict="full").tokenizer(mode=_SPLIT)


@lru_cache(maxsize=65536)
def _form_reading(form: str) -> str | None:
    morphemes = _tokenizer.tokenize(form)
    if len(morphemes) != 1:
        return None
    return to_hiragana(morphemes[0].reading_form())


def analyze(text: str) -> list[dict[str, Any]]:
    units = []
    for m in _tokenizer.tokenize(text):
        pos = m.part_of_speech()
        kind = kind_of(pos[0], pos[1])
        if kind is None:
            continue
        form = m.dictionary_form()
        reading = to_hiragana(m.reading_form())
        unit: dict[str, Any] = {
            "start": m.begin(),
            "end": m.end(),
            "surface": m.surface(),
            "kind": kind,
            "form": form,
            "reading": reading,
        }
        form_reading = reading if m.surface() == form else _form_reading(form)
        if form_reading is not None:
            unit["form_reading"] = form_reading
        units.append(unit)
    return units


def main() -> None:
    dict_version = metadata.version("sudachidict-full")
    serve(
        analyze,
        {
            "name": f"sudachi-{MODE.lower()}",
            "version": f"SudachiPy {metadata.version('sudachipy')}, mode {MODE}",
            "dictionary": f"SudachiDict-full {dict_version}",
            "dictionary_date": f"{dict_version[:4]}-{dict_version[4:6]}-{dict_version[6:8]}",
            "partition": True,
            "fields": ["form", "reading", "form_reading", "kind"],
        },
    )


if __name__ == "__main__":
    main()

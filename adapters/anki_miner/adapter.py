"""anki_miner's mining parser, raw: one unit per card word it mines from a sentence.

Runs in anki_miner's own venv (README.md), with src/ on PYTHONPATH for the
protocol only. The registry points ANKI_MINER_HOME at the cache, so anki_miner
reads its dictionary from there and never touches the real ~/.anki_miner.

Only the pinned commit runs. The adapter reads the checkout's HEAD before it
imports anything from it, since another commit may not even import, and exits
naming both commits when HEAD is not ``PINNED_COMMIT``.

The parser is built the way anki_miner's ``create_services`` builds it for a
Japanese config with ``SETTINGS`` applied: ``SubtitleParserService`` with the
offline probes of the JMdict index in the ``jmdict-english`` slot (compound
matching, kana recovery, the verb-front resolver, attested readings, entry
tags) and the name-wordset matcher. Each record is one ``ReadingUnit`` through
``parse_text_units``, the path anki_miner's reading tab mines text with; none
of the optional filters (known words, frequency, word lists, name wordsets)
run, as with its ``bypass_optional_filters``.

``SETTINGS`` are user settings a learner can pick in anki_miner, chosen for the
highest card-ready rate on this gold set: number + counter cards on, pre-noun
adjectives and conjunctions among the mined parts of speech, and proper nouns
and numerals no longer excluded subtypes. The name-wordset matcher stays, as
without it names split into junk pieces.

anki_miner is content-only: it outputs card words, not a partition. For each:

- span: ``surface_start`` to ``highlight_end``, the full inflected form the
  card bolds (蒔いた, not 蒔い); ``surface_end`` when ``highlight_end`` is -1.
  ``parse_text_units`` normalizes the text first and its offsets index that
  normalized sentence, so they are mapped back to the input text.
- form: ``mined_form``, the card front.
- form_reading: ``expression_reading``, the card's reading of the front.

``parse_text_units`` runs with ``every_occurrence``, so a word that occurs twice
in a record is output at both places; mining itself makes one card of it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from importlib import metadata
from pathlib import Path
from typing import Any

from monosashi.adapters.protocol import serve, to_hiragana

# The pin in README.md.
PINNED_COMMIT = "0b66053f809ce04a6ff1f1a4aadb10421cc582af"
# The slot AnkiMinerConfig's default dictionary_chain points at.
DICT_SLOT = "jmdict-english"
# AnkiMinerConfig fields set over the defaults (module docstring).
SETTINGS: dict[str, Any] = {
    "mine_number_counters": True,
    "allowed_pos": ("名詞", "動詞", "形容詞", "副詞", "形状詞", "代名詞", "連体詞", "接続詞"),
    "excluded_subtypes": ("非自立", "接尾", "助動詞", "接頭"),
}


def check_commit(checkout: Path) -> str:
    """The commit checked out at ``checkout``; exits unless it is ``PINNED_COMMIT``."""
    result = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(
            f"anki_miner adapter: {checkout} is not a git checkout of anki_miner: {result.stderr.strip()}"
        )
    head = result.stdout.strip()
    if head != PINNED_COMMIT:
        sys.exit(
            f"anki_miner adapter: {checkout} is at {head}, not the pinned {PINNED_COMMIT};"
            " check out the pin, or move it (adapters/anki_miner/README.md)"
        )
    return head


def _original_spans(text: str, normalized: str, normalize: Callable[[str], str]) -> list[tuple[int, int]]:
    """The span of ``text`` each character of ``normalized`` came from.

    Built by normalizing ever longer prefixes of ``text``: the characters a new
    input character adds come from it (ﾋ → ヒ, ⾞ → 車, ㌀ → アパート), and the
    characters it rewrites are merged with it (ﾋ then ﾟ → ピ, か then a
    combining mark → が). A character that adds and changes nothing (a
    stripped decoration glyph) belongs to no span.
    """
    spans: list[tuple[int, int]] = []
    prev = ""
    for i in range(len(text)):
        cur = normalize(text[: i + 1])
        same = 0
        while same < min(len(prev), len(cur)) and prev[same] == cur[same]:
            same += 1
        start = spans[same][0] if same < len(spans) else i
        spans = spans[:same] + [(start, i + 1)] * (len(cur) - same)
        prev = cur
    if prev != normalized:
        raise ValueError("anki_miner normalized the text unlike its own normalizer")
    return spans


def main() -> None:
    if not os.environ.get("ANKI_MINER_HOME"):
        sys.exit("anki_miner adapter: ANKI_MINER_HOME is not set; run it through `monosashi run anki_miner`")
    found = importlib.util.find_spec("anki_miner")
    if found is None or found.origin is None:
        sys.exit("anki_miner adapter: anki_miner is not installed here; see adapters/anki_miner/README.md")
    commit = check_commit(Path(found.origin).resolve().parents[1])

    import anki_miner
    from anki_miner.config.config import AnkiMinerConfig
    from anki_miner.models.reading import ReadingUnit
    from anki_miner.services.definition_service import DefinitionService
    from anki_miner.services.dictionary.registry import DictionaryRegistry
    from anki_miner.services.subtitle_parser import SubtitleParserService
    from anki_miner.services.wordset_service import WordsetService
    from anki_miner.utils.ja_normalize import normalize_for_tokenization, standardize_kanji_variants

    config = replace(AnkiMinerConfig(), **SETTINGS)
    registry = DictionaryRegistry(config.dicts_root)
    registry.load()
    definitions = DefinitionService(
        config, providers=registry.build_provider_chain(config), registry=registry
    )
    if not definitions.ensure_loaded():
        sys.exit(
            f"anki_miner adapter: no dictionary in {config.dicts_root / DICT_SLOT}; see adapters/anki_miner/README.md"
        )
    wordsets = WordsetService(enabled_ids=config.excluded_wordsets)
    wordsets.load()
    parser = SubtitleParserService(
        config,
        term_lookup=definitions.offline_terms_exist,
        name_lookup=wordsets.excluded_terms if wordsets.is_available() else None,
        reading_lookup=definitions.offline_term_readings,
        kana_attest_lookup=definitions.has_offline_definitions,
        term_common_lookup=definitions.offline_term_commonness,
        term_rules_lookup=definitions.offline_deinflection_terms_exist,
        form_lookup=definitions.offline_term_rows,
    )

    def normalize(text: str) -> str:
        """The normalization ``parse_text_units`` applies to a unit's text before tokenizing."""
        return standardize_kanji_variants(normalize_for_tokenization(text))

    def analyze(text: str) -> list[dict[str, Any]]:
        words, _index, _counts = parser.parse_text_units(
            [ReadingUnit(text=text, index=0, location_label="")], want_line_index=False, every_occurrence=True
        )
        # Offsets index the stored line, the unit text after normalization. Mapping
        # them back still takes the normalizer itself, run on prefixes of the input.
        sentence = words[0].sentence if words else text
        spans = _original_spans(text, sentence, normalize) if sentence != text else None
        units = []
        for w in words:
            start, end = w.surface_start, w.bold_end
            if spans is not None:
                start, end = spans[start][0], spans[end - 1][1]
            unit: dict[str, Any] = {
                "start": start,
                "end": end,
                "surface": text[start:end],
                "form": w.mined_form,
            }
            if w.expression_reading:
                unit["form_reading"] = to_hiragana(w.expression_reading)
            units.append(unit)
        return units

    meta = json.loads((config.dicts_root / DICT_SLOT / "meta.json").read_text(encoding="utf-8"))
    serve(
        analyze,
        {
            "name": "anki_miner",
            "version": f"anki_miner {anki_miner.__version__}, unidic-lite {metadata.version('unidic-lite')}",
            "commit": commit,
            "dictionary": f"{meta['source_name']} (jmdict-yomitan JMdict_english), imported by anki_miner",
            # source_revision is "JMdict.2026-10-09"
            "dictionary_date": str(meta["source_revision"]).removeprefix("JMdict."),
            "partition": False,
            "fields": ["form", "form_reading"],
        },
    )


if __name__ == "__main__":
    main()

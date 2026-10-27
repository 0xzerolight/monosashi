"""Licenses a record's source text may carry (SPEC.md §8, rule `license`)."""

from __future__ import annotations

ALLOWED_SOURCE_LICENSES = frozenset(
    {
        "CC0-1.0",  # Tatoeba's CC0 subset
        "public-domain",  # Aozora Bunko works out of copyright, the Tanaka Corpus
        "CC-BY-2.0-FR",  # Tatoeba
        "CC-BY-4.0",
        "CC-BY-SA-4.0",  # UD Japanese GSD, our own synthetic sentences, the anki_miner corpus
        "MIT",  # ichiran's test suite (seed)
        "Apache-2.0",  # Jiten's test suite (seed)
    }
)

"""The pool: every candidate sentence, filtered, deduplicated and tagged.

``build_pool`` reads the open corpora (Tatoeba, Aozora, UD GSD) and the
committed seeds and synthetic sentences, keeps the ones of a usable length,
drops duplicates, and caps the largest corpora by a seeded sample so tagging
stays fast. ``tag_pool`` adds category hints in parallel. Both write to the
cache; selection reads the tagged pool and commits only what it picks.
"""

from __future__ import annotations

import random
import unicodedata
from collections.abc import Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

from monosashi.jmdict import Dictionary, cache_dir, ensure_index, repo_root
from monosashi.kana import has_kanji, is_hiragana, is_katakana
from monosashi.sources import Sentence, aozora, dump_sentences, load_sentences, tatoeba, ud_gsd
from monosashi.tag import tag

# A typical subtitle line. Seeds are test cases and may be shorter.
MIN_LENGTH = 4
MIN_SEED_LENGTH = 2
MAX_LENGTH = 60
# Per-corpus sample sizes; the rest of a corpus is never tagged.
CAPS = {"tatoeba": 30_000, "aozora": 20_000}
POOL_SEED = 20261015


def pool_dir() -> Path:
    return cache_dir() / "pool"


def _japanese_share(text: str) -> float:
    return sum(is_hiragana(ch) or is_katakana(ch) or has_kanji(ch) for ch in text) / len(text)


def usable(sentence: Sentence) -> bool:
    text = sentence.text
    floor = MIN_SEED_LENGTH if sentence.slice == "seed" else MIN_LENGTH
    if not floor <= len(text) <= MAX_LENGTH or "\ufffd" in text:
        return False
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        return False  # a line break inside a seed (two subtitle lines in one test)
    # Mostly Japanese: drops lines that are mostly Latin, digits or markup.
    return _japanese_share(text) >= 0.6


def committed_sentences(*dirs: str) -> Iterator[Sentence]:
    for name in dirs:
        for path in sorted((repo_root() / "data" / name).glob("*.jsonl")):
            yield from load_sentences(path)


def open_sentences(cache: Path | None = None) -> Iterator[Sentence]:
    yield from tatoeba.sentences(cache)
    yield from aozora.sentences(cache)
    yield from ud_gsd.sentences(cache)


def build_pool(streams: Iterable[Iterable[Sentence]], seed: int = POOL_SEED) -> list[Sentence]:
    """Usable sentences, the first copy of each text kept, large corpora sampled down to ``CAPS``."""
    seen: set[str] = set()
    by_corpus: dict[str, list[Sentence]] = {}
    for stream in streams:
        for sentence in stream:
            if sentence.text in seen or not usable(sentence):
                continue
            seen.add(sentence.text)
            by_corpus.setdefault(sentence.source.corpus, []).append(sentence)
    pool: list[Sentence] = []
    for corpus, sentences in by_corpus.items():
        cap = CAPS.get(corpus)
        if cap is not None and len(sentences) > cap:
            # One generator per corpus, so re-pinning Tatoeba leaves the Aozora sample alone.
            sentences = random.Random(f"{seed}:{corpus}").sample(sentences, cap)
        pool += sentences
    return pool


_worker_dictionary: Dictionary | None = None


def _init_worker(index: Path) -> None:
    global _worker_dictionary
    _worker_dictionary = Dictionary(index)


def _tag_one(sentence: Sentence) -> Sentence:
    assert _worker_dictionary is not None
    return tag(sentence, _worker_dictionary)


def tag_pool(pool: list[Sentence], index: Path | None = None, workers: int | None = None) -> list[Sentence]:
    index = index or ensure_index()
    with ProcessPoolExecutor(max_workers=workers, initializer=partial(_init_worker, index)) as executor:
        return list(executor.map(_tag_one, pool, chunksize=64))


def write_pool(sentences: list[Sentence], name: str) -> Path:
    path = pool_dir() / f"{name}.jsonl"
    dump_sentences(path, sentences)
    return path

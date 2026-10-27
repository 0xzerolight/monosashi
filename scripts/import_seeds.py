"""One-shot import of the seed sentences into data/seeds/ (see monosashi.sources.seeds).

    uv run python scripts/import_seeds.py [--anki-miner ~/Projects/anki_miner]

ichiran and Jiten are fetched by their pinned raw URLs. The anki_miner corpus is
read from a local checkout at the pinned commit with ``git show``, and checked
against the pinned hash of its files (path NUL content, in path order).
Re-running at the same pins rewrites the same files.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from collections.abc import Iterator
from pathlib import Path

from monosashi.jmdict import cache_dir, fetch, repo_root
from monosashi.sources import Sentence, SourcePin, dump_sentences, load_source_pins, sentence_problems
from monosashi.sources.seeds import SUITES, parse_anki_miner, parse_ichiran, parse_jiten, to_sentences


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def anki_miner_sentences(repo: Path, pin: SourcePin) -> Iterator[Sentence]:
    listing = _git(repo, "ls-tree", "-r", "-z", "--name-only", pin.version, "--", pin.extra["path"])
    files = sorted(f for f in listing.decode("utf-8").split("\0") if f.endswith(".jsonl"))
    digest = hashlib.sha256()
    contents = {}
    for f in files:
        contents[f] = _git(repo, "show", f"{pin.version}:{f}")
        digest.update(f.encode() + b"\0" + contents[f])
    if digest.hexdigest() != pin.sha256:
        raise SystemExit(f"anki_miner corpus at {pin.version[:12]} does not match the pinned sha256")
    for f in files:
        yield from to_sentences(
            SUITES["anki_miner"],
            parse_anki_miner(contents[f].decode("utf-8")),
            path=f,
            version=pin.version,
            url=f"{pin.extra['blob_url']}/{f}",
            id_of="row-id",
        )


def fetched_sentences(key: str, pin: SourcePin) -> Iterator[Sentence]:
    parse = {"ichiran": parse_ichiran, "jiten": parse_jiten}[key]
    source = fetch(pin, cache_dir()).read_text(encoding="utf-8-sig")
    yield from to_sentences(
        SUITES[key], parse(source), path=pin.extra["path"], version=pin.version, url=pin.extra["blob_url"]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the seed sentences into data/seeds/.")
    parser.add_argument("--anki-miner", type=Path, default=Path.home() / "Projects" / "anki_miner")
    args = parser.parse_args()
    pins = load_source_pins("seeds")
    out_dir = repo_root() / "data" / "seeds"
    batches = {
        "ichiran": list(fetched_sentences("ichiran", pins["ichiran"])),
        "jiten": list(fetched_sentences("jiten", pins["jiten"])),
        "anki_miner": list(anki_miner_sentences(args.anki_miner, pins["anki_miner"])),
    }
    for key, sentences in batches.items():
        bad = [(s.id, p) for s in sentences for p in sentence_problems(s)]
        if bad:
            raise SystemExit(f"{key}: {bad[:5]}")
        count = dump_sentences(out_dir / f"{key}.jsonl", sentences)
        print(f"{out_dir / key}.jsonl: {count} sentences")


if __name__ == "__main__":
    main()

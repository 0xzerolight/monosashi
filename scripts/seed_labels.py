"""Seed gold records without their text, the form in which they are published.

    uv run python scripts/seed_labels.py strip     # data/private/core -> data/seed-labels
    uv run python scripts/seed_labels.py rebuild   # data/seed-labels + data/seeds -> data/private/core

Seed sentences quote song lyrics and novels, so data/seed-labels/ leaves out each
record's text and its units' surfaces. ``rebuild`` takes the text back from
data/seeds/; run ``scripts/import_seeds.py`` first. Run ``strip`` after a
``label merge`` changes data/private/core.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from monosashi.jmdict import repo_root
from monosashi.schema import dump_records, load_records
from monosashi.sources import load_sentences
from monosashi.sources.seeds import with_text, without_text


def strip(private: Path, labels: Path) -> None:
    labels.mkdir(parents=True, exist_ok=True)
    for path in sorted(private.glob("*.jsonl")):
        records = list(load_records(path))
        with (labels / path.name).open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(without_text(record), ensure_ascii=False) + "\n")
        print(f"{labels / path.name}: {len(records)} records")


def rebuild(labels: Path, seeds: Path, private: Path) -> None:
    texts = {s.id: s.text for p in sorted(seeds.glob("*.jsonl")) for s in load_sentences(p)}
    private.mkdir(parents=True, exist_ok=True)
    for path in sorted(labels.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        missing = [row["id"] for row in rows if row["id"] not in texts]
        if missing:
            raise SystemExit(f"{path}: no seed sentence for {missing[:5]}; run scripts/import_seeds.py first")
        dump_records(private / path.name, [with_text(row, texts[row["id"]]) for row in rows])
        print(f"{private / path.name}: {len(rows)} records")


def main() -> None:
    parser = argparse.ArgumentParser(description="Strip seed gold records of their text, or restore it.")
    parser.add_argument("command", choices=["strip", "rebuild"])
    args = parser.parse_args()
    data = repo_root() / "data"
    if args.command == "strip":
        strip(data / "private" / "core", data / "seed-labels")
    else:
        rebuild(data / "seed-labels", data / "seeds", data / "private" / "core")


if __name__ == "__main__":
    main()

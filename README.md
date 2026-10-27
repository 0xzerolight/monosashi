# monosashi

物差し: a yardstick for Japanese tokenizers, measured the way language-learning tools use them.

monosashi is a gold set of Japanese sentences labeled with learner word units, plus a harness that runs existing tokenizers on it and scores them. A learner word unit is a JMdict entry with its inflection chain, its dictionary form and its reading in context. The question it answers: which tool turns real text into correct flashcard words without post-processing?

Version 0.1: 993 gold records under spec 0.5, and nine tools scored in [RESULTS.md](RESULTS.md). The labeling rules are in [SPEC.md](SPEC.md).

## Use

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run monosashi jmdict build                                   # fetch and index the pinned JMdict + JMnedict
uv run monosashi score results/* --gold data/core/*.jsonl       # score the committed predictions
uv run --group adapters monosashi run fugashi-unidic-lite sudachi-c   # run the light adapters into runs/
uv run monosashi score runs/*
```

The heavy adapters (ichiran, himotoki, Jiten, Yomitan, anki_miner, full UniDic) each have their setup in `adapters/<name>/README.md`.

To score your own tool, write an adapter: a command that reads `{"id", "text"}` lines on stdin and answers each with `{"id", "units": [...]}`, and prints what it outputs for `--describe`. The contract is in [predictions.py](src/monosashi/predictions.py), a standard-library helper in [protocol.py](src/monosashi/adapters/protocol.py). List it in [adapters/registry.toml](adapters/registry.toml), then `uv run monosashi run NAME`.

## Seed records

306 of the records are other tools' test sentences, some quoting song lyrics and novels. They ship without their text in `data/seed-labels/`. To score them too:

```bash
git clone https://github.com/0xzerolight/anki_miner ../anki_miner
uv run python scripts/import_seeds.py --anki-miner ../anki_miner   # data/seeds/, from each tool's pinned source
uv run python scripts/seed_labels.py rebuild                         # data/private/core/, which run and score then include
```

## License

Code: GPL-3.0-or-later ([LICENSE](LICENSE)). Data: CC BY-SA 4.0 ([data/LICENSE](data/LICENSE)). Each record also keeps the license of its source text.

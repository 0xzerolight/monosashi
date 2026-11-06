<h1 align="center">monosashi 物差し</h1>

<p align="center">
<a href="https://github.com/0xzerolight/monosashi/actions/workflows/ci.yml"><img src="https://github.com/0xzerolight/monosashi/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+"></a>
<a href="https://www.gnu.org/licenses/gpl-3.0"><img src="https://img.shields.io/badge/code-GPLv3-blue.svg" alt="Code: GPL v3"></a>
<a href="https://creativecommons.org/licenses/by-sa/4.0/"><img src="https://img.shields.io/badge/data-CC%20BY--SA%204.0-lightgrey.svg" alt="Data: CC BY-SA 4.0"></a>
<a href="https://github.com/0xzerolight/monosashi/stargazers"><img src="https://img.shields.io/github/stars/0xzerolight/monosashi?style=social" alt="GitHub stars"></a>
</p>

<p align="center">
A yardstick for Japanese tokenizers, measured the way language-learning tools use them.
</p>

<p align="center">
Please leave a ⭐ star if monosashi helped you - it helps others find it :).
</p>


# <p align="center">Results</p>

monosashi is a gold set of Japanese sentences labeled with learner word units, plus a harness that runs existing tokenizers on it and scores them. A learner word unit is what a learner would look up: a JMdict entry with its inflection chain, its dictionary form and its reading in context. The question it answers: which tool turns real text into correct flashcard words without post-processing?

Version 0.1: 993 gold records under spec 0.5, nine tools. The overall scores, on the 687 records that are not from a tool's own test suite:

| tool | card-ready rate | junk rate (lower is better) | median ms |
|---|--:|--:|--:|
| [jiten](https://github.com/Sirush/Jiten) | 85.1 | 10.8 | 4.72 |
| [ichiran](https://github.com/tshatrov/ichiran) | 83.4 | 15.9 | 185.22 |
| [himotoki](https://github.com/moikdev/himotoki-rs) | 82.7 | 17.3 | 3.76 |
| [anki_miner](https://github.com/0xzerolight/anki_miner) | 76.6 | 4.4 | 1.89 |
| [yomitan](https://github.com/yomidevs/yomitan) | 75.7 | 27.8 | 18.75 |
| [sudachi-c](https://github.com/WorksApplications/sudachi.rs) | 61.4 | 27.0 | 0.04 |
| [sudachi-a](https://github.com/WorksApplications/sudachi.rs) | 58.0 | 26.7 | 0.06 |
| [unidic3](https://github.com/polm/unidic-py) | 56.9 | 28.2 | 0.31 |
| [fugashi-unidic-lite](https://github.com/polm/fugashi) | 56.6 | 28.2 | 0.18 |

Card-ready rate: the share of gold words a tool outputs as a correct card, with the right span, dictionary form and reading. Junk rate: the share of a tool's cards that are not gold words. Every table, with 95% intervals and breakdowns by category, register and slice: [RESULTS.md](RESULTS.md). The labeling rules: [SPEC.md](SPEC.md).

## Installation

### Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- For the heavy adapters only: Docker (ichiran, Jiten), Node 22+ (Yomitan), Rust 1.87+ (himotoki), an anki_miner checkout (anki_miner).

```bash
git clone https://github.com/0xzerolight/monosashi.git
cd monosashi
uv sync
uv run monosashi jmdict build                                   # fetch and index the pinned JMdict + JMnedict
uv run monosashi score results/* --gold data/core/*.jsonl       # score the committed predictions
uv run --group adapters monosashi run fugashi-unidic-lite sudachi-c   # run the light adapters into runs/
uv run monosashi score runs/*
```

<details>
<summary><strong>Heavy adapters</strong></summary>

Each runs in its own environment, pinned to a commit, with its setup in `adapters/<name>/README.md`. Once set up: `uv run monosashi run NAME`.

| Adapter | Needs | Setup |
|---|---|---|
| ichiran | Docker, about 5 GB of database | [adapters/ichiran](adapters/ichiran/README.md) |
| jiten | Docker, about 3 GB of checkout and database | [adapters/jiten](adapters/jiten/README.md) |
| himotoki | Rust 1.87+, a 2.1 GB database | [adapters/himotoki](adapters/himotoki/README.md) |
| yomitan | Node 22+, 1.6 GB of memory while it runs | [adapters/yomitan](adapters/yomitan/README.md) |
| unidic3 | its own venv, so the full UniDic never becomes fugashi's default here | [adapters/unidic3](adapters/unidic3/README.md) |
| anki_miner | a checkout at `~/Projects/anki_miner`, used read-only | [adapters/anki_miner](adapters/anki_miner/README.md) |

</details>

<details>
<summary><strong>Score your own tool</strong></summary>

Write an adapter: a command that reads `{"id", "text"}` lines on stdin and answers each with `{"id", "units": [...]}`, and prints what it outputs for `--describe`. The contract is in [predictions.py](src/monosashi/predictions.py), a standard-library helper in [protocol.py](src/monosashi/adapters/protocol.py). List it in [adapters/registry.toml](adapters/registry.toml), then `uv run monosashi run NAME`.

</details>

<details>
<summary><strong>Seed records</strong></summary>

306 of the records are other tools' test sentences, some quoting song lyrics and novels. They ship without their text in `data/seed-labels/`. To score them too:

```bash
git clone https://github.com/0xzerolight/anki_miner ../anki_miner
uv run python scripts/import_seeds.py --anki-miner ../anki_miner   # data/seeds/, from each tool's pinned source
uv run python scripts/seed_labels.py rebuild                         # data/private/core/, which run and score then include
```

</details>

## What it measures

- **Card-ready rate** - the headline: gold words the tool outputs with the right span, form and reading. Strict, and lenient, which forgives a split at a compound's accepted split point (一人|暮らし).
- **Junk rate** - always next to it, so a tool can't score by emitting more words.
- **Segmentation** - span F1, boundary F1 and content-unit F1.
- **Forms and readings** - accuracy on the spans a tool reproduces, and on the gold units its pieces tile.
- **Entry accuracy** - for tools that output JMdict ids, against the pinned snapshot.
- **Normalization** - colloquial variants mapped to the standard word (すげー -> すごい).
- **Breakdowns** - 28 categories (inflection chains, contractions, heteronyms, counters, Kansai-ben and more), registers, slices and seed suites.
- **Speed** - median milliseconds per sentence, warm.

The definitions are in [SPEC.md §7](SPEC.md#7-how-labels-are-scored).

<details>
<summary><strong>How It Works</strong></summary>

1. **Select** sentences from Tatoeba, Aozora Bunko and UD Japanese GSD, filling a quota for each hard category; lines Claude wrote fill the categories real text covers thinly.
2. **Label** each sentence twice, blind: two Claude Opus labelers work from a sheet of every JMdict entry that could match, without seeing tool output or each other.
3. **Validate** every record against [SPEC.md](SPEC.md): spans, entry ids in the pinned JMdict, chains that deinflect back to the form, readings.
4. **Adjudicate** disagreements, agreed words no learner tool reproduces, and a 10% audit; rulings on the rules become spec versions.
5. **Score** each tool behind one JSONL contract against the gold units.

</details>

<details>
<summary><strong>Data sources and licenses</strong></summary>

Sentences from [Tatoeba](https://tatoeba.org) (CC BY 2.0 FR), [Aozora Bunko](https://www.aozora.gr.jp) (public domain), [UD Japanese GSD](https://github.com/UniversalDependencies/UD_Japanese-GSD) (CC BY-SA 4.0), lines written for monosashi, and the test suites of ichiran, Jiten and anki_miner. Entry ids refer to [JMdict and JMnedict](https://www.edrdg.org/edrdg/licence.html) (EDRDG, CC BY-SA 4.0), through [jmdict-simplified](https://github.com/scriptin/jmdict-simplified). Every record names its source and license; the full credits are in [ATTRIBUTION.md](ATTRIBUTION.md).

</details>

## Troubleshooting

| Issue | Solution |
|---|---|
| `ModuleNotFoundError: fugashi` or `sudachipy` | The light adapters live in the optional `adapters` group, which `uv sync` removes. Run them with `uv run --group adapters`. |
| `jmdict build`: sha256 does not match the pin | The upstream file changed after it was pinned. Open an issue with the message. |
| Seed and category tables differ from RESULTS.md | `results/` holds no predictions for the seed records, so only the Overall table reproduces from it. Rebuild the seeds ([Seed records](#installation)) and rerun the tools. |
| anki_miner: `~/Projects/anki_miner/.venv/bin/python` not found | The registry runs anki_miner from a checkout there. Clone it as in [adapters/anki_miner](adapters/anki_miner/README.md), or change its `command` in [adapters/registry.toml](adapters/registry.toml). |
| ichiran or jiten: `No such container` | Start its compose project first: [adapters/ichiran](adapters/ichiran/README.md), [adapters/jiten](adapters/jiten/README.md). |

## Contributing

Contributions of any kind are welcome: a wrong gold label, a new tool, a fix.

- New here? Start with [CONTRIBUTING.md](CONTRIBUTING.md).
- The labeling rules: [SPEC.md](SPEC.md).
- Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Security: [SECURITY.md](SECURITY.md).

Bug reports, gold-label errors and new tools -> [Issues](https://github.com/0xzerolight/monosashi/issues).
Questions and discussion -> [Discussions](https://github.com/0xzerolight/monosashi/discussions).

## Acknowledgements

monosashi stands on JMdict and JMnedict, jmdict-simplified, the corpora above, and the tools it measures, three of which lent it their test suites. The full credits are in [ATTRIBUTION.md](ATTRIBUTION.md).

## License

Code: GPL-3.0-or-later ([LICENSE](LICENSE)). Data: CC BY-SA 4.0 ([data/LICENSE](data/LICENSE)). Each record also keeps the license of its source text.

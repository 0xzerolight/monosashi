<h1 align="center">monosashi 物差し</h1>

<p align="center">
<a href="https://github.com/0xzerolight/monosashi/actions/workflows/ci.yml"><img src="https://github.com/0xzerolight/monosashi/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+"></a>
<a href="https://www.gnu.org/licenses/gpl-3.0"><img src="https://img.shields.io/badge/code-GPLv3-blue.svg" alt="Code: GPL v3"></a>
<a href="https://creativecommons.org/licenses/by-sa/4.0/"><img src="https://img.shields.io/badge/data-CC%20BY--SA%204.0-lightgrey.svg" alt="Data: CC BY-SA 4.0"></a>
<a href="https://github.com/0xzerolight/monosashi/stargazers"><img src="https://img.shields.io/github/stars/0xzerolight/monosashi?style=social" alt="GitHub stars"></a>
</p>

<p align="center">
A measurement tool for Japanese tokenizers.
</p>

<p align="center">
Please leave a ⭐ star if monosashi helped you - it helps others find it :).
</p>


# <p align="center">Results</p>

993 Japanese sentences labeled with the words a learner would look up in JMdict, and a harness that scores tokenizers on them.

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

687 records; the tools' own test sentences are left out. Card-ready: gold words output with the right span, form and reading. Junk: output words that match no gold word. Full tables: [RESULTS.md](RESULTS.md). Labeling rules: [SPEC.md](SPEC.md).

## Installation

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/0xzerolight/monosashi.git
cd monosashi
uv sync
uv run monosashi jmdict build                                   # fetch and index the pinned JMdict
uv run monosashi score results/* --gold data/core/*.jsonl       # score the committed predictions
uv run --group adapters monosashi run fugashi-unidic-lite sudachi-c   # run the light adapters
uv run monosashi score runs/*
```

<details>
<summary><strong>Heavy adapters</strong></summary>

Set one up from its README, then `uv run monosashi run NAME`.

| Adapter | Needs |
|---|---|
| [ichiran](adapters/ichiran/README.md) | Docker, ~5 GB |
| [jiten](adapters/jiten/README.md) | Docker, ~3 GB |
| [himotoki](adapters/himotoki/README.md) | Rust 1.87+, ~2 GB |
| [yomitan](adapters/yomitan/README.md) | Node 22+ |
| [unidic3](adapters/unidic3/README.md) | its own venv |
| [anki_miner](adapters/anki_miner/README.md) | a checkout at `~/Projects/anki_miner` |

</details>

<details>
<summary><strong>Score your own tool</strong></summary>

An adapter reads `{"id", "text"}` lines, answers `{"id", "units": [...]}`, and says what it outputs on `--describe`. Contract: [predictions.py](src/monosashi/predictions.py). Helper: [protocol.py](src/monosashi/adapters/protocol.py). Register it in [adapters/registry.toml](adapters/registry.toml).

</details>

<details>
<summary><strong>Seed records</strong></summary>

306 records are other tools' test sentences, shipped without their text. To restore it:

```bash
git clone https://github.com/0xzerolight/anki_miner ../anki_miner
uv run python scripts/import_seeds.py --anki-miner ../anki_miner
uv run python scripts/seed_labels.py rebuild
```

</details>

## What it measures

- **Card-ready rate** - strict, and lenient on accepted compound splits (一人|暮らし).
- **Junk rate** - output words that match no gold word.
- **Segmentation** - span, boundary and content-unit F1.
- **Form, reading and entry accuracy.**
- **Normalization** - すげー -> すごい.
- **Breakdowns** - 28 categories, registers, slices, seed suites.
- **Speed** - median ms per sentence.

Definitions: [SPEC.md §7](SPEC.md#7-how-labels-are-scored).

<details>
<summary><strong>How It Works</strong></summary>

1. **Select** sentences by category quota; Claude-written lines fill thin categories.
2. **Label** each sentence twice, blind, with two Claude Opus agents.
3. **Validate** every record against [SPEC.md](SPEC.md).
4. **Adjudicate** disagreements, plus a 10% audit.
5. **Score** each tool through one JSONL contract.

</details>

<details>
<summary><strong>Data sources</strong></summary>

[Tatoeba](https://tatoeba.org) (CC BY 2.0 FR), [Aozora Bunko](https://www.aozora.gr.jp) (public domain), [UD Japanese GSD](https://github.com/UniversalDependencies/UD_Japanese-GSD) (CC BY-SA 4.0), Claude-written lines, and the test suites of ichiran, Jiten and anki_miner. Entries: [JMdict and JMnedict](https://www.edrdg.org/edrdg/licence.html) (EDRDG, CC BY-SA 4.0) via [jmdict-simplified](https://github.com/scriptin/jmdict-simplified). Credits: [ATTRIBUTION.md](ATTRIBUTION.md).

</details>

## Troubleshooting

| Issue | Solution |
|---|---|
| `ModuleNotFoundError: fugashi` or `sudachipy` | Use `uv run --group adapters`; `uv sync` drops that group. |
| `jmdict build`: sha256 mismatch | The upstream file changed; open an issue. |
| Seed or category tables differ from RESULTS.md | `results/` has no seed predictions; only Overall reproduces. |
| anki_miner: `~/Projects/anki_miner/.venv/bin/python` not found | Clone it there, or edit its `command` in [registry.toml](adapters/registry.toml). |
| ichiran or jiten: `No such container` | Start its compose project ([ichiran](adapters/ichiran/README.md), [jiten](adapters/jiten/README.md)). |

## Contributing

- [CONTRIBUTING.md](CONTRIBUTING.md), [Code of Conduct](CODE_OF_CONDUCT.md), [Security](SECURITY.md).
- Bugs, gold-label errors, new tools -> [Issues](https://github.com/0xzerolight/monosashi/issues).
- Questions -> [Discussions](https://github.com/0xzerolight/monosashi/discussions).

## License

Code: GPL-3.0-or-later ([LICENSE](LICENSE)). Data: CC BY-SA 4.0 ([data/LICENSE](data/LICENSE)), each record also under its source's license.

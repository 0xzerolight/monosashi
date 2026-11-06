# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-11-06

### Added
- **Contributor guide, code of conduct and security policy.** CONTRIBUTING.md covers setup, the gate, fixing a gold label, changing the spec, adding a tool and the data rules; CODE_OF_CONDUCT.md is Anki Miner's Contributor Covenant 3.0; SECURITY.md takes reports through private advisories.
- **Issue forms for bugs, wrong gold labels and new tools.** Blank issues are off; questions go to Discussions.

### Changed
- **anki_miner remeasured with four settings changed from its defaults.** Card-ready 76.6, up from 59.2; junk 4.4, down from 5.8. The adapter runs anki_miner at commit 0b66053 with number + counter cards on, pre-noun adjectives and conjunctions mined, and proper nouns and numerals not excluded: the user settings with the highest card-ready rate on this gold set. It also outputs a word at each of its occurrences in a sentence, not only the first. RESULTS.md notes the settings next to the scores.
- **README rewritten,** with the overall results, the heavy adapters' requirements and a troubleshooting table, in Anki Miner's layout.
- CI pins its actions by commit and runs with a read-only token; Dependabot keeps the actions current. Python dependencies stay as locked, since the light adapters' versions are part of the results.

## [0.1.0] - 2026-10-27

First version.

### Added
- **Gold set of 993 sentences under spec 0.5.** 687 public records from Tatoeba, Aozora Bunko, UD Japanese GSD and lines Claude wrote, each with its source and license. 306 seed records from the test suites of ichiran, Jiten and anki_miner ship without their text, which `scripts/import_seeds.py` and `scripts/seed_labels.py rebuild` restore from each tool's pinned source.
- **Nine tools measured (RESULTS.md).** fugashi + unidic-lite, full UniDic 3.1, Sudachi modes A and C, ichiran, himotoki-rs, Jiten, Yomitan and anki_miner, each pinned to a commit, with their predictions in `results/`.
- **Scorer (`monosashi score`).** Card-ready rate, strict and lenient, with the junk rate beside it; segmentation F1; form, reading and entry accuracy; normalization; speed. 95% bootstrap intervals and breakdowns by category, register, slice and seed suite.
- **Adapter contract for any tool (`monosashi run`).** JSONL in and out, with `--describe`; light adapters run in this repo's venv, heavy ones in their own pinned environments.
- **Validator (`monosashi validate`).** One named rule per check of SPEC.md, listed in its §8.
- **Pinned JMdict and JMnedict (`monosashi jmdict build`).** Fetched from jmdict-simplified, sha256-checked and indexed locally; `monosashi jmdict lookup` and `monosashi candidates` read the index.
- **Labeling pipeline (`monosashi pool`, `select`, `label`, `review`).** Category tagging and quotas, blind bundles for two labelers, agreement and the review queue, merge into `data/core`.

[Unreleased]: https://github.com/0xzerolight/monosashi/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/0xzerolight/monosashi/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/0xzerolight/monosashi/releases/tag/v0.1.0

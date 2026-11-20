# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **A second measure beside the card-ready rate: the right word at the right start.** The gold word's dictionary form and reading on a unit that starts in the right place, wherever the tool ends it (食べ of 食べ|させ|られ|なかっ|た finds 食べる). It separates "wrong word" from "unit ends elsewhere": Sudachi mode C scores 61.8 card-ready and 74.3 on this; Jiten 85.4 and 87.6.

### Changed
- **anki_miner remeasured at commit 17d3c96 (3.13.0 plus unreleased changes).** Card-ready 83.1, up from 76.6; junk 4.3, down from 4.4.
- **A second right reading passes.** Any reading the entry gives the tool's spelling is accepted as its dictionary reading (明日 read あす, 行く read ゆく), except on a unit tagged `heteronym`, where a sense picks the reading. Card-ready rises 0.2 to 0.7 points per tool.
- **A gold suffix, prefix or copula offered as a word is no longer junk.** 先生 in 田中先生, だらけ, 元 and だった are dictionary words that gold gives no card; they are left out of the junk count. A particle offered as a card is still junk. Junk falls 0.5 to 1.8 points per tool.
- **The category table leaves out the tools' own test sentences,** as the overall row does, so `results/` now reproduces it.
- **The README calls monosashi a measurement of learner word lookup, not of tokenizers,** and its table shows the new measure.

### Fixed
- **Gold labels audited record by record: 107 fixes in 95 of the 993 records.** Every record was reread against SPEC.md 0.5 with each tool's output beside it. 18 fixes change a unit a score reads (boundaries such as わけ|ねー -> わけねー and 指揮せざる|を|えない -> 指揮|せざるをえない, readings such as その後 そのご -> そのあと, a clock-time 30分, 番地 and 元 as affixes); the rest are category tags (73), split points (4) and particle-versus-copula labels (12). RESULTS.md and the README table are rescored: no card-ready rate moves by more than 0.2 points (ichiran 83.5, himotoki 82.9, unidic3 56.8) and the order is unchanged; anki_miner's junk rate reads 4.4.

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

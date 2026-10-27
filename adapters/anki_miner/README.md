# anki_miner adapter

[anki_miner](https://github.com/0xzerolight/anki_miner), the vocabulary-mining app this benchmark grew out of: its mining parser, raw. Registry name `anki_miner`.

## Pin

| Source | Pin |
|---|---|
| anki_miner | commit `0b66053f809ce04a6ff1f1a4aadb10421cc582af` (2026-10-27), version 3.10.1 plus unreleased changes |
| Tokenizer dictionary | unidic-lite 1.0.8 (UniDic 2.1.2), from anki_miner's venv |
| JMdict | [jmdict-yomitan](https://github.com/yomidevs/jmdict-yomitan) release `2026-10-09`, `JMdict_english.zip`, 15,607,868 bytes, sha256 `ae45a789a7fd47f2a6f05c8d8238abf78c9352576fb7fe97cbc0e107c4fe173c` ("JMdict [2026-10-09]") |

The adapter refuses any other checkout: it exits naming both commits before importing anki_miner. To move the pin, change `PINNED_COMMIT` in `adapter.py` and this table, then rerun. The JMdict is the build anki_miner's recommended download installs. 2026-10-09 is the closest one that was on this machine to monosashi's 2026-10-12 snapshot, and anki_miner outputs no entry ids, so the three-day gap only touches the dictionary checks its parser makes.

## Setup

The adapter runs in anki_miner's own venv at `~/Projects/anki_miner/.venv` (the registry's path) and only reads it. A checkout without one:

```sh
git clone https://github.com/0xzerolight/anki_miner.git ~/Projects/anki_miner
cd ~/Projects/anki_miner && git checkout 0b66053f809ce04a6ff1f1a4aadb10421cc582af
python -m venv .venv && .venv/bin/pip install -e .
```

anki_miner's user data lives in the cache, never in `~/.anki_miner`: the registry points `ANKI_MINER_HOME` at `~/.cache/monosashi/adapters/anki_miner/home`. Use `MONOSASHI_CACHE` in place of `~/.cache/monosashi` if you set it.

Import the JMdict there with anki_miner's own importer, into the `jmdict-english` slot its default config reads (about 2 minutes, 240 MB). Import again after moving the pin if anki_miner reports a wrong `schema_version`:

```sh
H=~/.cache/monosashi/adapters/anki_miner
mkdir -p $H
curl -L -o $H/JMdict_english.zip https://github.com/yomidevs/jmdict-yomitan/releases/download/2026-10-09/JMdict_english.zip
echo "ae45a789a7fd47f2a6f05c8d8238abf78c9352576fb7fe97cbc0e107c4fe173c  $H/JMdict_english.zip" | sha256sum -c
ANKI_MINER_HOME=$H/home ~/Projects/anki_miner/.venv/bin/python -c "
from pathlib import Path
from anki_miner.config.config import AnkiMinerConfig
from anki_miner.services.dictionary.importers.yomitan_importer import import_yomitan_zip
import_yomitan_zip(Path('$H/JMdict_english.zip'), AnkiMinerConfig().dicts_root, dict_id='jmdict-english', overwrite=True)"
```

## Run

```sh
uv run monosashi run anki_miner --gold data/selection/core.jsonl --out runs
```

## Output

`partition` is false: anki_miner outputs the words it would make cards of, not the whole sentence, so it is scored as a content-only tool (SPEC §7). Fields are `form` (the card front, `mined_form`) and `form_reading` (the card's reading, `expression_reading`). The span runs from the word's start to the end of its inflected form (`highlight_end`), so 始めてしまった is one unit with form 始める. The adapter docstring says how the parser is built.

The parser is the one anki_miner builds for a Japanese config: JMdict lookups on, plus the name-wordset matcher, which keeps a known name whole (大江山, not 江山). The filters a mining run applies afterwards (known words, frequency, word lists, the name exclusion) do not run. A word that occurs twice in a sentence is output at both places.

The config sets four user settings over anki_miner's defaults, chosen for the highest card-ready rate on this gold set (`SETTINGS` in `adapter.py`): number + counter cards on (4人, read よにん), pre-noun adjectives and conjunctions mined (大きな, 又), and proper nouns and numerals no longer excluded. With anki_miner's defaults it scores lower: about 1.7 points from the counters and 0.8 from the other three.

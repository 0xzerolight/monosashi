# yomitan adapter

[Yomitan](https://github.com/yomidevs/yomitan) (GPL-3.0-or-later), the pop-up dictionary extension: its scanning parser, the one its search page uses to split a sentence into terms, raw. Registry name `yomitan`.

## Pin

| Source | Pin |
|---|---|
| Yomitan | commit `e7334a96106a6c74e6fa75bd33a5ea1219d92712` (2026-10-09), release tag `26.10.12.0` |
| npm packages | Yomitan's `package-lock.json` at that commit |
| JMdict | [jmdict-yomitan](https://github.com/yomidevs/jmdict-yomitan) release `2026-10-12`, `JMdict_english.zip`, 15,609,387 bytes, sha256 `1b31f9f4200f684bf9ead6b90296777a4b72a5db3055dde25d5d3b9cde489070` ("JMdict [2026-10-12]") |

Built and run with Node 22.22.1 (Yomitan needs 22 or later) and npm 12.0.2.

The JMdict is downloaded, not copied from anki_miner's 2026-10-09 one, because this adapter outputs entry ids: the 2026-10-12 build is the same day's JMdict as monosashi's snapshot. Each of its 527,394 term rows has a sequence that is an entry of that snapshot, with the row's term among the entry's spellings.

## Setup

The checkout, its npm packages and the dictionary live in the cache (430 MB); the repo holds only the adapter. Use `MONOSASHI_CACHE` in place of `~/.cache/monosashi` if you set it.

```sh
Y=~/.cache/monosashi/adapters/yomitan
git clone https://github.com/yomidevs/yomitan.git $Y/src
git -C $Y/src checkout e7334a96106a6c74e6fa75bd33a5ea1219d92712
(cd $Y/src && npm ci --ignore-scripts --allow-git=all && node dev/bin/build-libs.js)
curl -L -o $Y/JMdict_english.zip https://github.com/yomidevs/jmdict-yomitan/releases/download/2026-10-12/JMdict_english.zip
echo "1b31f9f4200f684bf9ead6b90296777a4b72a5db3055dde25d5d3b9cde489070  $Y/JMdict_english.zip" | sha256sum -c
```

npm 12 needs `--allow-git=all` for Yomitan's one git dependency (yomitan-handlebars); `--ignore-scripts` skips its git hook setup. `build-libs.js` bundles the libraries Yomitan's modules import from `ext/lib/`.

## Run

```sh
uv run monosashi run yomitan --gold data/selection/core.jsonl --out runs
```

Each time the adapter starts, it imports the JMdict into an in-memory database: about 32 s and 1.6 GB before the first sentence.

## What runs

Yomitan's own modules from the checkout, unchanged: DictionaryImporter and DictionaryDatabase load the JMdict, and the parse is `Backend.prototype._onApiParseText` with the scanning parser (`_textParseScanning`), over Yomitan's Translator, its Japanese deinflection rules and text processors, and its furigana split. The settings are a fresh profile's defaults (scan length 16), with the dictionary added the way the settings page adds a sequenced one after an import: enabled, default settings, main dictionary.

What stands in for the browser:

- Globals, stubbed the way Yomitan's own tests stub them: `indexedDB` and `IDBKeyRange` from fake-indexeddb, `fetch` and `chrome` from `test/mocks/common.js` (they read files from `ext/`), and `self` and a no-op `Worker` from `test/utilities/database.js`. That Worker is the database's helper for drawing dictionary images, and JMdict has none.
- The importer's media loader: `test/mocks/dictionary-importer-media-loader.js`.
- The Backend object. It is never constructed, because its constructor wires the extension's browser APIs. Its parse methods run on a stand-in that holds the Translator, the options and the parse cache, as `test/backend-mecab-parse.test.js` does. The parse runs without a profile index, so Yomitan's parse cache stays off. That changes speed, not output.

The parser keeps only each term's headword and furigana, so the adapter keeps what each findTerms call returned. It also reads the chosen row's tags and raw sequence from the database. Both happen outside the parse.

## Output

`partition` is true: the parser walks the whole sentence. Text where no term starts is a gap and is not output. A term that is only punctuation is not output either. For each term:

- `form`, `form_reading`: the headword of the first entry findTerms returned at that position, the one whose furigana the parser shows (始めてしまった: 始める, はじめる).
- `reading`: the parser's furigana over the text, with kana as written, in hiragana, with ー and 〜 kept.
- `entries`: the row's sequence. jmdict-yomitan writes a search-only spelling's row (すご〜い, 飛んでもない) with the entry's JMdict id negated (`jmdictSearchTerm` in yomitan-import). Yomitan treats that as no sequence; the adapter outputs the id.
- `kind`: from the row's part-of-speech tags in JMdict's order, mapped as the ichiran adapter maps them. `cop` anywhere makes a copula; otherwise the first tag decides: `prt` particle, `aux`, `aux-v` and `aux-adj` auxiliary, `pref` prefix, `suf` suffix, `int` interjection, `exp` expression, and any other a word. A search-only spelling's row and a "forms" row have no tags, so they have no kind.

A reading that is not kana is left out, because Yomitan has none. jmdict-yomitan gives a search-only kanji spelling no reading, and Yomitan fills it with the term. The furigana split gives none where the text differs from the headword: 10月 for １０月, はMe for 羽目. On core, 155 of 8,922 units have no `reading`, 29 have no `form_reading`, and 88 have no `kind`.

Yomitan ranks what it finds by match length, then by the fewest text-processing and deinflection steps, then by whether the spelling matches the text, and only then by the dictionary's score. So uninflected した is 舌 rather than する, and a search-only spelling of the text (ワイ, ええん) comes before the entry's main headword.

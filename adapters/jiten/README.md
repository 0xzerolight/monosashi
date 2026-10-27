# jiten adapter

[Jiten](https://github.com/Sirush/Jiten) (Apache-2.0), the parser behind jiten.moe: Sudachi plus Jiten's own token repairs, deconjugator and JMdict matching, over a Postgres dictionary. Its own C# code runs in Docker, as compose project `monosashi-jiten`. Registry name `jiten`.

## Pin

| Source | Pin |
|---|---|
| Jiten | commit `2c69236b547de51ebac489f463830f4adba71e0e` (2026-10-15), parser revision 1 |
| JMdict | EDRDG `http://ftp.edrdg.org/pub/Nihongo/JMdict.gz`, "JMdict created: 2026-10-15", 22,202,018 bytes, sha256 `d1da7185e4cb331c08bdef9c89d3651a078de9583c8c13ba41353c04b9d30cc4` |
| JMnedict | EDRDG `http://ftp.edrdg.org/pub/Nihongo/JMnedict.xml.gz`, "JMnedict created: 2026-10-15", 12,447,859 bytes, sha256 `71e99dbdd48693078dd33e6d83661b994b3dcf82d88e8d714f9c47be43706487` |
| JmdictFurigana | [release `2.3.1+2026-09-25`](https://github.com/Doublevil/JmdictFurigana/releases/tag/2.3.1%2B2026-09-25), `JmdictFurigana.json`, 34,736,193 bytes, sha256 `2a8e206f0b171fa5acdce89e5f5798621b227175e5bfa2db6bd92fef63dd962e` |
| Sudachi dictionary | [SudachiDict `v20260428`](https://github.com/WorksApplications/SudachiDict/releases/tag/v20260428), `sudachi-dictionary-20260428-full.zip`, sha256 `2048891c7155c9c876c80d6dd9a0e9749c16bf294c5a9fe24a839b36d8278f88`; its `system_full.dic` has sha256 `2c993988aae44cbad92b395790c951aa2dad957c983a7d4c32944f6263e02593` |
| Sudachi library, user dictionary, rules | `Shared/resources/` in the Jiten commit (`libsudachi_lib.so`, `user_dic.dic`, `deconjugator.json`, `ruby_reading_priors.msgpack`, ...) |

EDRDG serves only its current files, so the JMdict and JMnedict above cannot be downloaded again once EDRDG updates them; keep the copies in the cache. The 2026-10-15 files were the current ones on 2026-10-16, the closest to monosashi's 2026-10-12 snapshot that EDRDG still had.

Jiten's guide says to take the latest SudachiDict. 20260428 is the one its user dictionary was built against: rebuilding `user_dic.dic` from the `user_dic.xml` in `user_dic.zip` with `sudachipy ubuild` (0.6.11) against 20260428 gives the shipped file to the byte, apart from the 8-byte build time in its header; against 20260723 it differs in 14 more bytes, where the user entries point at system words. The 20261015 release is in a format Jiten's Sudachi library does not read.

The base images resolved to these on the build measured here (2026-10-16):

| Input | Resolved to |
|---|---|
| `mcr.microsoft.com/dotnet/sdk:9.0` | `sha256:2f5eb32870b4c0074a3d5b5191a03553bcab7b74463a76a7c0a5f3ef65c90fe5`, SDK 9.0.319 |
| `mcr.microsoft.com/dotnet/aspnet:9.0` | `sha256:4d94cf3204df98d321e8dbf8d6d06e0b34fd136aa75c945abf4390ee07eb30dd`, .NET 9.0.21 |
| `postgres:17-bookworm` (Jiten's `postgres-pgroonga/Dockerfile`) | `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826`, PostgreSQL 17.11, PGroonga 4.0.6 |
| `redis:latest` | `sha256:2c2dff791878316e3b083188be0d578423b24813cdda5de0e80ea4f7b3e6bfd6`, Redis 8.10.2 |
| NuGet packages | the versions in Jiten's `.csproj` files at the commit |

Jiten's `global.json` asks for SDK 9.0.121 with `latestFeature`, which a host with only .NET 10 does not satisfy; the build runs in the .NET 9 SDK image, as Jiten's own Dockerfiles do.

## Setup

The checkout and the dictionary files live in the cache (1.7 GB); the database lives in the Docker volume `monosashi-jiten_pgdata` (1.5 GB). Use `MONOSASHI_CACHE` in place of `~/.cache/monosashi` if you set it; the compose file reads it too. Run from the repo root.

```sh
J=~/.cache/monosashi/adapters/jiten
git clone https://github.com/Sirush/Jiten.git $J/src
git -C $J/src checkout 2c69236b547de51ebac489f463830f4adba71e0e

mkdir -p $J/data && cd $J/data
curl -LO http://ftp.edrdg.org/pub/Nihongo/JMdict.gz
curl -LO http://ftp.edrdg.org/pub/Nihongo/JMnedict.xml.gz
curl -LO https://github.com/Doublevil/JmdictFurigana/releases/download/2.3.1%2B2026-09-25/JmdictFurigana.json
curl -LO https://github.com/WorksApplications/SudachiDict/releases/download/v20260428/sudachi-dictionary-20260428-full.zip
sha256sum -c <<'EOF'
d1da7185e4cb331c08bdef9c89d3651a078de9583c8c13ba41353c04b9d30cc4  JMdict.gz
71e99dbdd48693078dd33e6d83661b994b3dcf82d88e8d714f9c47be43706487  JMnedict.xml.gz
2a8e206f0b171fa5acdce89e5f5798621b227175e5bfa2db6bd92fef63dd962e  JmdictFurigana.json
2048891c7155c9c876c80d6dd9a0e9749c16bf294c5a9fe24a839b36d8278f88  sudachi-dictionary-20260428-full.zip
EOF
gunzip -k JMdict.gz JMnedict.xml.gz
unzip -j sudachi-dictionary-20260428-full.zip '*/system_full.dic'
# Jiten's import folds ゎ into わ, which turns entry 2857539's search-only でゎでゎ into a
# second でわでわ, against its own unique index on forms; leave that one spelling out.
sed '5215902,5215905d' JMdict > JMdict-jiten
echo "0bfe1a561a16a19f4c50e7728065eb9f7d1697bdd8ab0c7af7022d3349eba226  JMdict-jiten" | sha256sum -c
cd -

docker compose -f adapters/jiten/compose.yaml -p monosashi-jiten up -d --build
X="docker exec monosashi-jiten-main-1 dotnet cli/Jiten.Cli.dll"
$X --apply-migrations
$X -i --xml /app/jmdict_dtd.xml --dic /data/JMdict-jiten --namedic /data/JMnedict.xml --furi /data/JmdictFurigana.json
$X --sync-jmdict --xml /app/jmdict_dtd.xml --dic /data/JMdict-jiten --furi /data/JmdictFurigana.json --skip-kanji-rebuild \
   --sync-jmnedict /data/JMnedict.xml
```

The image build takes about two minutes. The import is Jiten's own CLI, in the steps its `DEVELOPMENT.md` gives (`--apply-migrations`, then `-i`), about 8 minutes; the sync takes about 7 more. The sync is the step jiten.moe runs on every JMdict update: the first import leaves per-form data out (priorities, search-only and obsolete flags, sense order) that only the sync writes, and the parser's form scoring reads it. `--skip-kanji-rebuild` skips the kanji tables, which the parser does not use.

One input of jiten.moe's parser is not public, so this setup runs without it: the word and form frequency ranks (`jmdict."WordFrequencies"`, `"WordFormFrequencies"`), which Jiten computes from its corpus of media decks (`--compute-frequencies`) and which its parser uses to rank candidate words and readings. Both tables are empty here, so every word counts as unranked: where jiten.moe weighs corpus frequency (choosing between candidate words and readings, resegmenting low-confidence spans), only Jiten's other scores decide.

Jiten's sync is written for EDRDG's "next generation" format (`JMdict_e_NG`: `lsource` on the entry, sequence numbers on `xref`). Fed the classic file its `DEVELOPMENT.md` names, it reads no `lsource` or `info` and resolves none of the 37,002 cross-references. The parser reads one of these: a word's gairaigo origin, which one rule uses to reject a hiragana spelling of a loanword. jiten.moe also takes word origins from a vocabulary-origin CSV (`--import-vocabulary-origin`) that is not public. Here every word's origin is unknown.

## Stop and restart

```sh
docker compose -f adapters/jiten/compose.yaml -p monosashi-jiten stop     # the database is kept
docker compose -f adapters/jiten/compose.yaml -p monosashi-jiten start
```

Redis keeps nothing on disk, so a restart empties the parser's cache; output does not depend on it. `down -v` removes the containers and the database.

## Run

```sh
uv run monosashi run jiten --gold data/selection/core.jsonl --out runs
```

The registry command is `docker exec -i monosashi-jiten-main-1 dotnet adapter/MonosashiJiten.dll`: one process per run, which speaks the contract itself. It starts the parser the way Jiten's API does (`Parser.WarmupAsync`: the lookup table and word metadata from Postgres, Sudachi's contexts), about 3.5 s before the first sentence, which itself takes about 4 s while Jiten's caches fill. Over the 993 core records the median is 3.7 ms per record.

## What runs

Jiten's own code, unchanged, from the checkout: `Jiten.Parser.Parser.ParseText`, the call behind jiten.moe's `/vocabulary/parse` and its reader, then that endpoint's placement of the words in the text: `TokenPositionHelper.FindTokenInSource` from `Jiten.Api/Helpers`, compiled into the adapter, finds each word after the one before, allowing for the ー and line breaks the parser drops and for the colloquial spellings it rewrites (とんでもねえ). The configuration is Jiten's example settings file with the database, Redis and dictionary from the environment, as Jiten's Dockerfiles set it.

## Output

Four fields: `form`, `form_reading`, `entries` and `kind`. The header comment of `Program.cs` says where each comes from.

No `reading`: Jiten's parse output has no reading of the text (the API's word is its WordId, ReadingIndex, text and conjugations). The parser does keep a `SudachiReading` on each word to score forms, but for a word it built from several Sudachi tokens that is the first token's reading: でも reads で, んだ reads ん, ３つ reads つ. On core, 286 of the 4,801 words written in kana would have had a reading that is not their own text.

`form_reading` is the chosen form's reading the way Jiten's API reads it. The forms are loaded as `WordFormHelper.LoadWordForms` loads them, where `RubyTextHelper.EnrichForms` infers furigana for a kanji form that has none from the entry's kana forms (２日 gets ２日[ふつか]); then a kana form gives its own text and a kanji form `RubyTextHelper.KanaFromRubyText` (始[はじ]める: はじめる). On core, 4 of 8,448 units have none: カ月, ヶ月 and １カ月, whose furigana sits on a katakana カ or ヶ that `KanaFromRubyText` does not take, and the name エズラ・パウンド, whose ・ is not kana. A name's furigana is inferred too, from the kana form at the same index of Jiten's merged name, so it can be a rare reading (佐藤 さいう, 鈴木 すすき).

`entries` holds Jiten's WordId. Jiten's import reads each JMdict `ent_seq` into the WordId, then each JMnedict `ent_seq` that JMdict does not already have into the WordId of a name (JMdict has 7,303 entries in JMnedict's range, names it took over; Jiten keeps JMdict's). Both number their entries below 8,000,000, apart from their date records (9999999, 9999990), and Jiten's own words start at 8,000,000. Checked against monosashi's 2026-10-12 snapshot, every Jiten word below 8,000,000 is an entry of it, JMdict for words and JMnedict for names, except 17 entries added since (16 JMdict, 1 JMnedict); on core, all 8,448 units' entries are (8,284 JMdict, 164 JMnedict). Jiten merges the JMnedict entries that share their first spelling into one word with the first entry's id, so a name's id is the JMnedict entry that comes first in the file, whichever of them the text means. Jiten's own words (でした, こうする, 逢魔, イクシオトキシン) have no entry.

`partition` is true: `ParseText` attempts the whole text. What it does not resolve to a dictionary word is not in its output and scores as a gap: punctuation and symbols, digits alone, single fullwidth letters, a few kana fragments it removes as misparses, and tokens no dictionary entry matches. Its text cleaning also drops characters outside the ranges it keeps before Sudachi sees them: Latin letters, halfwidth katakana, and kanji outside the basic CJK block (𠮷). On the first 100 core records, 34 have a gap, covering 209 of the records' 3,025 non-symbol characters; over all 993, 222 records and 1,003 of 20,383 characters. Common gaps are numbers alone (2008, 17), laughter and other repeated kana (ハハハハ, へへへへ), stray kana (ひ, そ) and unknown katakana names.

Placement follows the endpoint with one difference. The parser turns ASCII digits fullwidth before Sudachi sees them, so it returns １人 for 1人, which the endpoint cannot find in the text and leaves out; the adapter searches the text with the same change made (Jiten's `ToFullWidthDigits`, one character for one) and takes the surface from the input. A word whose text the parser changed in a way the placement does not undo (あり得ねぇー as あり得ねー, 世話になってま〜す as 世話になってます, 頑張 って as 頑張って) is still lost, as on jiten.moe, and so is a word the search passed while placing an earlier one further on: 11 words on core. The earlier word itself can then sit on the wrong span: in aoz-2093-169-2 (アハ……アハ……可笑しい可笑しい……アハアハアハアハアハ……), the アハアハ Jiten read from アハ……アハ at 0–6 is placed at 18–22, and both 可笑しい are lost. The adapter writes a line to the run's `stderr.log` for each.

# ichiran adapter

[ichiran](https://github.com/tshatrov/ichiran) (MIT), the Common Lisp + PostgreSQL reference implementation of JMdict-anchored segmentation for learners, in the Docker containers its own `docker-compose.yml` builds. Registry name `ichiran`.

## Pin

| Source | Pin |
|---|---|
| ichiran | commit `d00bee6e864c8863ed7ba0eb14ae8ee8221a22fa` (2026-10-11) |
| Database | release [`ichiran-260118`](https://github.com/tshatrov/ichiran/releases/tag/ichiran-260118), `https://github.com/tshatrov/ichiran/releases/download/ichiran-260118/ichiran-260118.pgdump` (the URL in that commit's `docker-compose.yml`), 200,012,956 bytes, sha256 `98a44e2cc88a65677da8b1f7124e7d6c904253eb1aae0ef16d2c7cc1dacdba82` |
| Dictionary | the JMdict in that dump, "Creation Date: 2026-01-01" (its entry 9999999), plus the errata ichiran's init applies |

ichiran's Dockerfiles leave some inputs unpinned. They resolved to these on the build measured here (2026-10-15):

| Input | Resolved to |
|---|---|
| `postgres:latest` | PostgreSQL 18.6, `sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336` |
| `debian:bookworm-slim` | `sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587`, with SBCL 2.2.9 |
| Quicklisp | dist `2026-01-01` |
| jmdictdb (`git clone`, master) | `c9c82328d0ba5b15c496c4a32116da105be29e4c` (2026-01-17) |

## Setup

The checkout, the images and the database (4.5 GB in `src/docker/pgdata`) live in the cache. Use `MONOSASHI_CACHE` in place of `~/.cache/monosashi` if you set it. The compose project is named `monosashi-ichiran`, so the containers are `monosashi-ichiran-pg-1` and `monosashi-ichiran-main-1` (the registry's `ICHIRAN_CONTAINER`).

```sh
H=~/.cache/monosashi/adapters/ichiran
git clone https://github.com/tshatrov/ichiran.git $H/src
git -C $H/src checkout d00bee6e864c8863ed7ba0eb14ae8ee8221a22fa
cd $H/src    # the compose file mounts ${PWD}/docker/pgdata
docker compose -p monosashi-ichiran build
docker compose -p monosashi-ichiran up -d
docker logs -f monosashi-ichiran-main-1    # wait for "All set, awaiting commands."
```

The build takes a few minutes and downloads the dump into the postgres image. Then the first `up` restores the dump (about 6 minutes), and ichiran builds its caches and `ichiran-cli` (under a minute). The restore prints `ERROR: schema "public" already exists` and `errors ignored on restore: 1`, which are harmless. To check the dump against the pin:

```sh
docker run --rm --entrypoint sha256sum monosashi-ichiran-pg /ichiran.pgdump
```

## Stop and restart

Run these from `~/.cache/monosashi/adapters/ichiran/src`.

```sh
docker compose -p monosashi-ichiran stop     # stop; the database and ichiran's init are kept
docker compose -p monosashi-ichiran start    # back in seconds
```

`down` removes the containers but keeps the database, and the next `up -d` runs ichiran's init again (under a minute). To remove everything, run `docker compose -p monosashi-ichiran down --rmi local`, then delete the database. Its files belong to the container's postgres user, so delete them through a container:

```sh
docker run --rm -v $PWD/docker:/d debian:bookworm-slim rm -rf /d/pgdata
```

## Run

```sh
uv run monosashi run ichiran --gold data/selection/core.jsonl --out runs
```

The adapter runs in this repo's Python with the standard library only. It keeps one `ichiran-cli -e` process running in the main container, reading forms from stdin and printing each value as one JSON line, and sends each sentence the call `ichiran-cli -f` makes, `(romanize* text :limit 1)`. Starting `ichiran-cli -f` once per sentence would add its start-up, about 0.3 s, to every record. Over the 943 core records the median is 0.38 s per record (0.6 s on the first 100), almost all of it ichiran's own segmentation.

## Output

All five fields: `form`, `reading`, `form_reading`, `entries` (JMdict seq) and `kind`. The adapter docstring says how each is derived.

`partition` is true: ichiran attempts the whole sentence. It leaves gaps for text it cannot analyze, and gaps are not output, so they score as misses. On the first 100 core records, 24 have such a gap, covering 90 of the records' 2,964 non-symbol characters. ichiran also rewrites 〜 as ` - ` before segmenting, so a stretched word such as すご〜い comes out as gap す, prefix ご, gap い.

### ichiran's JSON

`ichiran-cli -f` prints a list with one item per run of the normalized text. A run of non-Japanese text (punctuation, Latin letters) is a string. A Japanese run is a list of segmentations, best first, each `[words, score]`. A word is `[romaji, info, prop]`. The adapter fills `prop` with `word-info-json` (the `-f` output leaves it empty) and reads both objects.

`info`, as `-f` prints it:

| Field | Meaning |
|---|---|
| `text` | The word as it stands in the normalized text. |
| `kana` | Its reading in context: hiragana, or katakana for a word written in katakana. U+200C marks a は or へ that is pronounced わ or え, and U+200B a break between romanized words (19本: じゅう, U+200B, きゅうほん). Compound parts are joined with a space (べんきょう しています). |
| `reading` | `text 【kana】`, or the kana alone for a word written in kana. |
| `seq` | The entry. Below 10,000,000 it is a JMdict id (9999999 is JMdict's own date record). From 10,000,000 up it is one of ichiran's own entries: a conjugated form ichiran generated, or an entry from its extra data (municipalities, extra words). |
| `score` | ichiran's score for the word. |
| `gloss` | The entry's senses: `pos` (JMdict parts of speech, such as `[v1,vt]`), `gloss`, and optionally `info` and `field`. It is left out when ichiran matched the word through a conjugation, and generated forms have no senses of their own. For a counter, only the counter senses are listed. |
| `conj` | One item per way the word is a conjugated form: `prop` (the conjugated part of speech and the conjugation `type`, with `neg` and `fml` flags), `reading` (the root entry's spelling, `食べる 【たべる】`), `gloss` (the root's senses for that part of speech) and `readok`. A conjugation of a conjugation (食べさせられた) has `via`, a nested `conj` for the intermediate form, in place of `reading` and `gloss`. A JMdict entry that is also a conjugated form of another (叫び of 叫ぶ, です of だ) has `conj` too, usually next to its own `gloss`. |
| `compound`, `components` | A compound word (始めて + しまった, 勉強 + して + います): the parts' texts, and one `info` per part. |
| `suffix` | On a compound part that acts as a suffix: what it adds. |
| `counter` | On a number + counter: `value` and `ordinal`. |
| `alternative` | In place of all the above, for a word with equally good readings (家: いえ or うち): one `info` per reading, best first. |

`prop`, ichiran's `word-info-json`:

| Field | Meaning |
|---|---|
| `type` | `KANJI`, `KANA`, or `GAP` for text ichiran could not analyze. |
| `truetext` | The dictionary spelling ichiran matched: やる for ヤル, which it finds by looking the katakana up as hiragana. |
| `components` | The parts of a compound, each with `primary` true for the part ichiran scores the compound by, or the readings of an `alternative`. |
| `conjugations` | The conjugation rows (ids in ichiran's `conjugation` table) a word was matched through, often empty. |
| `start`, `end`, `skipped` | Offsets within the run, and how many candidates ichiran discarded. |

Two things are not in the JSON and come from ichiran's database. The first is the root entry of a generated form: the `from` of its rows in the `conjugation` table, matched to the spelling `conj` names. The second is the parts of speech of a JMdict entry that is also a conjugated form, when ichiran lists no senses for it.

ichiran normalizes text before it segments: fullwidth digits and Latin letters become ASCII, halfwidth katakana becomes fullwidth, and punctuation is rewritten (。 to `. `, 、 to `, `, 〜 to ` - `). Its offsets index that normalized text. The adapter maps them back to the input with ichiran's own `normalize`, run on prefixes of the input, so ３つ and ﾋﾟｱﾉ come out with their input spans.

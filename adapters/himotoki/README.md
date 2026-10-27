# himotoki adapter

[himotoki-rs](https://github.com/moikdev/himotoki-rs) (MIT), the Rust port of himotoki/ichiran, through its Python bindings. Registry name `himotoki`.

## Pin

| Source | Pin |
|---|---|
| himotoki-rs | commit `12ed2eb315e01455a918a9144d5e34f400d3cf13` (2026-10-08), crate version 0.3.2 |
| Dictionary | `data/JMdict_e.xml` in that commit, "JMdict created: 2026-01-02", plus himotoki's errata pass |
| maturin | 1.15.0 |

Built with rustc 1.98.0 (the crates need 1.87 or later) and Python 3.12.

## Setup

The source, its build and the database (2.1 GB) live in the cache; the venv lives here and is gitignored. Run from the repo root, with `MONOSASHI_CACHE` in place of `~/.cache/monosashi` if you set it.

```sh
R=$PWD H=~/.cache/monosashi/adapters/himotoki
git clone https://github.com/moikdev/himotoki-rs.git $H/src
git -C $H/src checkout 12ed2eb315e01455a918a9144d5e34f400d3cf13

# The database, about 2 minutes
(cd $H/src &&
  cargo run --release -p himotoki-load -- jmdict data/JMdict_e.xml --db $H/himotoki.db &&
  cargo run --release -p himotoki-load -- conj --db $H/himotoki.db --data-dir data &&
  cargo run --release -p himotoki-load -- errata --db $H/himotoki.db)

# The bindings, in their own venv
uv venv --python 3.12 adapters/himotoki/.venv
uv pip install --python adapters/himotoki/.venv/bin/python maturin==1.15.0
(cd $H/src/crates/himotoki-py &&
  $R/adapters/himotoki/.venv/bin/maturin build --release --interpreter $R/adapters/himotoki/.venv/bin/python)
uv pip install --python adapters/himotoki/.venv/bin/python $H/src/target/wheels/himotoki_rs-0.3.2-*.whl
```

The first run builds a word index next to the database (`himotoki.db.fst`, about 5 s).

## Run

```sh
uv run monosashi run himotoki --gold data/selection/core.jsonl --out runs
```

The registry points `HIMOTOKI_DB_PATH` at the cache and sets `HIMOTOKI_MAX_TEXT_LENGTH` to 10000, so himotoki's default cap of 100 characters never rejects a record. That also lifts its complexity budget (10 × the cap² segment pairs), so a pathological sentence ends as the runner's 120 s timeout instead of an error.

## Output

All five fields: `form`, `reading`, `form_reading`, `entries` (JMdict seq) and `kind`. The adapter docstring says where each comes from.

himotoki lists a compound alternative before a dictionary entry whatever their scores (彼+ら before 彼ら, 読み+方 before 読み方). The adapter ranks alternatives by score, as ichiran does, so it reports 彼ら and 読み方.

`partition` is true: himotoki attempts the whole sentence. It leaves gaps for text it cannot analyze; gaps are not output and score as misses. Gaps are not only punctuation: onomatopoeia, kana runs and some names end up there too. On the first 100 core records, 27 have such a gap: 93 of the records' 2,964 non-symbol characters.

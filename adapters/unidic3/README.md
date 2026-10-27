# unidic3 adapter

MeCab through [fugashi](https://github.com/polm/fugashi) (MIT) with the full UniDic 3.1 from the [unidic](https://github.com/polm/unidic-py) package (MIT; the dictionary itself is NINJAL's, GPL/LGPL/BSD), raw. Registry name `unidic3`.

## Pin

| Source | Pin |
|---|---|
| fugashi | 1.5.2 (PyPI), the version this repo's `adapters` group locks; its wheel bundles MeCab |
| unidic | 1.1.0 (PyPI), `unidic-1.1.0.tar.gz`, sha256 `0ab91c05de342c84d2a6314901fd3afb9061ecd7534dd4a0431dccbb87d921b7` |
| Dictionary | UniDic 3.1.0, entry `3.1.0+2021-08-31` of unidic-py's `dicts.json` (master, `31ba63c3ba2a1b95652bf322d182fbc0bc9f3c2b`): `https://cotonoha-dic.s3-ap-northeast-1.amazonaws.com/unidic-3.1.0.zip`, 525,943,040 bytes, sha256 `638718c4c63625ab300de4c92c67925d54c0e9e3830009eaa992f29819d59c43`; unpacked `sys.dic` sha256 `f019f95838242cd614953a25201ad0b623b9c1cbca90de2507df4510db1b192c` |

This is unidic-py's edition of UniDic-cwj 3.1.0. Its README lists the changes from NINJAL's release: 令和 added, single-character numeric and alphabetic words removed, and `unk.def` changed so unknown punctuation is not a noun.

## Setup

The venv lives here and is gitignored; the download puts the dictionary (770 MB) in its site-packages. Run from the repo root:

```sh
uv venv --python 3.12 adapters/unidic3/.venv
uv pip install --python adapters/unidic3/.venv/bin/python fugashi==1.5.2 unidic==1.1.0
adapters/unidic3/.venv/bin/python -m unidic download 3.1.0+2021-08-31
D=$(adapters/unidic3/.venv/bin/python -c 'import unidic; print(unidic.DICDIR)')
echo "f019f95838242cd614953a25201ad0b623b9c1cbca90de2507df4510db1b192c  $D/sys.dic" | sha256sum -c
```

The download deletes the zip once it has unpacked it, so the check is on `sys.dic`. Never install `unidic` into this repo's own venv: fugashi prefers it to unidic-lite, so `fugashi-unidic-lite` would silently run on it.

## Run

```sh
uv run monosashi run unidic3 --gold data/selection/core.jsonl --out runs
```

## Output

The mapping is `fugashi-unidic-lite`'s (`monosashi.adapters.fugashi_unidic.units`): `form` is orthBase, `reading` kana, `form_reading` kanaBase, and `kind` comes from the part of speech. Symbols and spaces are not output. `partition` is true.

UniDic 3.1's kanaBase keeps a sound change that unidic-lite's drops, so `form_reading` differs too: in ペンを一本ください, 一本 is いっ + ぽん, where unidic-lite gives いち + ほん.

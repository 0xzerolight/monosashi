"""The pinned JMdict/JMnedict snapshot: fetch, index, look up.

Gold entry ids are JMdict ``ent_seq`` values from the snapshot pinned in
``data/sources.toml``. The archives are downloaded once into the cache
(``$MONOSASHI_CACHE``, default ``~/.cache/monosashi``) and turned into a small
read-only SQLite index that the validator, the candidate sheet and the scorer
share.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tarfile
import tomllib
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from monosashi.kana import has_kanji, has_katakana_letter, to_hiragana, widen

SCHEMA_VERSION = "4"
CACHE_ENV = "MONOSASHI_CACHE"

JMDICT = "jmdict"
JMNEDICT = "jmnedict"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    override = os.environ.get(CACHE_ENV)
    return Path(override) if override else Path.home() / ".cache" / "monosashi"


@dataclass(frozen=True, slots=True)
class Pin:
    key: str
    version: str
    dict_date: str
    url: str
    sha256: str
    license: str
    attribution: str


def load_pins(path: Path | None = None) -> dict[str, Pin]:
    source = path or repo_root() / "data" / "sources.toml"
    with source.open("rb") as fh:
        data = tomllib.load(fh)
    pins: dict[str, Pin] = {}
    for key, raw in data.get("dictionaries", {}).items():
        pins[key] = Pin(
            key=key,
            version=str(raw["version"]),
            dict_date=str(raw["dict_date"]),
            url=str(raw["url"]),
            sha256=str(raw["sha256"]),
            license=str(raw["license"]),
            attribution=str(raw["attribution"]),
        )
    return pins


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


DOWNLOAD_TIMEOUT_S = 60


class Pinned(Protocol):
    """Anything pinned in ``data/sources.toml``: a URL and the sha256 of what it serves."""

    @property
    def url(self) -> str: ...

    @property
    def sha256(self) -> str: ...


def fetch(pin: Pinned, cache: Path) -> Path:
    """The pinned archive in the cache, downloaded if missing; sha256-checked either way.

    A download is checked before it takes the archive's name, so a bad
    download never sits in the cache looking like the real thing.
    """
    downloads = cache / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / Path(urllib.parse.unquote(pin.url.rsplit("/", 1)[1])).name
    if not archive.exists():
        partial = archive.with_suffix(archive.suffix + ".part")
        with (
            urllib.request.urlopen(pin.url, timeout=DOWNLOAD_TIMEOUT_S) as response,
            partial.open("wb") as out,
        ):
            while block := response.read(1 << 20):
                out.write(block)
        actual = _sha256(partial)
        if actual != pin.sha256:
            partial.unlink()
            raise ValueError(f"{pin.url}: sha256 {actual} does not match the pin {pin.sha256}")
        partial.rename(archive)
        return archive
    actual = _sha256(archive)
    if actual != pin.sha256:
        raise ValueError(
            f"{archive}: sha256 {actual} does not match the pin {pin.sha256}; delete it to re-fetch"
        )
    return archive


def extract_json(archive: Path, dest_dir: Path) -> Path:
    """The single JSON member of a jmdict-simplified archive, written into ``dest_dir``.

    Members are streamed by name only, so a hostile path inside the archive
    cannot escape ``dest_dir``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".json")]
        if len(members) != 1:
            raise ValueError(f"{archive.name}: expected one JSON member, found {len(members)}")
        out = dest_dir / Path(members[0].name).name
        stream = tar.extractfile(members[0])
        if stream is None:
            raise ValueError(f"{archive.name}: cannot read {members[0].name}")
        with stream, out.open("wb") as fh:
            while block := stream.read(1 << 20):
                fh.write(block)
    return out


def index_path(pins: Mapping[str, Pin], cache: Path) -> Path:
    """One index per (JMdict, JMnedict, schema) combination, so bumping either pin rebuilds it."""
    names = pins[JMNEDICT].version if JMNEDICT in pins else "none"
    return cache / f"jmdict-{pins[JMDICT].version}-jmnedict-{names}-schema{SCHEMA_VERSION}.sqlite"


def ensure_index(cache: Path | None = None, pins: Mapping[str, Pin] | None = None) -> Path:
    """Path to the pinned index, fetching and building it on first use."""
    cache = cache or cache_dir()
    pins = pins or load_pins()
    out = index_path(pins, cache)
    if out.exists():
        return out
    extracted = cache / "extracted" / pins[JMDICT].version
    jmdict_json = extract_json(fetch(pins[JMDICT], cache), extracted)
    jmnedict_json = extract_json(fetch(pins[JMNEDICT], cache), extracted) if JMNEDICT in pins else None
    meta = {f"{key}_version": pin.version for key, pin in pins.items()}
    meta |= {f"{key}_dict_date": pin.dict_date for key, pin in pins.items()}
    build_index(jmdict_json, jmnedict_json, out, meta)
    return out


# JMdict and JMnedict share id ranges (7,303 ids collide in the pinned
# snapshot), so every table is keyed by (source, seq).
_DDL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entry(
    source TEXT NOT NULL,
    seq INTEGER NOT NULL,
    common INTEGER NOT NULL,
    pos TEXT NOT NULL,
    misc TEXT NOT NULL,
    gloss TEXT NOT NULL,
    PRIMARY KEY (source, seq)
);
CREATE TABLE spelling(source TEXT NOT NULL, seq INTEGER NOT NULL, text TEXT NOT NULL, kind TEXT NOT NULL,
                      tags TEXT NOT NULL, common INTEGER NOT NULL);
CREATE TABLE pair(source TEXT NOT NULL, seq INTEGER NOT NULL, spelling TEXT NOT NULL, reading TEXT NOT NULL);
CREATE TABLE sense(source TEXT NOT NULL, seq INTEGER NOT NULL, idx INTEGER NOT NULL, pos TEXT NOT NULL,
                   misc TEXT NOT NULL, glosses TEXT NOT NULL, kanji TEXT NOT NULL, kana TEXT NOT NULL,
                   info TEXT NOT NULL);
"""
_INDEXES = """
CREATE INDEX spelling_text ON spelling(text);
CREATE INDEX spelling_key ON spelling(source, seq);
CREATE INDEX pair_key ON pair(source, seq);
CREATE INDEX sense_key ON sense(source, seq, idx);
"""

_Row = tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Sense:
    """One JMdict sense, or one JMnedict translation (its name types as ``pos``).

    ``kanji`` and ``kana`` are the spellings the sense is restricted to
    (``appliesToKanji``, ``appliesToKana``); empty means unrestricted. ``info``
    holds JMdict's notes on the sense ("as ...なければならない").
    """

    pos: tuple[str, ...]
    misc: tuple[str, ...]
    glosses: tuple[str, ...]
    kanji: tuple[str, ...]
    kana: tuple[str, ...]
    info: tuple[str, ...] = ()


def _restriction(applies: list[str]) -> tuple[str, ...]:
    return () if applies == ["*"] else tuple(applies)


def _senses(word: Mapping[str, Any], source: str) -> list[Sense]:
    if source == JMDICT:
        return [
            Sense(
                pos=tuple(s.get("partOfSpeech", [])),
                # Dialect tags (ksb) ride with misc, so lookup and the senses show them (SPEC.md §6 kansai).
                misc=tuple(s.get("misc", [])) + tuple(s.get("dialect", [])),
                glosses=tuple(g["text"] for g in s.get("gloss", [])),
                kanji=_restriction(s.get("appliesToKanji", ["*"])),
                kana=_restriction(s.get("appliesToKana", ["*"])),
                info=tuple(s.get("info", [])),
            )
            for s in word.get("sense", [])
        ]
    return [
        Sense(tuple(tr.get("type", [])), (), tuple(t["text"] for t in tr.get("translation", [])), (), ())
        for tr in word.get("translation", [])
    ]


def _entry_rows(word: Mapping[str, Any], source: str) -> tuple[_Row, list[_Row], list[_Row], list[_Row]]:
    seq = int(word["id"])
    key = (source, seq)
    kanji = list(word.get("kanji", []))
    kana = list(word.get("kana", []))
    senses = _senses(word, source)
    pos = sorted({p for s in senses for p in s.pos})
    misc = sorted({m for s in senses for m in s.misc})
    glosses = senses[0].glosses[:3] if senses else ()  # the short display gloss
    common = any(bool(k.get("common")) for k in kanji + kana)
    entry: _Row = (*key, int(common), " ".join(pos), " ".join(misc), "; ".join(glosses))
    # Tags never hold a space; glosses, spellings and notes may, so they are stored as JSON lists.
    sense_rows: list[_Row] = [
        (*key, i, " ".join(s.pos), " ".join(s.misc), *map(_json, (s.glosses, s.kanji, s.kana, s.info)))
        for i, s in enumerate(senses)
    ]
    spellings: list[_Row] = [
        (*key, k["text"], kind, " ".join(k.get("tags", [])), int(bool(k.get("common"))))
        for kind, group in (("kanji", kanji), ("kana", kana))
        for k in group
    ]
    kanji_texts = [k["text"] for k in kanji]
    pairs: list[_Row] = []
    for k in kana:
        pairs.append((*key, k["text"], k["text"]))
        if "sk" in k.get("tags", []):
            # A search-only kana spelling (すごーい) is how the word may be written,
            # not a reading of its kanji forms.
            continue
        applies = k.get("appliesToKanji", ["*"])
        targets = kanji_texts if applies == ["*"] else [t for t in applies if t in kanji_texts]
        pairs += [(*key, t, k["text"]) for t in targets]
    return entry, spellings, pairs, sense_rows


def _json(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _words(path: Path) -> list[Mapping[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return list(data["words"])


def build_index(jmdict_json: Path, jmnedict_json: Path | None, out: Path, meta: Mapping[str, str]) -> None:
    """Write the SQLite index for one JMdict (+ optional JMnedict) snapshot."""
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    conn = sqlite3.connect(partial)
    try:
        conn.executescript(_DDL)
        sources: list[tuple[Path, str]] = [(jmdict_json, JMDICT)]
        if jmnedict_json is not None:
            sources.append((jmnedict_json, JMNEDICT))
        for path, source in sources:
            entries, spellings, pairs, senses = [], [], [], []
            for word in _words(path):
                e, s, p, n = _entry_rows(word, source)
                entries.append(e)
                spellings += s
                pairs += p
                senses += n
            conn.executemany("INSERT INTO entry VALUES (?, ?, ?, ?, ?, ?)", entries)
            conn.executemany("INSERT INTO spelling VALUES (?, ?, ?, ?, ?, ?)", spellings)
            conn.executemany("INSERT INTO pair VALUES (?, ?, ?, ?)", pairs)
            conn.executemany("INSERT INTO sense VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", senses)
        conn.executescript(_INDEXES)
        conn.executemany(
            "INSERT INTO meta VALUES (?, ?)", sorted({**meta, "schema_version": SCHEMA_VERSION}.items())
        )
        conn.commit()
    finally:
        conn.close()
    partial.rename(out)


@dataclass(frozen=True, slots=True)
class Entry:
    seq: int
    source: str
    common: bool
    pos: tuple[str, ...]
    misc: tuple[str, ...]
    gloss: str  # the short display gloss: the first sense's first three glosses
    kanji: tuple[str, ...]
    kana: tuple[str, ...]
    pairs: frozenset[tuple[str, str]]
    search_only: frozenset[str] = frozenset()  # spellings tagged sK / sk
    common_spellings: frozenset[str] = frozenset()  # spellings JMdict marks common
    spelling_tags: frozenset[tuple[str, str]] = frozenset()  # (spelling, tag): iK, io, ok, rK, sK, ...
    senses: tuple[Sense, ...] = ()  # every sense, in JMdict order

    @property
    def spellings(self) -> frozenset[str]:
        return frozenset(self.kanji + self.kana)

    @property
    def is_name(self) -> bool:
        return self.source == JMNEDICT

    def spelling_key(self, text: str) -> str | None:
        """The JMdict spelling ``text`` stands for, also matching ASCII to fullwidth (3つ -> ３つ)."""
        spellings = self.spellings
        if text in spellings:
            return text
        wide = widen(text)
        return wide if wide in spellings else None

    def has_spelling(self, text: str) -> bool:
        return self.spelling_key(text) is not None

    def readings_of(self, spelling: str) -> frozenset[str]:
        """Hiragana readings JMdict allows for ``spelling`` (empty if it is not a spelling).

        JMdict separates the letters of some katakana readings with ・ (シー・ディー);
        a gold reading has no ・, so it is dropped here.
        """
        key = self.spelling_key(spelling)
        return frozenset(to_hiragana(r).replace("・", "") for s, r in self.pairs if s == key)

    def preferred_form(self, spelling: str) -> str:
        """The gold form for a surface spelled ``spelling`` (SPEC.md §5).

        A spelling is its own form, except a search-only one (すご〜い, スゴい), whose
        form is the entry's standard spelling in the same script: kana for kana,
        kanji for kanji, katakana for katakana when one exists.
        """
        key = self.spelling_key(spelling) or spelling
        if key not in self.search_only:
            return spelling
        return self.standard_spelling(key)

    def standard_spelling(self, surface: str) -> str:
        """The entry's first standard (not search-only) spelling in the script of
        ``surface``: kanji for kanji, kana for kana, katakana for katakana when one
        exists (SPEC.md §5); ``surface`` itself when there is none in that script
        (飛んでもない). The form of a search-only spelling."""
        return (self._standard_in_script(surface) or [surface])[0]

    def standard_spellings(self, surface: str) -> list[str]:
        """The forms an unlisted spelling may take (SPEC.md §5): the entry's standard
        spellings in the script of ``surface``, in JMdict's order, or its standard kana
        spellings when it has none there (不可ない: いけない, whose only kanji
        spelling is search-only)."""
        kana = [s for s in self.kana if s not in self.search_only]
        return self._standard_in_script(surface) or kana or [surface]

    def _standard_in_script(self, surface: str) -> list[str]:
        pool = self.kanji if has_kanji(surface) else self.kana
        standard = [s for s in pool if s not in self.search_only]
        katakana = has_katakana_letter(surface)
        return [s for s in standard if has_katakana_letter(s) == katakana] or standard


class Dictionary:
    """Read-only access to a built index."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        self.meta = dict(self._conn.execute("SELECT key, value FROM meta").fetchall())
        self._entry_cached = lru_cache(maxsize=65536)(self._entry_uncached)

    def close(self) -> None:
        self._conn.close()

    def entry(self, seq: int, source: str = JMDICT) -> Entry | None:
        """One entry by id. Ids are only unique within a source (JMdict or JMnedict)."""
        return self._entry_cached(source, seq)

    def _entry_uncached(self, source: str, seq: int) -> Entry | None:
        key = (source, seq)
        row = self._conn.execute(
            "SELECT common, pos, misc, gloss FROM entry WHERE source = ? AND seq = ?", key
        ).fetchone()
        if row is None:
            return None
        kanji: list[str] = []
        kana: list[str] = []
        search_only: set[str] = set()
        common: set[str] = set()
        spelling_tags: set[tuple[str, str]] = set()
        for text, kind, tags, is_common in self._conn.execute(
            "SELECT text, kind, tags, common FROM spelling WHERE source = ? AND seq = ? ORDER BY rowid", key
        ):
            (kanji if kind == "kanji" else kana).append(text)
            if {"sK", "sk"} & set(tags.split()):
                search_only.add(text)
            if is_common:
                common.add(text)
            spelling_tags.update((text, tag) for tag in tags.split())
        pairs = frozenset(
            self._conn.execute(
                "SELECT spelling, reading FROM pair WHERE source = ? AND seq = ?", key
            ).fetchall()
        )
        senses = tuple(
            Sense(
                pos=tuple(pos.split()),
                misc=tuple(misc.split()),
                glosses=tuple(json.loads(glosses)),
                kanji=tuple(json.loads(only_kanji)),
                kana=tuple(json.loads(only_kana)),
                info=tuple(json.loads(info)),
            )
            for pos, misc, glosses, only_kanji, only_kana, info in self._conn.execute(
                "SELECT pos, misc, glosses, kanji, kana, info FROM sense WHERE source = ? AND seq = ? ORDER BY idx",
                key,
            )
        )
        return Entry(
            seq=seq,
            source=source,
            common=bool(row[0]),
            pos=tuple(row[1].split()),
            misc=tuple(row[2].split()),
            gloss=row[3],
            kanji=tuple(kanji),
            kana=tuple(kana),
            pairs=pairs,
            search_only=frozenset(search_only),
            common_spellings=frozenset(common),
            spelling_tags=frozenset(spelling_tags),
            senses=senses,
        )

    def lookup(self, text: str, source: str | None = None) -> list[Entry]:
        """Entries with ``text`` among their spellings: JMdict before JMnedict, common first."""
        keys = self._conn.execute(
            "SELECT DISTINCT source, seq FROM spelling WHERE text = ?", (text,)
        ).fetchall()
        entries = [e for e in (self.entry(seq, src) for src, seq in keys) if e is not None]
        if source is not None:
            entries = [e for e in entries if e.source == source]
        return sorted(entries, key=lambda e: (e.source != JMDICT, not e.common, e.seq))

    def common_readings(self, spelling: str) -> frozenset[str]:
        """Readings of a kanji spelling, across JMdict entries, where JMdict marks both common.

        彼 read あれ is not one: the あれ entry marks 彼 as a rare spelling.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT p.reading FROM pair p JOIN spelling s"
            " ON s.source = p.source AND s.seq = p.seq AND s.text = p.reading AND s.kind = 'kana'"
            " JOIN spelling k ON k.source = p.source AND k.seq = p.seq AND k.text = p.spelling AND k.kind = 'kanji'"
            " WHERE p.spelling = ? AND p.source = ? AND p.reading != p.spelling AND s.common = 1 AND k.common = 1",
            (spelling, JMDICT),
        ).fetchall()
        return frozenset(to_hiragana(r).replace("・", "") for (r,) in rows)

    def spells_on(self, prefix: str, source: str = JMDICT) -> bool:
        """Whether a longer spelling starts with ``prefix`` (欲し, the start of 欲しい)."""
        row = self._conn.execute(
            "SELECT 1 FROM spelling WHERE text > ? AND text < ? AND source = ? LIMIT 1",
            (prefix, prefix + "\U0010ffff", source),
        ).fetchone()
        return row is not None

    def exists(self, seq: int, source: str = JMDICT) -> bool:
        return self.entry(seq, source) is not None

    def entries(self, seqs: Iterable[int], source: str = JMDICT) -> Iterator[Entry]:
        for seq in seqs:
            entry = self.entry(seq, source)
            if entry is not None:
                yield entry

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from monosashi.jmdict import JMDICT, JMNEDICT, Dictionary, Sense, extract_json, load_pins


def test_lookup_returns_entries_with_pairs(dictionary: Dictionary) -> None:
    (entry,) = dictionary.lookup("一人暮らし")
    assert entry.seq == 1613340 and entry.source == JMDICT and entry.common
    assert "ひとり暮らし" in entry.spellings  # a search-only spelling is still a spelling
    assert entry.readings_of("一人暮らし") == {"ひとりぐらし"}


def test_heteronyms_are_separate_entries(dictionary: Dictionary) -> None:
    readings = {r for e in dictionary.lookup("一日") for r in e.readings_of("一日")}
    assert {"いちにち", "ついたち"} <= readings


def test_common_readings_need_a_common_spelling_and_reading(dictionary: Dictionary) -> None:
    assert dictionary.common_readings("方") == {"かた", "ほう"}  # not さま, where 方 is a rare spelling
    assert dictionary.common_readings("彼") == {"かれ"}  # not あれ, for the same reason


def test_spells_on_finds_only_longer_spellings(dictionary: Dictionary) -> None:
    assert dictionary.spells_on("欲し")  # 欲しい
    assert not dictionary.spells_on("欲しい")
    assert not dictionary.spells_on("私も")


def test_names_live_in_their_own_source(dictionary: Dictionary) -> None:
    names = dictionary.lookup("田中", JMNEDICT)
    assert [e.seq for e in names] == list(range(5543705, 5543715))  # the fixture keeps its ten person entries
    assert dictionary.entry(5543705, JMNEDICT) is not None
    assert dictionary.entry(5543705) is None  # the same id is not a JMdict entry


def test_katakana_spelling_reads_as_hiragana(dictionary: Dictionary) -> None:
    entry = dictionary.entry(1374550)
    assert entry is not None
    assert entry.readings_of("スゴイ") == {"すごい"}
    assert entry.readings_of("凄い") == {"すごい"}


def test_readings_drop_the_letter_separator(dictionary: Dictionary) -> None:
    entry = dictionary.entry(1059430)
    assert entry is not None and entry.readings_of("ＣＤ") == {"しーでぃー"}


def test_ascii_matches_fullwidth_spellings(dictionary: Dictionary) -> None:
    entry = dictionary.entry(1299740)
    assert entry is not None
    assert entry.has_spelling("3つ") and entry.has_spelling("３つ")
    assert entry.readings_of("3つ") == entry.readings_of("３つ") == {"みっつ", "みつ"}
    assert entry.preferred_form("3つ") == "3つ"  # ASCII is not search-only; it stays


def test_search_only_spellings_prefer_the_standard_one(dictionary: Dictionary) -> None:
    sugoi = dictionary.entry(1374550)
    assert sugoi is not None
    assert {"すご〜い", "すごーい", "スゴい"} <= sugoi.search_only
    assert sugoi.preferred_form("すご〜い") == "すごい"
    assert sugoi.preferred_form("スゴーイ") == "スゴイ"  # katakana keeps katakana
    assert sugoi.preferred_form("凄い") == "凄い"
    sugee = dictionary.entry(2722660)
    assert sugee is not None and sugee.preferred_form("すげえ") == "すげー"


def test_entry_keeps_every_sense(dictionary: Dictionary) -> None:
    naranai = dictionary.entry(2083990)
    assert naranai is not None and len(naranai.senses) > 2
    assert any("must" in gloss for sense in naranai.senses for gloss in sense.glosses)
    assert naranai.senses[0] == Sense(
        pos=("exp",), misc=(), glosses=("cannot help (feeling)", "unbearably", "awfully", "irresistibly"),
        kanji=(), kana=(), info=("as ...てならない",),
    )  # fmt: skip
    assert naranai.senses[4].misc == ("dated",)
    assert naranai.gloss == "cannot help (feeling); unbearably; awfully"  # the short display gloss stays
    tanaka = dictionary.entry(5543705, JMNEDICT)
    assert tanaka is not None
    assert tanaka.senses == (
        Sense(pos=("surname", "place"), misc=(), glosses=("Tanaka",), kanji=(), kana=()),
    )


def test_sense_restrictions(dictionary: Dictionary) -> None:
    hitori = dictionary.entry(1576150)  # 一人: only ひとり means "alone"
    assert hitori is not None
    assert (hitori.senses[0].kanji, hitori.senses[0].kana) == ((), ())  # unrestricted
    assert hitori.senses[1].kana == ("ひとり",) and hitori.senses[1].glosses[0] == "being alone"
    hane = dictionary.entry(1171680)  # 羽 / 羽根: the blade sense is 羽根 only
    assert hane is not None and hane.senses[2].kanji == ("羽根",)


def test_pins_carry_a_sha256_and_license() -> None:
    pins = load_pins()
    assert set(pins) == {JMDICT, JMNEDICT}
    for pin in pins.values():
        assert len(pin.sha256) == 64 and pin.license == "CC-BY-SA-4.0"


def test_extract_json_ignores_member_paths(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tgz"
    payload = b'{"words": []}'
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../../escape/jmdict.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    out = extract_json(archive, tmp_path / "dest")
    assert out == tmp_path / "dest" / "jmdict.json"
    assert out.read_bytes() == payload


def test_extract_json_rejects_multiple_members(tmp_path: Path) -> None:
    archive = tmp_path / "two.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in ("a.json", "b.json"):
            info = tarfile.TarInfo(name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(ValueError, match="one JSON member"):
        extract_json(archive, tmp_path / "dest")

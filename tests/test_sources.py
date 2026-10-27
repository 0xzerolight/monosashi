"""Corpus readers and the Sentence schema, on small hand-built archives."""

from __future__ import annotations

import bz2
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from monosashi.schema import SchemaError, Source
from monosashi.sources import (
    Hint,
    Sentence,
    SourcePin,
    aozora,
    dump_sentences,
    load_sentences,
    load_source_pins,
    sentence_from_dict,
    sentence_problems,
    tatoeba,
    ud_gsd,
)


def _pin(**extra: str) -> SourcePin:
    return SourcePin("k", "https://example.org/x", "0" * 64, "public-domain", "Someone『Work』", "v1", extra)


def _sentence(**overrides: object) -> Sentence:
    fields: dict[str, object] = {
        "id": "s-1",
        "text": "食べた。",
        "source": Source("test", "1", "CC-BY-SA-4.0", "monosashi tests"),
        "register": "conversation",
        "slice": "open",
    }
    fields.update(overrides)
    return Sentence(**fields)  # type: ignore[arg-type]


def test_sentences_round_trip(tmp_path: Path) -> None:
    s = _sentence(original={"split": ["食べた"]}, hints=(Hint("inflection-chain", 0, 3),))
    path = tmp_path / "s.jsonl"
    assert dump_sentences(path, [s]) == 1
    assert list(load_sentences(path)) == [s]


def test_sentence_parsing_rejects_unknown_fields() -> None:
    with pytest.raises(SchemaError, match="unknown field"):
        sentence_from_dict(
            {"id": "x", "text": "a", "source": {}, "register": "formal", "slice": "open", "units": []}
        )


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"text": "ｶﾞﾝﾊﾞﾚ"}, "not normalized"),
        ({"register": "speech"}, "unknown register"),
        ({"slice": "gold"}, "unknown slice"),
        ({"source": Source("t", "1", "GPL-3.0", "x")}, "allowlist"),
        ({"hints": (Hint("nonsense", 0, 1),)}, "unknown category"),
        ({"hints": (Hint("compound", 2, 9),)}, "out of bounds"),
    ],
)
def test_sentence_problems(overrides: dict[str, object], problem: str) -> None:
    assert any(problem in p for p in sentence_problems(_sentence(**overrides)))
    assert sentence_problems(_sentence()) == []


def test_load_source_pins_keeps_group_fields(tmp_path: Path) -> None:
    toml = tmp_path / "sources.toml"
    toml.write_text(
        '[aozora.card1]\nurl = "u"\nsha256 = "s"\nlicense = "public-domain"\nattribution = "a"\n'
        'version = "v"\ncard = "1"\n',
        encoding="utf-8",
    )
    pin = load_source_pins("aozora", toml)["card1"]
    assert (pin.url, pin.version, dict(pin.extra)) == ("u", "v", {"card": "1"})


def test_aozora_pins_are_new_orthography_editions() -> None:
    # Each pin records the 文字遣い種別 of Aozora's index; only 新字新仮名 editions are used.
    pins = load_source_pins("aozora")
    assert pins and {p.key: p.extra.get("orthography") for p in pins.values()} == dict.fromkeys(
        pins, "新字新仮名"
    )


def _tar_bz2(path: Path, name: str, content: str) -> None:
    data = content.encode("utf-8")
    with tarfile.open(path, "w:bz2") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def test_tatoeba_keeps_native_owned_sentences(tmp_path: Path) -> None:
    users = tmp_path / "user_languages.tar.bz2"
    _tar_bz2(users, "user_languages.csv", "jpn\t5\tkana\t\njpn\t3\tlearner\t\neng\t5\tkana\t\n")
    sentences = tmp_path / "jpn_sentences_detailed.tsv.bz2"
    rows = (
        "1\tjpn\t食べた。\tkana\t\\N\t\\N\n2\tjpn\t寝た。\tlearner\t\\N\t\\N\n3\tjpn\tｶﾞﾝﾊﾞﾚ\tkana\t\\N\t\\N\n"
    )
    sentences.write_bytes(bz2.compress(rows.encode("utf-8")))
    natives = tatoeba.native_speakers(users)
    assert natives == {"kana"}
    out = list(tatoeba.read_sentences(sentences, natives, _pin()))
    assert [(s.id, s.text) for s in out] == [("tat-1", "食べた。"), ("tat-3", "ガンバレ")]
    assert out[0].source.url == "https://tatoeba.org/en/sentences/show/1"
    assert (out[0].register, out[0].slice, out[0].source.license) == ("conversation", "open", "CC-BY-2.0-FR")


AOZORA_TEXT = "\r\n".join(
    [
        "走れメロス",
        "太宰治",
        "",
        "-------------------------------------------------------",
        "【テキスト中に現れる記号について】",
        "《》：ルビ",
        "-------------------------------------------------------",
        "",
        "　メロスは激怒《げきど》した。必ず、かの｜邪智暴虐《じゃちぼうぎゃく》の王を除かなければならぬと決意した。",
        "「王様は、人を殺します。」と老爺は答えた。",
        "　所謂「神憑り」で働いた骨休めをかねて、旅に出た。",
        "「ハハハ……、ご心配",
        "　※［＃「てへん＋去」、第4水準2-13-28］いた。",
        "［＃５字下げ］一［＃「一」は中見出し］",
        "",
        "底本：「太宰治全集3」ちくま文庫、筑摩書房",
        "「これは奥付です。」",
    ]
)


def test_aozora_strips_markup_and_splits_dialogue(tmp_path: Path) -> None:
    archive = tmp_path / "1567_ruby.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("hashire_merosu.txt", AOZORA_TEXT.encode("cp932"))
    pin = _pin(card="1567", card_url="https://www.aozora.gr.jp/cards/000035/card1567.html")
    texts = [s.text for s in aozora.read_work(archive, pin)]
    assert texts == [
        "メロスは激怒した。",
        "必ず、かの邪智暴虐の王を除かなければならぬと決意した。",
        "王様は、人を殺します。",  # the quotative tail と老爺は答えた。 is dropped
        "所謂「神憑り」で働いた骨休めをかねて、旅に出た。",  # a quoted term stays in its sentence
        "一",  # 「ハハハ……、ご心配 has an unclosed bracket and is dropped
    ]
    first = next(aozora.read_work(archive, pin))
    assert first.id == "aoz-1567-9-0"
    assert (first.register, first.source.license, first.source.attribution) == (
        "literature",
        "public-domain",
        "Someone『Work』",
    )


def test_ud_gsd_reads_sentence_text(tmp_path: Path) -> None:
    path = tmp_path / "ja_gsd-ud-test.conllu"
    path.write_text(
        "# sent_id = test-s1\n# text = 日本語の文。\n1\t日本\t_\n\n# sent_id = test-s2\n# text = ２文目\n1\t２\t_\n",
        encoding="utf-8",
    )
    out = list(ud_gsd.read_conllu(path, _pin(repo_url="https://github.com/x")))
    assert [(s.id, s.text, s.register) for s in out] == [
        ("gsd-test-s1", "日本語の文。", "formal"),
        ("gsd-test-s2", "２文目", "formal"),
    ]

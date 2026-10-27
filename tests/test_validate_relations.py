"""How the validator relates a unit's surface to its form (SPEC.md §4-§5).

Each case is a one-sentence record and the exact set of rules it must trip;
an empty set means it is a correct label.
"""

from __future__ import annotations

from typing import Any

import pytest

from helpers import record
from monosashi.jmdict import Dictionary
from monosashi.kana import to_hiragana as _hira
from monosashi.schema import record_from_dict
from monosashi.validate import validate_record

Unit = dict[str, Any]


def _w(surface: str, entries: list[int], form: str, reading: str, form_reading: str, **extra: Any) -> Unit:
    return {
        "surface": surface,
        "kind": "word",
        "entries": entries,
        "form": form,
        "reading": reading,
        "form_reading": form_reading,
        **extra,
    }


def _record(text: str, units: list[Unit]) -> dict[str, Any]:
    """Offsets computed from the units; a ``{"symbol": ...}`` item is text outside any unit."""
    pos, out = 0, []
    for unit in units:
        if "symbol" in unit:
            pos += len(unit["symbol"])
            continue
        out.append({"start": pos, "end": pos + len(unit["surface"]), **unit})
        pos += len(unit["surface"])
    assert pos == len(text)
    return record(text, out)


def _rules(data: dict[str, Any], dictionary: Dictionary) -> set[str]:
    return {issue.rule for issue in validate_record(record_from_dict(data), dictionary)}


def _seq(dictionary: Dictionary, spelling: str, pos: str | None = None) -> int:
    return next(e.seq for e in dictionary.lookup(spelling) if pos is None or pos in e.pos)


CASES: dict[str, tuple[str, Any, set[str]]] = {
    # A surface that is a spelling of the entry is its own form.
    "spelling variant": (
        "往く",
        lambda d: [_w("往く", [1578850], "行く", "いく", "いく")],
        {"form-orthography"},
    ),
    "kanji surface": (
        "凄い",
        lambda d: [_w("凄い", [1374550], "すごい", "すごい", "すごい")],
        {"form-orthography"},
    ),
    "katakana surface": ("スゴイ", lambda d: [_w("スゴイ", [1374550], "スゴイ", "すごい", "すごい")], set()),
    # Search-only spellings take the standard spelling as their form.
    "stretched, standard form": (
        "すご〜い",
        lambda d: [_w("すご〜い", [1374550], "すごい", "すご〜い", "すごい")],
        set(),
    ),
    "stretched, search-only form": (
        "すご〜い",
        lambda d: [_w("すご〜い", [1374550], "すご〜い", "すご〜い", "すご〜い")],
        {"form-orthography"},
    ),
    # An inflected unit records its chain, including katakana, stretched and exp-only units.
    "exp-only expression, no chain": (
        "かもしれなかった",
        lambda d: [
            _w(
                "かもしれなかった",
                [1002970],
                "かもしれない",
                "かもしれなかった",
                "かもしれない",
                kind="expression",
            )
        ],
        {"chain-missing"},
    ),
    "exp-only expression, chain": (
        "かもしれなかった",
        lambda d: [
            _w(
                "かもしれなかった",
                [1002970],
                "かもしれない",
                "かもしれなかった",
                "かもしれない",
                kind="expression",
                chain=["-た"],
            )
        ],
        set(),
    ),
    "katakana verb, no chain": (
        "ヤった",
        lambda d: [_w("ヤった", [_seq(d, "やる", "v5r")], "やる", "やった", "やる")],
        {"chain-missing"},
    ),
    "katakana verb, chain": (
        "ヤった",
        lambda d: [_w("ヤった", [_seq(d, "やる", "v5r")], "やる", "やった", "やる", chain=["-た"])],
        set(),
    ),
    "stretched inflection": (
        "すご〜かった",
        lambda d: [_w("すご〜かった", [1374550], "すごい", "すご〜かった", "すごい", chain=["-た"])],
        set(),
    ),
    # Noun + する is one unit, bare or inflected.
    "bare noun + する": (
        "勉強する",
        lambda d: [_w("勉強する", [1512670], "勉強", "べんきょうする", "べんきょう")],
        set(),
    ),
    "noun | する split": (
        "勉強する",
        lambda d: [
            _w("勉強", [1512670], "勉強", "べんきょう", "べんきょう"),
            {"surface": "する", "kind": "auxiliary"},
        ],
        {"chain-maximal"},
    ),
    # Alphanumerics: fullwidth as in JMdict, or ASCII kept from the source.
    "fullwidth letters": (
        "ＣＤ",
        lambda d: [_w("ＣＤ", [1059430], "ＣＤ", "しーでぃー", "しーでぃー")],
        set(),
    ),
    "fullwidth digit": ("３つ", lambda d: [_w("３つ", [1299740], "３つ", "みっつ", "みっつ")], set()),
    "ASCII digit": ("3つ", lambda d: [_w("3つ", [1299740], "3つ", "みっつ", "みっつ")], set()),
    # Counters: the whole entry when JMdict has one, otherwise the counter.
    "counter with own entry": (
        "三本",
        lambda d: [_w("三本", [1301640], "三本", "さんぼん", "さんぼん", split_points=[1])],
        set(),
    ),
    "counter without own entry": (
        "二十本",
        lambda d: [_w("二十本", [1522150], "本", "にじゅっぽん", "ほん", split_points=[2])],
        set(),
    ),
    # 三は is a number and a particle: a kana "counter" other than つ relates nothing.
    "number + particle as a counter": (
        "三は",
        lambda d: [
            _w("三は", [next(e.seq for e in d.lookup("は") if "prt" not in e.pos)], "は", "さんは", "は")
        ],
        {"form-relation"},
    ),
    # Reading and form_reading must agree when nothing inflects.
    "heteronym mismatch": (
        "方",
        lambda d: [_w("方", [1516930], "方", "かた", "ほう")],
        {"reading-form-reading"},
    ),
    # Function units are not chain-checked.
    "auxiliary with a form": (
        "しまった",
        lambda d: [{"surface": "しまった", "kind": "auxiliary", "form": "しまう"}],
        set(),
    ),
    # A lone 〜 marking a range stands outside any unit.
    "range tilde": (
        "今日〜明日",
        lambda d: [
            _w("今日", [1579110], "今日", "きょう", "きょう"),
            {"symbol": "〜"},
            _w("明日", [_seq(d, "明日")], "明日", "あした", "あした"),
        ],
        set(),
    ),
    # A search-only kanji spelling that inflects: the form is the standard spelling.
    "search-only inflection": (
        "つき合った",
        lambda d: [_w("つき合った", [1597790], "付き合う", "つきあった", "つきあう", chain=["-た"])],
        set(),
    ),
    "search-only inflection, raw form": (
        "つき合った",
        lambda d: [_w("つき合った", [1597790], "つき合う", "つきあった", "つきあう", chain=["-た"])],
        {"form-orthography"},
    ),
    "search-only inflection, no chain": (
        "つき合った",
        lambda d: [_w("つき合った", [1597790], "付き合う", "つきあった", "つきあう")],
        {"chain-missing"},
    ),
    # Vowel stretches keep the entry and the standard form.
    **{
        f"stretch {surface}": (
            surface,
            lambda d, s=surface, e=seq, f=form, k=kind: [_w(s, [e], f, _hira(s), f, kind=k)],
            set(),
        )
        for surface, seq, form, kind in [
            ("すごおおい", 1374550, "すごい", "word"),
            ("かわいいいい", 1577200, "かわいい", "word"),
            ("かわいー", 1577200, "かわいい", "word"),
            ("おいしー", 1486650, "おいしい", "word"),
            ("ねえええ", 2029080, "ねえ", "interjection"),
            ("すげーー", 2722660, "すげー", "interjection"),
            ("やだぁぁ", 2710010, "やだ", "interjection"),
        ]
    },
    # An inflected katakana surface keeps katakana when JMdict has it; kana keeps kana.
    "katakana inflection": (
        "スゴかった",
        lambda d: [_w("スゴかった", [1374550], "スゴイ", "すごかった", "すごい", chain=["-た"])],
        set(),
    ),
    "katakana inflection, hiragana form": (
        "スゴかった",
        lambda d: [_w("スゴかった", [1374550], "すごい", "すごかった", "すごい", chain=["-た"])],
        {"form-orthography"},
    ),
    "hiragana inflection, katakana form": (
        "すごかった",
        lambda d: [_w("すごかった", [1374550], "スゴイ", "すごかった", "すごい", chain=["-た"])],
        {"form-orthography"},
    ),
    # A 〜 after kana stretches that word; it cannot be left outside.
    "stretching tilde inside": (
        "あの〜",
        lambda d: [_w("あの〜", [1000430], "あの", "あの〜", "あの", kind="interjection")],
        set(),
    ),
    "stretching tilde outside": (
        "あの〜",
        lambda d: [_w("あの", [1000430], "あの", "あの", "あの", kind="interjection"), {"symbol": "〜"}],
        {"coverage"},
    ),
    # A counter JMdict lists whole is only an advisory when labeled without that entry
    # (SPEC.md §4.4): the validator can't tell whether one of its senses fits.
    "counter split from its entry": (
        "三本",
        lambda d: [_w("三本", [1522150], "本", "さんぼん", "ほん", split_points=[1])],
        set(),
    ),
    # Counters are ctr nouns plus a fixed list; 万, 億 and 兆 count after digits (§4.4).
    "counter after digits": (
        "50万",
        lambda d: [_w("50万", [1584460], "万", "ごじゅうまん", "まん", split_points=[2])],
        set(),
    ),
    "noun after a number": (
        "21得点",
        lambda d: [_w("21得点", [1454590], "得点", "にじゅういちとくてん", "とくてん", split_points=[2])],
        {"form-relation"},
    ),
    "entry that extends a counter": (
        "7日間",
        lambda d: [_w("7日間", [2827650], "日間", "なのかかん", "にっかん")],
        {"form-relation"},
    ),
    "noun after 何": (
        "何世紀",
        lambda d: [_w("何世紀", [1373990], "世紀", "なんせいき", "せいき")],
        {"form-relation"},
    ),
    # A digit reads as it does in context, with any reading of its entry (§4.4).
    "digit read in context": ("４", lambda d: [_w("４", [1579470], "４", "よん", "よん")], set()),
    # Rendaku right after another content unit (§5), but not at the start.
    "rendaku in a split compound": (
        "灯明皿",
        lambda d: [
            _w("灯明", [1448750], "灯明", "とうみょう", "とうみょう"),
            _w("皿", [1299680], "皿", "ざら", "さら"),
        ],
        set(),
    ),
    "rendaku with nothing before": (
        "皿",
        lambda d: [_w("皿", [1299680], "皿", "ざら", "さら")],
        {"reading-form-reading"},
    ),
    # Unlisted spellings relate through the reading when tagged kanji-variant (§5).
    "unlisted okurigana": (
        "塗みれた",
        lambda d: [
            _w(
                "塗みれた",
                [1444280],
                "塗れる",
                "まみれた",
                "まみれる",
                chain=["-た"],
                targets=["kanji-variant"],
            )
        ],
        set(),
    ),
    # The form of an unlisted spelling is the entry's first standard spelling in its script.
    "unlisted spelling takes the first standard spelling": (
        "当てがった",
        lambda d: [
            _w(
                "当てがった",
                [1153470],
                "宛がう",
                "あてがった",
                "あてがう",
                chain=["-た"],
                targets=["kanji-variant"],
            )
        ],
        set(),
    ),
    "unlisted spelling, a later standard spelling": (
        "当てがった",
        lambda d: [
            _w(
                "当てがった",
                [1153470],
                "宛てがう",
                "あてがった",
                "あてがう",
                chain=["-た"],
                targets=["kanji-variant"],
            )
        ],
        {"form-orthography"},
    ),
    # When only a later standard spelling reads as the surface, that one is the form.
    "unlisted spelling, the standard spelling its reading relates to": (
        "カンヴァス",
        lambda d: [
            _w("カンヴァス", [1042130], "カンバス", "かんゔぁす", "かんばす", targets=["kanji-variant"])
        ],
        set(),
    ),
    "unlisted spelling, a standard spelling its reading does not relate to": (
        "カンヴァス",
        lambda d: [
            _w("カンヴァス", [1042130], "キャンバス", "かんゔぁす", "きゃんばす", targets=["kanji-variant"])
        ],
        {"form-orthography", "form-relation"},
    ),
    # An entry with no standard spelling in the surface's script: the kana spelling.
    "unlisted kanji spelling of a kana-only entry": (
        "不可ない",
        lambda d: [_w("不可ない", [1000730], "いけない", "いけない", "いけない", targets=["kanji-variant"])],
        set(),
    ),
    "unlisted kanji spelling of a kana-only entry, form as written": (
        "不可ない",
        lambda d: [_w("不可ない", [1000730], "不可ない", "いけない", "いけない", targets=["kanji-variant"])],
        {"form-spelling"},
    ),
    # A particle dropped from a phrase entry keeps the phrase (§5).
    "dropped particle with a chain": (
        "腹減って",
        lambda d: [
            _w(
                "腹減って",
                [1626200],
                "腹が減る",
                "はらへって",
                "はらがへる",
                chain=["-て"],
                targets=["kanji-variant"],
            )
        ],
        set(),
    ),
    "dropped particle, no chain": (
        "気つける",
        lambda d: [
            _w("気つける", [1591990], "気をつける", "きつける", "きをつける", targets=["kanji-variant"])
        ],
        set(),
    ),
    "dropped particle, untagged": (
        "腹減って",
        lambda d: [_w("腹減って", [1626200], "腹が減る", "はらへって", "はらがへる", chain=["-て"])],
        {"chain-deinflects"},
    ),
    # ヸ reads as ゔぃ, so ヸオロン relates to ヴィオロン through its reading.
    "historical vu kana": (
        "ヸオロン",
        lambda d: [
            _w("ヸオロン", [2500590], "ヴィオロン", "ゔぃおろん", "ゔぃおろん", targets=["archaic-classical"])
        ],
        set(),
    ),
    # An iteration mark is spelled out: いゝえ is いいえ, read いいえ.
    "kana iteration mark": (
        "いゝえ",
        lambda d: [
            {
                "surface": "いゝえ",
                "kind": "interjection",
                "entries": [1583250],
                "form": "いいえ",
                "reading": "いいえ",
                "form_reading": "いいえ",
            }
        ],
        set(),
    ),
    # A name JMdict lists is a word with the name target, and keeps its separator (§4.6).
    "a JMdict-listed name with its separator": (
        "エール・フランス",
        lambda d: [
            _w(
                "エール・フランス",
                [5741000],
                "エールフランス",
                "えーるふらんす",
                "えーるふらんす",
                targets=["name", "katakana"],
            )
        ],
        set(),
    ),
    "unlisted okurigana, untagged": (
        "塗みれた",
        lambda d: [_w("塗みれた", [1444280], "塗れる", "まみれた", "まみれる", chain=["-た"])],
        {"chain-deinflects"},
    ),
    "ヴ for バ": (
        "ヴォイド",
        lambda d: [_w("ヴォイド", [2671580], "ボイド", "ゔぉいど", "ぼいど", targets=["kanji-variant"])],
        set(),
    ),
    "ゆう for いう": (
        "どーゆう",
        lambda d: [_w("どーゆう", [1008920], "どういう", "どーゆう", "どういう", targets=["kanji-variant"])],
        set(),
    ),
    # Emphatic っ is a stretch mark, but only on a unit tagged elongation (§4.8).
    "emphatic inner っ": (
        "ほんっと",
        lambda d: [_w("ほんっと", [1523060], "ほんと", "ほんっと", "ほんと", targets=["elongation"])],
        set(),
    ),
    "emphatic final っ": (
        "写るーっ",
        lambda d: [_w("写るーっ", [1321820], "写る", "うつるーっ", "うつる", targets=["elongation"])],
        set(),
    ),
    **{
        f"emphatic っ run {surface}": (
            surface,
            lambda d, s=surface, e=seq, f=form: [_w(s, [e], f, s, f, targets=["elongation"])],
            set(),
        )
        for surface, seq, form in [
            ("ずっっと", 1006380, "ずっと"),
            ("もっっと", 1012620, "もっと"),
            ("まっったく", 1394800, "まったく"),
        ]
    },
    "っ untagged relates nothing": (
        "まった",
        lambda d: [_w("まった", [1524930], "また", "まった", "また")],
        {"form-relation"},
    ),
    # A ー inside a chain, and a vowel after a kanji, are stretches (§4.8).
    "ー for an -え ending": (
        "気をつけねー",
        lambda d: [
            _w(
                "気をつけねー",
                [1591990],
                "気をつける",
                "きをつけねー",
                "きをつける",
                chain=["negative", "-え"],
            )
        ],
        set(),
    ),
    "vowel after a kanji": ("気い", lambda d: [_w("気い", [1221520], "気", "きい", "き")], set()),
    **{
        f"vowel after a kanji, 来る {surface}": (
            surface,
            lambda d, s=surface, r=reading: [
                _w(s, [_seq(d, "来る", "vk")], "来る", r, "くる", chain=["negative", "kansai-ben negative"])
            ],
            set(),
        )
        for surface, reading in [("来えへん", "けえへん"), ("来いひん", "きいひん"), ("来おへん", "こおへん")]
    },
    "okurigana is no stretch": (
        "食う",
        lambda d: [_w("食う", [1956480], "食", "くう", "しょく")],
        {"form-relation"},
    ),
    "vowel after a kanji, in a chain": (
        "見いひん",
        lambda d: [
            _w(
                "見いひん",
                [_seq(d, "見る", "v1")],
                "見る",
                "みいひん",
                "みる",
                chain=["negative", "kansai-ben negative"],
            )
        ],
        set(),
    ),
    # Spaces and symbols that split one word (§1).
    "name with a space": (
        "TIME SLIP黄金丸",
        lambda d: [{"surface": "TIME SLIP黄金丸", "kind": "name", "targets": ["name"]}],
        set(),
    ),
    "line-break space": (
        "頑張 って",
        lambda d: [_w("頑張 って", [1217700], "頑張る", "がんばって", "がんばる", chain=["-て"])],
        set(),
    ),
    "digit-group comma": (
        "44,276",
        lambda d: [
            _w(
                "44,276",
                [],
                "44,276",
                "よんまんよんせんにひゃくななじゅうろく",
                "よんまんよんせんにひゃくななじゅうろく",
            )
        ],
        set(),
    ),
    # With no entry the form is the surface as written (§4.4), commas and all.
    "digit-group comma, form without it": (
        "44,276",
        lambda d: [
            _w(
                "44,276",
                [],
                "44276",
                "よんまんよんせんにひゃくななじゅうろく",
                "よんまんよんせんにひゃくななじゅうろく",
            )
        ],
        {"form-relation"},
    ),
    "digit-group comma before a counter": (
        "44,276票",
        lambda d: [
            _w(
                "44,276票",
                [_seq(d, "票", "ctr")],
                "票",
                "よんまんよんせんにひゃくななじゅうろくひょう",
                "ひょう",
                split_points=[6],
            )
        ],
        set(),
    ),
    # A sentence-final よ stays out of a chain it would join only through -いる or -おく (§4.1).
    "sentence-final よ after て": (
        "買ってよ",
        lambda d: [
            _w("買って", [1473740], "買う", "かって", "かう", chain=["-て"]),
            {"surface": "よ", "kind": "particle"},
        ],
        set(),
    ),
    "quotative って after a verb": (
        "思うって",
        lambda d: [
            _w("思う", [1589350], "思う", "おもう", "おもう"),
            {"surface": "って", "kind": "particle"},
        ],
        set(),
    ),
    # A form must be reachable from the surface somehow.
    "wrong entry": (
        "食べた",
        lambda d: [_w("食べた", [1358280], "飲む", "たべた", "のむ")],
        {"form-spelling"},
    ),
    "unrelated OOV form": (
        "ぴえん",
        lambda d: [_w("ぴえん", [], "ぱおん", "ぴえん", "ぱおん")],
        {"form-relation"},
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_surface_form_relations(name: str, dictionary: Dictionary) -> None:
    text, make_units, expected = CASES[name]
    assert _rules(_record(text, make_units(dictionary)), dictionary) == expected


def test_chain_maximal_ignores_stretch_readings(dictionary: Dictionary) -> None:
    """A following unit is absorbed only by a chain, never by reading the pair as a stretch."""
    from monosashi.validate import _reach

    entries = [e for e in dictionary.lookup("凄い") if e.seq == 1374550]
    # すごい|い: the pair reads as a stretch of すごい, which must not make すごい absorb い.
    assert _reach("すごいい", entries).chains_for("すごい")
    assert not _reach("すごいい", entries, stretch=False).chains_for("すごい")


def test_a_stretch_after_a_small_vowel_keeps_its_chain() -> None:
    from monosashi.validate import _variants

    # あり得ねぇー: dropping only the ー leaves あり得ねぇ, which still deinflects.
    assert "ありえねぇ" in _variants("ありえねぇー")


def test_a_chain_still_absorbs_a_following_auxiliary(dictionary: Dictionary) -> None:
    data = _record(
        "食べた",
        [
            _w("食べ", [1358280], "食べる", "たべ", "たべる", chain=["continuative"]),
            {"surface": "た", "kind": "auxiliary"},
        ],
    )
    assert "chain-maximal" in _rules(data, dictionary)


@pytest.mark.parametrize(
    "surface", ["頑張。って", "頑張,って", "頑・張って", "頑―張って", "頑＼張って", "頑／＼張って"]
)
def test_symbols_inside_a_unit_must_split_one_word(surface: str, dictionary: Dictionary) -> None:
    unit = _w(surface, [1217700], "頑張る", "がんばって", "がんばる", chain=["-て"])
    assert "span-inner-symbol" in _rules(_record(surface, [unit]), dictionary)


def test_a_name_may_hold_its_separators(dictionary: Dictionary) -> None:
    for surface in ("ジャン=ポール", "F-ZERO", "メアリー・アン"):
        data = _record(surface, [{"surface": surface, "kind": "name"}])
        assert _rules(data, dictionary) == set(), surface


def test_a_repeat_mark_needs_two_characters_to_repeat(dictionary: Dictionary) -> None:
    data = _record("そ／＼と", [_w("そ／＼と", [], "そ／＼と", "そそと", "そそと")])
    assert "span-inner-symbol" in _rules(data, dictionary)

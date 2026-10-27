from __future__ import annotations

from typing import Any

import pytest

from helpers import record
from monosashi.deinflect import chains_to, deinflect, pos_condition_flags, transform_ids
from monosashi.jmdict import Dictionary
from monosashi.schema import record_from_dict
from monosashi.validate import validate_record


@pytest.mark.parametrize(
    ("surface", "form", "pos", "chain"),
    [
        ("始めてしまった", "始める", ["v1", "vt"], ("-て", "-しまう", "-た")),
        ("食べちゃった", "食べる", ["v1"], ("-ちゃう", "-た")),
        ("食べさせられなかった", "食べる", ["v1"], ("causative", "potential or passive", "negative", "-た")),
        ("感じた", "感じる", ["v1"], ("-た",)),
        ("すごくない", "すごい", ["adj-i"], ("negative",)),
        ("行かなければ", "行く", ["v5k-s"], ("negative", "-ば")),
    ],
)
def test_vendored_table_chains(surface: str, form: str, pos: list[str], chain: tuple[str, ...]) -> None:
    assert chain in chains_to(surface, form, pos)


def test_miru_supplement_puts_te_miru_inside_the_chain() -> None:
    assert "-みる" in transform_ids()
    assert ("-て", "-みる", "-た") in chains_to("食べてみた", "食べる", ["v1"])


def test_noun_suru_reaches_the_noun() -> None:
    assert ("-て", "-いる") in chains_to("勉強している", "勉強", ["n", "vs", "vt"])
    assert chains_to("勉強する", "勉強", ["n", "vs"]) == [()]  # bare する: an empty chain
    # Without the vs tag the noun takes no chain.
    assert chains_to("勉強している", "勉強", ["n"]) == []
    assert chains_to("勉強する", "勉強", ["n"]) == []


def test_exp_only_expressions_still_inflect() -> None:
    # JMdict tags かもしれない only exp, so no POS condition can be checked.
    assert ("-た",) in chains_to("かもしれなかった", "かもしれない", ["exp"])
    assert chains_to("かもしれなかった", "かもしれない", ["n"]) == []
    # A chain may end in a polite form, which is no dictionary form: ございません (core aoz-179-36-2).
    assert ("negative",) in chains_to("ございません", "ございます", ["aux-v", "exp"])
    # Or in a te-form, when no auxiliary was stripped: Kansai に沿うて is に沿って (2215300).
    assert chains_to("に沿うて", "に沿って", ["adv", "exp"]) == [("kansai-ben -て",)]
    assert chains_to("からというて", "からといって", ["exp"]) == [("kansai-ben -て",)]
    # But a te + auxiliary anywhere in the chain stays out, also behind a Kansai te-form.
    assert chains_to("に沿うている", "に沿って", ["adv", "exp"]) == []


def test_identity_and_non_inflecting_entries() -> None:
    assert chains_to("学生", "学生", ["n"]) == [()]
    assert chains_to("学生じゃない", "学生", ["n"]) == []
    # なければならない is not a transform: the chain stops at 行かなければ.
    assert chains_to("行かなければならない", "行く", ["v5k-s"]) == []


def test_pos_mapping_covers_godan_subclasses_and_skips_archaic() -> None:
    v5 = pos_condition_flags(["v5k-s"])
    assert v5 and v5 == pos_condition_flags(["v5r"])
    assert pos_condition_flags(["adj-ix"]) == pos_condition_flags(["adj-i"])
    assert pos_condition_flags(["vs-c"]) == 0
    assert pos_condition_flags(["n", "prt"]) == 0


@pytest.mark.parametrize(
    ("surface", "form", "pos", "chain"),
    [
        ("見せてもらった", "見せる", ["v1"], ("-て", "-もらう", "-た")),
        ("走ってくる", "走る", ["v5r"], ("-て", "-くる")),
        ("書いてあげた", "書く", ["v5k"], ("-て", "-あげる", "-た")),
        ("置いてある", "置く", ["v5k"], ("-て", "-ある")),
        ("持っていく", "持つ", ["v5t"], ("-て", "-いく")),
        ("来てくれる", "来る", ["vk"], ("-て", "-くれる")),
        ("読んでほしい", "読む", ["v5m"], ("-て", "-ほしい")),
        ("持っていかない", "持つ", ["v5t"], ("-て", "-いく", "negative")),
        ("読んでく", "読む", ["v5m"], ("-て", "-いく")),
        ("立ててゆく", "立てる", ["v1"], ("-て", "-いく")),
        # Kanji auxiliaries.
        ("持って行く", "持つ", ["v5t"], ("-て", "-いく")),
        ("見せて貰った", "見せる", ["v1"], ("-て", "-もらう", "-た")),
        ("飛んで来た", "飛ぶ", ["v5b"], ("-て", "-くる", "-た")),
    ],
)
def test_te_auxiliary_supplements(surface: str, form: str, pos: list[str], chain: tuple[str, ...]) -> None:
    assert chain in chains_to(surface, form, pos)


@pytest.mark.parametrize(
    ("surface", "form", "pos"),
    [("出てった", "出る", ["v1"]), ("出てってる", "出る", ["v1"]), ("飲んでった", "飲む", ["v5m"])],
)
def test_contracted_iku_stays_inside_the_chain(surface: str, form: str, pos: list[str]) -> None:
    assert any("-いく" in chain for chain in chains_to(surface, form, pos))


@pytest.mark.parametrize(
    ("surface", "form", "pos", "chain"),
    [
        ("わかん", "わかる", ["v5r"], ("-ん (kansai)",)),
        ("すん", "する", ["vs-i"], ("-ん (kansai)",)),
        ("おもろない", "おもろい", ["adj-i"], ("-ない (kansai)",)),
        ("こよ", "くる", ["vk"], ("volitional (short)",)),
        ("しよ", "する", ["vs-i"], ("volitional (short)",)),
        ("行きゃがる", "行く", ["v5k-s"], ("-ゃがる",)),
    ],
)
def test_kansai_and_colloquial_supplements(
    surface: str, form: str, pos: list[str], chain: tuple[str, ...]
) -> None:
    assert chain in chains_to(surface, form, pos)


@pytest.mark.parametrize(
    ("surface", "form"), [("見", "見る"), ("寝", "寝る"), ("出", "出る"), ("居", "居る"), ("着", "着る")]
)
def test_one_kanji_ichidan_stems_reach_their_verb(surface: str, form: str) -> None:
    # The table's continuative needs a kana ending (食べ -> 食べる), so it can't see 見 in 見ながら.
    assert ("continuative (kanji stem)",) in chains_to(surface, form, ["v1"])


def test_kanji_stems_reach_only_their_listed_verbs() -> None:
    assert chains_to("花", "花る", ["v1"]) == []
    assert [d.chain for d in deinflect("見")] == [(), ("continuative (kanji stem)",)]


def test_supplement_ids_are_listed() -> None:
    new = {"-くる", "-いく", "-ある", "-あげる", "-くれる", "-もらう", "-ほしい"}
    new |= {"-ん (kansai)", "-ない (kansai)", "volitional (short)", "-ゃがる", "continuative (kanji stem)"}
    assert new <= transform_ids()


def _rules(data: dict[str, Any], dictionary: Dictionary) -> set[str]:
    return {issue.rule for issue in validate_record(record_from_dict(data), dictionary)}


def test_supplements_leave_ordinary_words_alone(dictionary: Dictionary) -> None:
    assert chains_to("知らん", "知る", ["v5r"]) == [("-ん",)]
    # -ない (kansai) takes only ろない, so 少ない is no negative of its search-only spelling 少い.
    assert chains_to("少ない", "少い", ["adj-i"]) == []
    sukunai = {"start": 0, "end": 3, "surface": "少ない", "kind": "word", "entries": [1348910], "form": "少い",
               "reading": "すくない", "form_reading": "すくない", "chain": ["-ない (kansai)"]}  # fmt: skip
    assert "form-orthography" in _rules(record("少ない", [sukunai]), dictionary)
    sukunai.update(form="少ない")
    del sukunai["chain"]
    assert _rules(record("少ない", [sukunai]), dictionary) == set()


def test_quotative_tte_after_a_te_form_stays_out(dictionary: Dictionary) -> None:
    # No bare てって rule: the って after 待って is the quotative particle, not いく.
    assert chains_to("待ってって", "待つ", ["v5t"]) == []
    matte = record(
        "待ってって言った",
        [
            {"start": 0, "end": 3, "surface": "待って", "kind": "word", "entries": [1410590], "form": "待つ",
             "reading": "まって", "form_reading": "まつ", "chain": ["-て"]},
            {"start": 3, "end": 5, "surface": "って", "kind": "particle"},
            {"start": 5, "end": 8, "surface": "言った", "kind": "word", "entries": [1587040], "form": "言う",
             "reading": "いった", "form_reading": "いう", "chain": ["-た"]},
        ],
    )  # fmt: skip
    yamete = record(
        "やめてって",
        [
            {"start": 0, "end": 3, "surface": "やめて", "kind": "word", "entries": [1310680], "form": "やめる",
             "reading": "やめて", "form_reading": "やめる", "chain": ["-て"]},
            {"start": 3, "end": 5, "surface": "って", "kind": "particle"},
        ],
    )  # fmt: skip
    assert _rules(matte, dictionary) == set()
    assert _rules(yamete, dictionary) == set()


def test_exp_only_chains_never_strip_a_te_auxiliary(dictionary: Dictionary) -> None:
    # として and 一人で are exp-only and end in て/で. Stripping て + an auxiliary (-くれる,
    # -いる) leaves a bare te-form, no inflection of them, so the auxiliary stays its own unit.
    assert chains_to("としてくれる", "として", ["exp"]) == []
    assert chains_to("一人でいる", "一人で", ["exp"]) == []
    shouyo = record(
        "賞与としてくれる",
        [
            {"start": 0, "end": 2, "surface": "賞与", "kind": "word", "entries": [1351990], "form": "賞与",
             "reading": "しょうよ", "form_reading": "しょうよ"},
            {"start": 2, "end": 5, "surface": "として", "kind": "expression", "entries": [1008590],
             "form": "として", "reading": "として", "form_reading": "として"},
            {"start": 5, "end": 8, "surface": "くれる", "kind": "word", "entries": [1269130], "form": "くれる",
             "reading": "くれる", "form_reading": "くれる"},
        ],
    )  # fmt: skip
    hitori = {"start": 0, "end": 3, "surface": "一人で", "kind": "expression", "entries": [1163700],
              "form": "一人で", "reading": "ひとりで", "form_reading": "ひとりで"}  # fmt: skip
    iku = {"start": 3, "end": 5, "surface": "行く", "kind": "word", "entries": [1578850], "form": "行く",
           "reading": "いく", "form_reading": "いく"}  # fmt: skip
    iru = {"start": 3, "end": 5, "surface": "いる", "kind": "word", "entries": [1577980], "form": "いる",
           "reading": "いる", "form_reading": "いる"}  # fmt: skip
    assert _rules(shouyo, dictionary) == set()
    assert _rules(record("一人で行く", [hitori, iku]), dictionary) == set()
    assert _rules(record("一人でいる", [hitori, iru]), dictionary) == set()

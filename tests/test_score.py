"""The scorer on hand-built predictions over the SPEC worked examples (SPEC.md §7)."""

from __future__ import annotations

import itertools
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from monosashi.jmdict import Dictionary
from monosashi.predictions import Description, PredictedUnit, Prediction
from monosashi.schema import Record, Unit, load_records
from monosashi.score import (
    METRICS,
    Scorer,
    ToolScores,
    bootstrap,
    category_scores,
    coverage,
    paired_difference,
    score_tool,
)

EXAMPLES = {r.id: r for r in load_records(Path(__file__).parent / "fixtures" / "spec-examples.jsonl")}
FULL = Description("full", "1", "test", "2026", True, ("form", "reading", "form_reading", "entries", "kind"))
CONTENT_ONLY = Description("cards", "1", "test", "2026", False, ("form", "form_reading"))
NO_READING = CONTENT_ONLY.fields  # the fields of a tool that outputs no reading

# Gold units for the other ways to pass (SPEC.md §7), labeled as §4 says. 三十八 is a
# number with no entry of its own.
NUMBER = Unit(0, 3, "三十八", "word", (), "三十八", "さんじゅうはち", "さんじゅうはち")
BENKYOU_SHITA = Unit(0, 4, "勉強した", "word", (1512670,), "勉強", "べんきょうした", "べんきょう", ("-た",))
FRAGMENT = Unit(0, 1, "か", "interjection", (), "か", "か", "か", targets=("ellipsis-truncation",))
KANOJO = Unit(2, 4, "彼女", "word", (1483150,), "彼女", "かのじょ", "かのじょ")
# 使える (1607180) is a derived verb with an entry of its own; 行われた is 行う (1589060) + passive.
TSUKAENAI = Unit(0, 4, "使えない", "word", (1607180,), "使える", "つかえない", "つかえる", ("negative",))
OKONAWARETA = Unit(
    0, 4, "行われた", "word", (1589060,), "行う", "おこなわれた", "おこなう", ("passive", "-た")
)


def _record(record_id: str, text: str, *units: Unit) -> Record:
    return replace(EXAMPLES["spec-01"], id=record_id, text=text, units=units)


ALTERNATIVES = [
    _record("alt-number", "三十八", NUMBER),
    _record("alt-suru", "勉強した", BENKYOU_SHITA),
    _record("alt-suru-split", "勉強した", replace(BENKYOU_SHITA, split_points=(2,))),
    _record("alt-fragment", "か、彼女", FRAGMENT, KANOJO),
    _record("alt-derived", "使えない", TSUKAENAI),
    _record("alt-voice", "行われた", OKONAWARETA),
]


def _from_gold(u: Unit) -> PredictedUnit:
    return PredictedUnit(u.start, u.end, u.surface, u.form, u.reading, u.form_reading, u.entries, u.kind)


def perfect(record: Record) -> Prediction:
    return Prediction(record.id, tuple(_from_gold(u) for u in record.units))


def _score(
    dictionary: Dictionary,
    records: list[Record],
    predictions: list[Prediction],
    d: Description = FULL,
    name: str | None = None,
) -> ToolScores:
    return score_tool(Scorer(dictionary), name or d.name, d, records, predictions)


def test_perfect_predictions_score_one_everywhere(dictionary: Dictionary) -> None:
    records = list(EXAMPLES.values())
    scores = _score(dictionary, records, [perfect(r) for r in records])
    for metric in METRICS:
        value = scores.value(metric)
        # Copying gold keeps すげー as すげー: right, but not normalized to すごい.
        expected = 0.0 if metric in ("junk", "normalized") else 1.0
        assert value == expected or value is None, metric


def test_an_accepted_split_fails_strict_and_passes_lenient(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-01"]  # 彼女|は|一人·暮らし|を|始めてしまった
    units = [_from_gold(u) for u in r.units]
    hitori = PredictedUnit(3, 5, "一人", "一人", "ひとり", "ひとり", (), "word")
    gurashi = PredictedUnit(5, 8, "暮らし", "暮らし", "くらし", "くらし", (), "word")
    split = Prediction(r.id, (units[0], units[1], hitori, gurashi, *units[3:]))
    s = _score(dictionary, [r], [split])
    assert s.value("card") == pytest.approx(2 / 3)  # 一人暮らし is not card-ready on its own span
    assert s.value("card_lenient") == 1.0  # ...but is left out under lenient scoring
    assert s.value("junk") == 0.0  # the pieces of an accepted split are not junk
    assert (s.value("seg") or 0.0) < 1.0
    assert s.value("seg_lenient") == 1.0


def test_a_split_chain_fails_both_but_is_scored_tiled(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-02"]  # 食べちゃった, one unit
    pieces = (
        PredictedUnit(0, 2, "食べ", "食べる", "たべ", "たべる", (), "word"),
        PredictedUnit(2, 5, "ちゃっ", "ちゃう", "ちゃっ", "ちゃう", (), "auxiliary"),
        PredictedUnit(5, 6, "た", "た", "た", "た", (), "auxiliary"),
    )
    s = _score(dictionary, [r], [Prediction(r.id, pieces)])
    assert s.value("card") == 0.0
    assert s.value("card_lenient") == 0.0  # 2 and 5 are not split points
    assert (s.value("seg_lenient") or 0.0) < 1.0
    assert s.value("reading_tiled") == 1.0  # たべ + ちゃっ + た
    assert s.value("form_tiled") == 1.0  # the first content piece's form, 食べる
    assert s.value("reading") is None  # no exact span to score


def test_joining_two_units_fails_both(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-07"]  # そう|です·か
    joined = Prediction(
        r.id, (PredictedUnit(0, 5, "そうですか", "そうですか", "そうですか", "そうですか", (), "word"),)
    )
    s = _score(dictionary, [r], [joined])
    assert s.value("card") == 0.0
    assert s.total()["card.n"] == 2
    assert s.value("junk") == 1.0


def test_a_three_way_split_of_spec_07_scored_by_hand(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-07"]  # そう|です·か, predicted as そう|です|か
    units = (
        PredictedUnit(0, 2, "そう", "そう", "そう", "そう", (2137720,), "word"),
        PredictedUnit(2, 4, "です", "です", "です", "です", (), "copula"),
        PredictedUnit(4, 5, "か", "か", "か", "か", (), "particle"),
    )
    s = _score(dictionary, [r], [Prediction(r.id, units)])
    assert s.value("card") == 0.5  # そう passes; ですか has no unit of its own span
    assert s.value("card_lenient") == 1.0  # ですか is cut only at its split point: left out
    assert s.value("seg") == pytest.approx(0.4)  # 1 span right of 3 predicted and 2 gold: 2/(3+2)
    assert s.value("seg_lenient") == 1.0  # boundary 2 on both sides; 4 is a split point
    assert s.value("content") == pytest.approx(2 / 3)  # です and か are function units: 2/(1+2)
    assert s.value("junk") == 0.0


def test_a_content_only_tool_gets_content_metrics_only(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-01"]
    cards = [_from_gold(u) for u in r.units if u.kind == "word"]
    extra = PredictedUnit(2, 3, "は", "は", None, "は")  # a particle mined as a card: junk
    s = _score(dictionary, [r], [Prediction(r.id, (*cards, extra))], CONTENT_ONLY)
    assert s.value("card") == 1.0
    assert s.value("seg") is None and s.value("seg_lenient") is None
    assert s.value("junk") == pytest.approx(1 / 4)
    assert s.value("content") == pytest.approx(2 * 3 / (4 + 3))


def test_scoring_accepts_any_spelling_and_noun_suru(dictionary: Dictionary) -> None:
    sugoi = EXAMPLES["spec-11"]  # すご〜い, form すごい: 凄い is accepted too
    u = sugoi.units[0]
    kanji = Prediction(
        sugoi.id, (PredictedUnit(u.start, u.end, u.surface, "凄い", u.reading, "すごい", (), "word"),)
    )
    assert _score(dictionary, [sugoi], [kanji]).value("card") == 1.0
    benkyou = EXAMPLES["spec-05"]  # 勉強している, form 勉強: 勉強する is accepted too, read べんきょうする
    g = benkyou.units[0]
    suru = Prediction(
        benkyou.id,
        (PredictedUnit(g.start, g.end, g.surface, "勉強する", None, "べんきょうする", (), "word"),),
    )
    s = _score(dictionary, [benkyou], [suru])
    assert (s.value("card"), s.value("form"), s.value("form_reading")) == (1.0, 1.0, 1.0)


def test_a_normalized_card_passes_with_its_own_reading(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-10"]  # すげー, normalized to すごい
    u = r.units[0]
    normalizing = PredictedUnit(u.start, u.end, u.surface, "すごい", u.reading, "すごい", (), "interjection")
    s = _score(dictionary, [r], [Prediction(r.id, (normalizing,))])
    assert (s.value("card"), s.value("form_reading"), s.value("normalized")) == (1.0, 1.0, 1.0)
    # The normalized reading goes only with a normalized form: (すげー, すごい) is no card.
    mixed = replace(normalizing, form="すげー")
    assert _score(dictionary, [r], [Prediction(r.id, (mixed,))]).value("card") == 0.0


def test_form_and_form_reading_must_belong_to_one_entry(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-10"]  # すげー (2722660), normalized to すごい (1374550)
    u = r.units[0]
    # 凄い spells the normalized entry and すげー is the gold form_reading, but only 2722660 reads すげー.
    mixed = PredictedUnit(u.start, u.end, u.surface, "凄い", u.reading, "すげー", (), "interjection")
    assert not Scorer(dictionary).card_ok(u, mixed)
    assert _score(dictionary, [r], [Prediction(r.id, (mixed,))]).value("card") == 0.0
    assert Scorer(dictionary).card_ok(u, replace(mixed, form_reading="すごい"))  # one entry's pair


def test_a_unit_with_no_entry_passes_on_span_and_reading(dictionary: Dictionary) -> None:
    r = _record("no-entry", "三十八", NUMBER)
    scorer = Scorer(dictionary)
    any_form = PredictedUnit(0, 3, "三十八", "38", "さんじゅうはち", "さんじゅうはち", (), "word")
    assert _score(dictionary, [r], [Prediction(r.id, (any_form,))]).value("card") == 1.0
    assert not scorer.card_ok(NUMBER, replace(any_form, reading="さんじゅうや"))
    # A tool with no reading: its form_reading stands in, since the gold unit has no chain.
    no_reading = PredictedUnit(0, 3, "三十八", "38", None, "さんじゅうはち")
    assert _score(dictionary, [r], [Prediction(r.id, (no_reading,))], CONTENT_ONLY).value("card") == 1.0
    # Only a tool that outputs no reading: one that does but leaves a unit's out gets no stand-in.
    assert not scorer.card_ok(NUMBER, no_reading)
    # With a chain, the form_reading is a dictionary form's reading, not the reading in context:
    # a tool with no reading passes on the gold form and form_reading together.
    gugutta = Unit(0, 4, "ググった", "word", (), "ググる", "ぐぐった", "ぐぐる", ("-た",), targets=("oov",))
    assert scorer.card_ok(gugutta, PredictedUnit(0, 4, "ググった", "ググる", None, "ぐぐる"), NO_READING)
    assert not scorer.card_ok(
        gugutta, PredictedUnit(0, 4, "ググった", "ググる", None, "ぐぐった"), NO_READING
    )
    assert not scorer.card_ok(
        gugutta, PredictedUnit(0, 4, "ググった", "ググった", None, "ぐぐる"), NO_READING
    )
    assert scorer.card_ok(gugutta, PredictedUnit(0, 4, "ググった", "ググった", "ぐぐった", None))


def test_a_number_and_counter_needs_the_sound_changed_reading(dictionary: Dictionary) -> None:
    scorer = Scorer(dictionary)
    g = EXAMPLES["spec-21"].units[0]  # 二十本: form 本, reading にじゅっぽん, form_reading ほん
    assert "二十本" in scorer.accepted_forms(g)
    # The whole surface as form, with the gold reading as reading, or as form_reading when there is none.
    assert scorer.card_ok(g, PredictedUnit(0, 3, "二十本", "二十本", "にじゅっぽん", None))
    assert scorer.card_ok(g, PredictedUnit(0, 3, "二十本", "二十本", None, "にじゅっぽん"), NO_READING)
    assert not scorer.card_ok(g, PredictedUnit(0, 3, "二十本", "二十本", None, "にじゅっぽん"))
    assert not scorer.card_ok(g, PredictedUnit(0, 3, "二十本", "二十本", "にじゅうほん", "にじゅっぽん"))
    # The counter as form passes only with the sound-changed reading.
    assert scorer.card_ok(g, PredictedUnit(0, 3, "二十本", "本", "にじゅっぽん", "ほん"))
    assert not scorer.card_ok(g, PredictedUnit(0, 3, "二十本", "本", None, "ほん"), NO_READING)
    assert not scorer.card_ok(g, PredictedUnit(0, 3, "二十本", "本", "にじゅうほん", "ほん"))
    r = EXAMPLES["spec-21"]
    counter_only = Prediction(r.id, (PredictedUnit(0, 3, "二十本", "本", None, "ほん"),))
    assert _score(dictionary, [r], [counter_only], CONTENT_ONLY).value("card") == 0.0
    # ASCII digits: the widened surface is an accepted form.
    digits = replace(g, surface="20本")
    assert scorer.card_ok(digits, PredictedUnit(0, 3, "20本", "２０本", "にじゅっぽん", None))
    # A counter JMdict lists whole (三本) is an ordinary entry: no reading needed.
    sanbon = EXAMPLES["spec-12"].units[0]
    assert scorer.card_ok(sanbon, PredictedUnit(0, 2, "三本", "三本", None, "さんぼん"))


def test_the_noun_alone_is_a_card_for_noun_suru(dictionary: Dictionary) -> None:
    noun = PredictedUnit(0, 2, "勉強", "勉強", "べんきょう", "べんきょう", (1512670,), "word")
    rest = PredictedUnit(2, 4, "した", "する", "した", "する", (), "word")
    for split_points in ((), (2,)):
        r = _record("suru", "勉強した", replace(BENKYOU_SHITA, split_points=split_points))
        s = _score(dictionary, [r], [Prediction(r.id, (noun, rest))])
        assert (s.value("card"), s.value("card_lenient")) == (1.0, 1.0), split_points
        assert s.total()["card_lenient.n"] == 1, split_points  # the unit stays in the lenient count
        assert s.value("junk") == 0.0, split_points  # neither 勉強 nor した is junk
    scorer = Scorer(dictionary)
    # The noun's span takes the noun's card only: 勉強 read べんきょうする is no card.
    assert not scorer.card_ok(BENKYOU_SHITA, replace(noun, form_reading="べんきょうする"))
    # The noun ends where the rest of the surface deinflects to する by the chain, so an
    # unlisted spelling of the noun (勉彊) has its noun span too.
    variant = replace(BENKYOU_SHITA, surface="勉彊した", targets=("kanji-variant",))
    assert scorer.card_ok(variant, replace(noun, surface="勉彊"))
    # A stretched vs noun with no する has no noun span, and no する form.
    ryoukai = Unit(
        0, 3, "了解っ", "word", (1553310,), "了解", "りょうかいっ", "りょうかい", targets=("elongation",)
    )
    assert not scorer.card_ok(ryoukai, PredictedUnit(0, 2, "了解", "了解", "りょうかい", "りょうかい"))
    assert "了解する" not in scorer.accepted_forms(ryoukai)


def test_a_unit_the_tool_marks_as_a_particle_earns_no_card(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-07"]  # そう|ですか
    units = [_from_gold(u) for u in r.units]
    units[1] = replace(units[1], kind="particle")
    s = _score(dictionary, [r], [Prediction(r.id, tuple(units))])
    assert s.value("card") == 0.5
    assert not Scorer(dictionary).card_ok(r.units[1], units[1])
    # A tool that declares no kinds is not read for them.
    assert Scorer(dictionary).card_ok(r.units[1], units[1], ("form", "reading", "form_reading"))


def test_interjections_with_no_entry_are_left_out_of_card_ready(dictionary: Dictionary) -> None:
    r = _record("fragment", "か、彼女", FRAGMENT, KANOJO)  # a stammered か before 彼女
    s = _score(dictionary, [r], [Prediction(r.id, (_from_gold(KANOJO),))])
    assert (s.total()["card.n"], s.value("card")) == (1, 1.0)
    # A laugh or a shout with no entry (シシシ, どおおおおっ) has no card to make either.
    laugh = _record("laugh", "か、彼女", replace(FRAGMENT, targets=("kana-run",)), KANOJO)
    assert _score(dictionary, [laugh], [Prediction(laugh.id, ())]).total()["card.n"] == 1
    # An interjection with an entry has a card.
    other = _record("fragment", "か、彼女", replace(FRAGMENT, entries=(2028970,)), KANOJO)
    assert _score(dictionary, [other], [Prediction(other.id, ())]).total()["card.n"] == 2


def test_either_verb_passes_for_derived_verbs_and_voice_chains(dictionary: Dictionary) -> None:
    scorer = Scorer(dictionary)
    # The base verb, from the form and each kanji spelling of 使える's entry (使える, 遣える).
    assert scorer.voice_alternatives(TSUKAENAI) == {("使う", "つかう"), ("遣う", "つかう")}
    assert scorer.voice_alternatives(OKONAWARETA) == {("行われる", "おこなわれる")}  # the derived verb
    tsukau = PredictedUnit(0, 4, "使えない", "使う", "つかえない", "つかう", (1305990,), "word")
    okonawareru = PredictedUnit(0, 4, "行われた", "行われる", "おこなわれた", "おこなわれる", (), "word")
    for gold, card in ((TSUKAENAI, tsukau), (OKONAWARETA, okonawareru)):
        r = _record("voice", gold.surface, gold)
        assert _score(dictionary, [r], [Prediction(r.id, (card,))]).value("card") == 1.0, gold.surface
    assert scorer.card_ok(TSUKAENAI, replace(tsukau, form="遣う"))
    # A chain starting with -すぎる or -がる accepts the entry it passes through too.
    tabesugita = Unit(
        0, 5, "食べすぎた", "word", (1358280,), "食べる", "たべすぎた", "たべる", ("-すぎる", "-た")
    )
    assert scorer.card_ok(
        tabesugita, PredictedUnit(0, 5, "食べすぎた", "食べすぎる", "たべすぎた", "たべすぎる", (), "word")
    )
    # Each alternative is a pair: the other verb with this verb's reading is no card.
    assert not scorer.card_ok(TSUKAENAI, replace(tsukau, form_reading="つかえる"))
    assert not scorer.card_ok(OKONAWARETA, replace(okonawareru, form_reading="おこなう"))
    assert scorer.voice_alternatives(EXAMPLES["spec-01"].units[0]) == frozenset()  # 彼女
    # A bare kana spelling of the entry is not deinflected: かえる would reach かう, another verb.
    kaeru = Unit(0, 2, "帰る", "word", (1221270,), "帰る", "かえる", "かえる")
    assert ("かう", "かう") not in scorer.voice_alternatives(kaeru)
    assert not scorer.card_ok(kaeru, PredictedUnit(0, 2, "帰る", "かう", "かえる", "かう"))


def test_the_derived_verb_passes_in_any_of_its_spellings(dictionary: Dictionary) -> None:
    scorer = Scorer(dictionary)
    # された as する (1157170) + passive takes 為れる (される), a spelling of される's own entry,
    # as it would if the labeler had chosen that entry (2269820).
    sareta = Unit(0, 3, "された", "word", (1157170,), "する", "された", "する", ("passive", "-た"))
    own_entry = replace(sareta, entries=(2269820,), form="される", form_reading="される", chain=("-た",))
    for gold in (sareta, own_entry):
        for form in ("為れる", "される"):
            assert scorer.card_ok(gold, PredictedUnit(0, 3, "された", form, "された", "される")), (gold, form)
    # なれる as なる (1375610) + potential: 成れる deinflects to 成る, a spelling of なる; 慣れる
    # deinflects to 慣る, which is no spelling of it (慣れる is another verb).
    nareru = Unit(0, 3, "なれる", "word", (1375610,), "なる", "なれる", "なる", ("potential",))
    assert scorer.card_ok(nareru, PredictedUnit(0, 3, "なれる", "成れる", "なれる", "なれる"))
    assert not scorer.card_ok(nareru, PredictedUnit(0, 3, "なれる", "慣れる", "なれる", "なれる"))


def test_voice_alternatives_pair_spelling_and_reading_through_the_same_rule(dictionary: Dictionary) -> None:
    # される deinflects to する (vs) and to す (godan) by passive; the two never cross.
    sareta = Unit(0, 3, "された", "word", (2269820,), "される", "された", "される", ("-た",))
    pairs = Scorer(dictionary).voice_alternatives(sareta)
    assert ("する", "する") in pairs
    assert ("する", "す") not in pairs and ("す", "する") not in pairs


def test_unknown_entry_ids_count_as_version_mismatch(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-14"]  # あの|方
    units = [_from_gold(u) for u in r.units]
    units[1] = replace(units[1], entries=(9999999,))
    s = _score(dictionary, [r], [Prediction(r.id, tuple(units))])
    assert s.total()["entry.mismatch"] == 1
    assert s.value("entry") == 1.0  # あの is still right; 方 is not counted wrong


def test_a_jmdict_id_for_a_name_is_wrong_not_a_mismatch(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-13"]  # 田中 (JMnedict 5543705)|さん
    units = [_from_gold(u) for u in r.units]
    units[0] = replace(units[0], entries=(1613340,))  # in the pin, but as a JMdict entry
    s = _score(dictionary, [r], [Prediction(r.id, tuple(units))])
    assert s.total()["entry.mismatch"] == 0
    assert s.value("entry") == 0.0


def test_entry_coverage_and_normalization_only_with_forms_or_ids(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-14"]  # あの|方, and the tool outputs only あの
    s = _score(dictionary, [r], [Prediction(r.id, (_from_gold(r.units[0]),))])
    assert (s.value("entry"), coverage(s.total(), "entry")) == (1.0, 0.5)
    sugee = EXAMPLES["spec-10"]
    spans_only = Description("spans", "1", "test", "2026", True, ())
    s = _score(dictionary, [sugee], [Prediction(sugee.id, (PredictedUnit(0, 3, "すげー"),))], spans_only)
    assert s.value("normalized") is None  # neither a form nor an id to judge


def test_wrong_reading_of_a_heteronym(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-15"]  # こっちの方, 方 read ほう
    units = [_from_gold(u) for u in r.units]
    units[2] = replace(units[2], reading="かた", form_reading="かた", entries=(1516925,))
    s = _score(dictionary, [r], [Prediction(r.id, tuple(units))])
    assert s.value("card") == pytest.approx(1 / 2)
    assert s.value("entry") == pytest.approx(1 / 2)
    by_category = category_scores(Scorer(dictionary), s, "heteronym")
    assert by_category.value("card") == 0.0


def test_a_crashed_record_scores_as_empty(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-01"]
    s = _score(dictionary, [r], [Prediction(r.id, (), None, "crash")])
    assert s.value("card") == 0.0
    assert s.statuses()["crash"] == 1


def test_a_garbled_record_scores_as_empty_but_keeps_its_units(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-07"]
    s = _score(dictionary, [r], [replace(perfect(r), status="garbled")])
    assert s.value("card") == 0.0 and s.value("seg") == 0.0
    assert len(s.predictions[r.id].units) == 2


def test_units_that_do_not_fit_the_text_garble_the_record(dictionary: Dictionary) -> None:
    r = EXAMPLES["spec-14"]  # あの方; the run saw another text, あの人
    units = (_from_gold(r.units[0]), PredictedUnit(2, 3, "人", "人", "ひと", "ひと", (), "word"))
    s = _score(dictionary, [r], [Prediction(r.id, units)])
    assert s.statuses()["garbled"] == 1
    assert s.value("card") == 0.0  # あの is not counted right either


def test_paired_bootstrap_brackets_the_point_estimate(dictionary: Dictionary) -> None:
    records = list(EXAMPLES.values())
    good = _score(dictionary, records, [perfect(r) for r in records], name="good")
    empty = [perfect(r) if i % 2 else Prediction(r.id, ()) for i, r in enumerate(records)]
    half = _score(dictionary, records, empty, name="half")
    intervals = bootstrap([good, half], "card", samples=200)
    assert intervals["good"] == (1.0, 1.0)
    low, high = intervals["half"]
    value = half.value("card")
    assert value is not None and low <= value <= high
    diff = paired_difference(good, half, "card", samples=200)
    assert diff is not None and diff[0] > 0


def _guess(scorer: Scorer, r: Record, start: int, end: int, data: st.DataObject) -> PredictedUnit:
    """A piece of a random segmentation; on a gold unit's span or its noun, a gold-derived card."""
    text = r.text[start:end]
    plain = PredictedUnit(start, end, text, text, None, None, (), "word")
    for g in r.units:
        if g.start != start or not g.is_content:
            continue
        if g.end == end:
            options = [
                PredictedUnit(start, end, text, g.form, g.reading, g.form_reading, g.entries, g.kind),
                PredictedUnit(start, end, text, text, g.reading, None, (), "word"),  # no entry, counter
                PredictedUnit(start, end, text, text, None, g.reading, (), None),  # no reading
                PredictedUnit(start, end, text, g.form, g.reading, g.form_reading, (), "particle"),
                *(PredictedUnit(start, end, text, f, None, fr, (), "word") for f, fr in sorted(scorer.voice_alternatives(g))),
            ]  # fmt: skip
        elif text == g.form:  # the noun of a noun + する unit
            options = [PredictedUnit(start, end, text, g.form, None, g.form_reading, (), "word")]
        else:
            continue
        return data.draw(st.sampled_from([plain, *options]))
    return plain


def _gold_cuts(r: Record) -> list[int]:
    """Inner offsets where the gold units start and end, split, or end their noun (勉強|した)."""
    points = {p for g in r.units for p in (g.start, g.end, *g.split_points)}
    points |= {g.start + len(g.form) for g in r.units if g.form and r.text.startswith(g.form, g.start)}
    return sorted(p for p in points if 0 < p < len(r.text))


# A partition tool that outputs no reading, for the paths where form_reading stands in.
NO_READING_TOOL = Description(
    "no-reading", "1", "test", "2026", True, ("form", "form_reading", "entries", "kind")
)


@settings(max_examples=300, deadline=None)
@given(st.data())
def test_random_segmentations_stay_in_bounds(data: st.DataObject) -> None:
    from monosashi.jmdict import Dictionary as D  # the fixture cannot be used inside @given

    scorer = Scorer(D(_INDEX[0]))
    examples = sorted(EXAMPLES.values(), key=lambda x: x.id)
    r = data.draw(st.one_of(st.sampled_from(examples), st.sampled_from([*ALTERNATIVES, EXAMPLES["spec-21"]])))
    tool = data.draw(st.sampled_from([FULL, NO_READING_TOOL]))
    # Most cuts fall on gold edges, where the other ways to pass can be reached; at most one anywhere.
    gold = _gold_cuts(r)
    cuts = data.draw(st.sets(st.sampled_from(gold))) if gold else set()
    if data.draw(st.booleans()):
        cuts.add(data.draw(st.integers(1, max(1, len(r.text) - 1))))
    edges = [0, *sorted(c for c in cuts if c < len(r.text)), len(r.text)]
    units = tuple(_guess(scorer, r, a, b, data) for a, b in itertools.pairwise(edges) if a < b)
    s = score_tool(scorer, tool.name, tool, [r], [Prediction(r.id, units)])
    for metric in METRICS:
        value = s.value(metric)
        assert value is None or 0.0 <= value <= 1.0, metric
    strict, lenient = s.value("card"), s.value("card_lenient")
    if strict is not None and lenient is not None:
        assert lenient >= strict
    # A unit that is a card is never junk, so cards and junk never overlap.
    total = s.total()
    cards = sum(1 for u in units if any(scorer.card_ok(g, u, tool.fields) for g in r.units if g.is_content))
    assert total["junk.ok"] + cards <= total["junk.n"]


_INDEX: list[Path] = []


@pytest.fixture(autouse=True)
def _remember_index(index_path: Path) -> None:
    if not _INDEX:
        _INDEX.append(index_path)

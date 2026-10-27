"""The tagger: lattice segmentation and the category detectors, on the mini fixture."""

from __future__ import annotations

import pytest

from monosashi.jmdict import Dictionary
from monosashi.label.candidates import candidate_sheet
from monosashi.tag import DETECTORS, _splits_katakana_run, hints_for, segment
from monosashi.taxonomy import CATEGORIES


def _surfaces(text: str, dictionary: Dictionary) -> list[str]:
    return [p.surface for p in segment(text, candidate_sheet(text, dictionary))]


def _hints(text: str, dictionary: Dictionary) -> set[tuple[str, str]]:
    return {(h.category, text[h.start : h.end]) for h in hints_for(text, dictionary)}


def _categories(text: str, dictionary: Dictionary) -> set[str]:
    return {h.category for h in hints_for(text, dictionary)}


def test_every_category_has_a_detector() -> None:
    assert set(DETECTORS) == set(CATEGORIES)


def test_segment_prefers_few_common_units_and_skips_symbols(dictionary: Dictionary) -> None:
    assert _surfaces("彼女は一人暮らしを始めてしまった。", dictionary) == [
        "彼女",
        "は",
        "一人暮らし",
        "を",
        "始めてしまった",
    ]


def test_segment_never_starts_a_mixed_unit_inside_katakana() -> None:
    assert _splits_katakana_run("トムはいい", 1, 4)
    assert not _splits_katakana_run("トムはいい", 0, 2)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "彼女は一人暮らしを始めてしまった。",
            {("compound", "一人暮らし"), ("te-auxiliary", "始めてしまった")},
        ),
        ("食べちゃった", {("contraction", "食べちゃった"), ("inflection-chain", "食べちゃった")}),
        ("勉強している", {("suru-verb", "勉強している")}),
        ("見れる", {("potential-ranuki", "見れる")}),
        ("感じた", {("jiru-zuru", "感じた")}),
        ("田中さん", {("name", "田中"), ("suffix", "田中さん")}),
        ("二十本", {("counter", "二十本"), ("counter-reading", "二十本")}),
        ("すご〜い", {("elongation", "すご〜い")}),
        ("あああ", {("kana-run", "あああ")}),
        ("ほんまにあかん", {("kansai", "ほんま"), ("kansai", "あかん")}),
        ("選挙管理委員会", {("long-compound", "選挙管理委員会")}),
        ("欲し…", {("ellipsis-truncation", "欲し")}),
        ("あ、あの方", {("ellipsis-truncation", "あ、あの")}),
        ("お兄ちゃん", {("kinship", "お兄ちゃん")}),
        ("あの方", {("heteronym", "方")}),
        ("見せてもらった", {("te-auxiliary", "見せてもらった")}),
    ],
)
def test_detectors_find_their_category(
    text: str, expected: set[tuple[str, str]], dictionary: Dictionary
) -> None:
    assert expected <= _hints(text, dictionary)


def test_a_weak_kansai_marker_alone_is_not_kansai(dictionary: Dictionary) -> None:
    assert not {c for c, _ in _hints("行くやろ", dictionary)} & {"kansai"}
    # めっちゃ is common far beyond Kansai, so it is only a weak marker.
    assert "kansai" not in _categories("めっちゃ", dictionary)


def test_ellipsis_needs_a_word_actually_cut_off(dictionary: Dictionary) -> None:
    # A whole word that trails off is no truncation: 待って…, そう…….
    for text in ("食べて", "待って…", "そう……"):
        assert "ellipsis-truncation" not in _categories(text, dictionary), text
    # 欲|し… is the start of 欲しい; a stammer may break on an ellipsis as well as a comma.
    assert ("ellipsis-truncation", "欲し") in _hints("何が欲し…", dictionary)
    assert ("ellipsis-truncation", "あ、あの") in _hints("あ、あの", dictionary)
    assert ("ellipsis-truncation", "そ……そう") in _hints("そ……そう", dictionary)


def test_archaic_needs_a_classical_unit_not_a_substring(dictionary: Dictionary) -> None:
    assert ("archaic-classical", "候") in _hints("存じ候", dictionary)
    # 候補者, ざるを得ない and けりをつける are modern words that spell 候, ざる and けり.
    for text in ("候補者", "ざるを得ない", "けりをつける"):
        assert "archaic-classical" not in _categories(text, dictionary), text


def test_counter_reading_fires_only_where_the_reading_changes(dictionary: Dictionary) -> None:
    assert ("counter", "三冊") in _hints("三冊", dictionary)
    assert "counter-reading" not in _categories("三冊", dictionary)  # さんさつ: no sound change
    # さんぼん, いっさい (not a counter compound, SPEC.md §6), じゅうよにん, みっつ,
    # さんがい, なんがい, さんげん, よんぷん; but さんかい.
    for text in ("三本", "一切", "14人", "3つ", "三階", "何階", "三軒", "四分"):
        assert ("counter-reading", text) in _hints(text, dictionary), text
    assert "counter-reading" not in _categories("三回", dictionary)


def test_counters_follow_the_spec(dictionary: Dictionary) -> None:
    # 年間 extends a counter, so 10年間 is 10年|間; after digits 万 is a counter (SPEC.md §4.4).
    assert ("counter", "10年") in _hints("10年間", dictionary)
    assert ("counter", "50万") in _hints("50万", dictionary)
    assert ("counter", "50万円") in _hints("50万円", dictionary)


def test_potential_hints_name_clear_potentials(dictionary: Dictionary) -> None:
    # 聞き取れる, 話し合える and 理解できる are no entries, though 取れる, 合える and きる are:
    # only a phrase (眼を開く) is split.
    for text in ("書ける", "見れる", "食べられない", "聞き取れない", "話し合える", "勉強できない"):
        assert ("potential-ranuki", text) in _hints(text, dictionary), text
    # 思える, 行ける and 開ける are verbs of their own (いけない, いけなかった, 眼を開けて); られる
    # may be a passive unless a negative follows (用いられた, 見られたくない); 誘えよ is an
    # imperative; ませぬ is ます + ぬ.
    for text in (
        "思えない",
        "いけない",
        "いけなかった",
        "眼を開けて",
        "用いられた",
        "見られたくない",
        "誘えよ",
        "ませぬ",
    ):
        assert "potential-ranuki" not in _categories(text, dictionary), text


def test_heteronyms_need_different_words_or_senses(dictionary: Dictionary) -> None:
    assert ("heteronym", "方") in _hints("あの方", dictionary)  # かた and ほう are two entries
    assert ("heteronym", "今日") in _hints("今日", dictionary)  # こんにち alone means 'these days'
    assert ("heteronym", "何") in _hints("何", dictionary)  # なに and なん, picked by the next sound
    # Free variants of one word (いく / ゆく, いう / ゆう), 彼 read あれ, a rare spelling, and
    # 私 read あたし, an entry of its own that JMdict marks as a register variant (fem).
    for text in ("行く", "言う", "彼", "私"):
        assert "heteronym" not in _categories(text, dictionary), text


def test_kinship_is_only_on_kanji(dictionary: Dictionary) -> None:
    assert "kinship" not in _categories("おじいさん", dictionary)


def test_oov_flags_hiragana_and_kanji_no_entry_matches(dictionary: Dictionary) -> None:
    assert ("oov", "ぬるぽ") in _hints("ぬるぽだよ", dictionary)
    assert ("oov", "尊死") in _hints("尊死だよ", dictionary)
    # An old spelling leaves short gaps (思|ふ, 滑|べり), which are no word of their own.
    assert "oov" not in _categories("思ふ", dictionary)
    assert "oov" not in _categories("滑べり", dictionary)


def test_tag_keeps_declared_hints(dictionary: Dictionary) -> None:
    from monosashi.schema import Source
    from monosashi.sources import Hint, Sentence
    from monosashi.tag import tag

    s = Sentence("syn-oov-001", "ぴえんだよ", Source("synthetic", "1", "CC-BY-SA-4.0", "x"), "game-net", "synthetic",
                 hints=(Hint("oov", 0, 3),))  # fmt: skip
    assert Hint("oov", 0, 3) in tag(s, dictionary).hints


def test_precision_rules(dictionary: Dictionary) -> None:
    hints = _hints("三本と一つの木", dictionary)
    assert ("counter-reading", "三本") in hints
    # 人 counts as にん here, so 三人 has no sound change; ことごとく is no classical ごとく.
    assert ("counter-reading", "三人") not in _hints("三人", dictionary)
    assert not {c for c, _ in _hints("ことごとく", dictionary)} & {"archaic-classical"}
    # A bare kinship noun is no address form; an ellipsis is never a hint by itself.
    assert not {c for c, _ in _hints("彼女は木を見た", dictionary)} & {"kinship"}
    assert all(t != "……" for _, t in _hints("そう……", dictionary))


def test_oov_flags_katakana_no_entry_explains(dictionary: Dictionary) -> None:
    assert ("oov", "ヌルポガッ") in _hints("ヌルポガッたよ", dictionary) or ("oov", "ヌルポガ") in _hints(
        "ヌルポガだよ", dictionary
    )
    # A run JMdict and JMnedict tile (セント|ヘレナ), or one inside a name (セントヘレナ島), is no oov.
    for text in ("セントヘレナ", "セントヘレナ島"):
        assert "oov" not in _categories(text, dictionary), text

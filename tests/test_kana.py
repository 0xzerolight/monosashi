from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from monosashi.kana import (
    WAVE_DASH,
    drop_kanji_stretch,
    fold_reading,
    full_size_vowels,
    has_kanji,
    is_normalized,
    is_reading,
    is_symbol,
    marks_to_vowels,
    normalize_text,
    read_inner_symbols,
    stretch_key,
    strip_marks,
    to_hiragana,
)


def test_to_hiragana_converts_katakana_only() -> None:
    assert to_hiragana("スゲー") == "すげー"
    assert to_hiragana("ヴァイオリン") == "ゔぁいおりん"
    assert to_hiragana("漢字とカナ") == "漢字とかな"


def test_to_hiragana_spells_historical_vu_kana_as_vu() -> None:
    """ヷヸヹヺ have no hiragana; they read as ゔぁ, ゔぃ, ゔぇ, ゔぉ (ヸオロン)."""
    assert to_hiragana("ヸオロン") == "ゔぃおろん"
    assert to_hiragana("ヷヹヺ") == "ゔぁゔぇゔぉ"


def test_normalize_folds_halfwidth_katakana_and_composes_voicing() -> None:
    assert normalize_text("ｶﾞﾝﾊﾞﾚ") == "ガンバレ"
    assert normalize_text("ﾊﾟﾝ") == "パン"


def test_normalize_unifies_tildes_to_jmdict_wave_dash() -> None:
    for tilde in ("～", "~", "∼"):
        assert normalize_text(f"すご{tilde}い") == f"すご{WAVE_DASH}い"


def test_normalize_keeps_fullwidth_digits_and_composes_nfd() -> None:
    assert normalize_text("１人暮らし") == "１人暮らし"
    assert normalize_text("が") == "が"


@given(st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xFFEF)))
def test_normalize_is_idempotent(text: str) -> None:
    assert is_normalized(normalize_text(text))


def test_reading_and_symbol_classes() -> None:
    assert is_reading("すご〜い") and is_reading("すげー")
    assert not is_reading("スゴイ") and not is_reading("")
    assert is_symbol("。") and is_symbol("！") and is_symbol("・") and is_symbol(" ")
    assert not is_symbol("ー") and not is_symbol(WAVE_DASH) and not is_symbol("あ")
    assert has_kanji("始めて") and not has_kanji("はじめて")


def test_stretch_helpers_leave_emphatic_marks_alone() -> None:
    """Emphatic っ and small vowels relate only through the validator's elongation variants
    (SPEC.md §8), so the shared stretch helpers keep them."""
    assert strip_marks("ほんっと") == "ほんっと" and stretch_key("ほんっと") == "ほんっと"
    assert strip_marks("うつるーっ") == "うつるっ" and stretch_key("うつるーっ") == "うつるっ"
    assert strip_marks("わぉ") == "わ" and stretch_key("わぉ") == "わ"
    assert strip_marks("すご〜い") == "すごい" and stretch_key("すごおおい") == "すごい"


def test_marks_to_vowels_spells_out_the_lengthened_vowel() -> None:
    assert marks_to_vowels("きをつけねー") == "きをつけねえ"
    assert marks_to_vowels("すごーい") == "すごおい"
    assert marks_to_vowels("ーあ") == "ーあ"  # nothing to lengthen
    assert marks_to_vowels("気ー") == "気ー"  # a kanji's vowel is unknown


def test_full_size_vowels() -> None:
    assert full_size_vowels("わぉ") == "わお"
    assert full_size_vowels("ワォ") == "ワオ"
    assert full_size_vowels("ほんっと") == "ほんっと"


def test_drop_kanji_stretch_needs_the_reading_to_show_it() -> None:
    assert drop_kanji_stretch("気い", "きい", "き") == "気"
    assert drop_kanji_stretch("見いひん", "みいひん", "みる") == "見ひん"
    # The vowel after the kanji is okurigana, not a stretch: 会う is not 会, nor 青い 青.
    assert drop_kanji_stretch("会う", "あう", "かい") is None
    assert drop_kanji_stretch("言う", "いう", "げん") is None
    assert drop_kanji_stretch("青い", "あおい", "あお") is None
    assert drop_kanji_stretch("気い", None, "き") is None
    assert drop_kanji_stretch("気", "き", "き") is None


def test_drop_kanji_stretch_needs_the_same_vowel() -> None:
    """The vowel must repeat the kanji's last vowel: おう and えい are spellings, not stretches."""
    assert drop_kanji_stretch("思う", "おもう", "おも") is None
    assert drop_kanji_stretch("通う", "かよう", "かよ") is None
    assert drop_kanji_stretch("問う", "とう", "と") is None


def test_drop_kanji_stretch_keeps_the_forms_reading() -> None:
    """The kanji reads as the form does: 食う read くう is not 食 (しょく) stretched."""
    assert drop_kanji_stretch("食う", "くう", "しょく") is None
    assert drop_kanji_stretch("言い", "いい", "げん") is None


def test_drop_kanji_stretch_in_a_chain_skips_the_forms_reading() -> None:
    """A chain changes the kanji's reading (来る: き, け, こ); deinflecting to the form checks it."""
    assert drop_kanji_stretch("来えへん", "けえへん") == "来へん"
    assert drop_kanji_stretch("来いひん", "きいひん") == "来ひん"
    assert drop_kanji_stretch("来おへん", "こおへん") == "来へん"
    assert drop_kanji_stretch("思う", "おもう") is None  # still the same vowel only


def test_fold_reading_folds_vu_and_yuu() -> None:
    assert fold_reading("ゔぉいど") == "ぼいど"
    assert fold_reading("ゔぁゔぃゔゔぇゔぉ") == "ばびぶべぼ"
    assert fold_reading("どーゆう") == "どーいう"


def test_read_inner_symbols() -> None:
    """SPEC.md §1: the spaces and symbols that split one word."""
    assert read_inner_symbols("頑張 って") == "頑張って"
    assert read_inner_symbols("頑張\u3000って") == "頑張って"
    assert read_inner_symbols("44,276") == "44276"
    assert read_inner_symbols("ナア――ンダ") == "ナアーーンダ"
    assert read_inner_symbols("そわ／＼した") == "そわそわした"
    assert read_inner_symbols("食べた") == "食べた"


def test_read_inner_symbols_spells_out_iteration_marks() -> None:
    """ゝ repeats the kana before it unvoiced, ゞ voiced; ヽ and ヾ likewise."""
    assert read_inner_symbols("いゝえ") == "いいえ"
    assert read_inner_symbols("みすゞ") == "みすず"
    assert read_inner_symbols("ぶゝ") == "ぶふ"
    assert read_inner_symbols("コヽロ") == "ココロ"
    assert read_inner_symbols("ハヾ") == "ハバ"
    assert read_inner_symbols("ゝ") == "ゝ"

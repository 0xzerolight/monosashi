"""Kana conversion, script tests, and the gold-text normalization."""

from __future__ import annotations

import unicodedata

_KATA_START, _KATA_END = 0x30A1, 0x30F6  # ァ..ヶ; their hiragana sit 0x60 lower
_HIRA_OFFSET = 0x60
# ヷヸヹヺ have no hiragana; they spell va, vi, ve, vo (ヸオロン), as ヴァ.. do.
_VU_KANA = {"ヷ": "ゔぁ", "ヸ": "ゔぃ", "ヹ": "ゔぇ", "ヺ": "ゔぉ"}

# SPEC.md §Normalization: JMdict spells stretched forms with U+301C (すご〜い), so
# every tilde-like dash in gold text becomes that one character.
WAVE_DASH = "〜"
_TILDES = {"～": WAVE_DASH, "~": WAVE_DASH, "∼": WAVE_DASH, "˜": WAVE_DASH}

# Halfwidth katakana block (U+FF61..U+FF9F) is folded with NFKC, which also joins
# a following halfwidth (semi-)voicing mark; nothing else is NFKC-folded, so
# fullwidth digits such as the １ in JMdict's １人暮らし survive.
_HALFWIDTH_KANA = range(0xFF61, 0xFFA0)


def to_hiragana(text: str) -> str:
    """Katakana letters (ァ..ヶ, and ヷ..ヺ as ゔぁ..ゔぉ) to hiragana; everything else,
    ー included, unchanged."""
    out = []
    for ch in text:
        code = ord(ch)
        out.append(_VU_KANA.get(ch) or (chr(code - _HIRA_OFFSET) if _KATA_START <= code <= _KATA_END else ch))
    return "".join(out)


def is_hiragana(ch: str) -> bool:
    return "ぁ" <= ch <= "ゟ"


def is_katakana(ch: str) -> bool:
    return "゠" <= ch <= "ヿ" or "ㇰ" <= ch <= "ㇿ"


def is_kanji(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x3134F
        or 0xF900 <= code <= 0xFAFF
        or ch in "々〆ヶ"
    )


def has_kanji(text: str) -> bool:
    return any(is_kanji(ch) for ch in text)


def has_katakana_letter(text: str) -> bool:
    """Any katakana letter (ァ..ヺ). The long-vowel mark ー sits in the katakana
    block but stretches hiragana words too (すげー), so it does not count."""
    return any("ァ" <= ch <= "ヺ" for ch in text)


def is_reading(text: str) -> bool:
    """A gold reading: non-empty hiragana, plus the long-vowel mark and 〜."""
    return bool(text) and all(is_hiragana(ch) or ch in "ー" + WAVE_DASH for ch in text)


def is_kana_text(text: str) -> bool:
    """Only kana, ー and 〜: a surface whose reading is the surface itself."""
    return bool(text) and all(is_hiragana(ch) or is_katakana(ch) or ch in "ー" + WAVE_DASH for ch in text)


_SMALL_VOWELS = "ぁぃぅぇぉ"


def strip_marks(text: str) -> str:
    """Drop the marks that stretch a word: ー, 〜 and a trailing small vowel.

    すご〜い -> すごい, すごーい -> すごい, 手ぇ -> 手. Used only to relate a
    stretched surface to its form; gold readings keep the marks.
    """
    out = text.replace("ー", "").replace(WAVE_DASH, "")
    if len(out) > 1 and out[-1] in _SMALL_VOWELS:
        out = out[:-1]
    return out


_VOWEL_ROWS = {
    "a": "あかがさざただなはばぱまやらわゃゕ",
    "i": "いきぎしじちぢにひびぴみりゐ",
    "u": "うくぐすずつづぬふぶぷむゆるゅゔ",
    "e": "えけげせぜてでねへべぺめれゑゖ",
    "o": "おこごそぞとどのほぼぽもよろをょ",
}
_VOWEL_OF = {ch: vowel for vowel, row in _VOWEL_ROWS.items() for ch in row}
_BARE_VOWELS = dict(zip("あいうえお", "aiueo", strict=True))
# A bare vowel that lengthens the mora before it: the same vowel (すごおい),
# or the long-vowel spellings おう and えい (ありがとう ~ ありがとー, せんせい ~ せんせー).
_LENGTHENS = {"a": "a", "i": "ie", "u": "uo", "e": "e", "o": "o"}


def stretch_key(text: str) -> str:
    """A word's vowel skeleton, the same for its plain and stretched spellings.

    Drops ー, 〜 and small vowels, and every bare vowel that only lengthens the
    mora before it: すごおおい, すご〜い and すごーい all give すごい; かわいいいい
    and かわいー give かわい, as does かわいい. Used only to relate a stretched
    surface to its form, on both sides of the comparison.
    """
    out: list[str] = []
    previous: str | None = None
    for ch in to_hiragana(text):
        if ch in "ー" + WAVE_DASH or ch in _SMALL_VOWELS:
            continue
        bare = _BARE_VOWELS.get(ch)
        if bare is not None and previous is not None and previous in _LENGTHENS[bare]:
            continue
        out.append(ch)
        previous = _VOWEL_OF.get(ch, bare)
    return "".join(out)


_VOWEL_KANA = dict(zip("aiueo", "あいうえお", strict=True))


def marks_to_vowels(text: str) -> str:
    """Each ー after a hiragana as the vowel it lengthens: きをつけねー -> きをつけねえ.

    Only relates a stretch to its form (SPEC.md §4.8), like ``stretch_key``.
    """
    out: list[str] = []
    for ch in text:
        vowel = _VOWEL_OF.get(out[-1], _BARE_VOWELS.get(out[-1])) if out and ch == "ー" else None
        out.append(_VOWEL_KANA[vowel] if vowel else ch)
    return "".join(out)


_FULL_SIZE = str.maketrans("ぁぃぅぇぉァィゥェォ", "あいうえおアイウエオ")


def full_size_vowels(text: str) -> str:
    """Small vowels as full-size ones: わぉ -> わお (SPEC.md §4.8)."""
    return text.translate(_FULL_SIZE)


def drop_kanji_stretch(surface: str, reading: str | None, form_reading: str | None = None) -> str | None:
    """The surface without a bare vowel that stretches the kanji before it (SPEC.md §4.8).

    気い read きい gives 気, 見いひん read みいひん gives 見ひん. The reading must show
    the stretch: the vowel repeats the vowel of the kanji's last mora (き + い), so
    the okurigana of 会う (あう), 思う (おもう) or 青い (あおい) is never dropped. With
    ``form_reading``, the reading up to the vowel must also be how the form starts:
    食う read くう is not 食 (しょく) stretched. A unit with a chain passes none, since
    the chain may change the kanji's reading (来えへん, けえへん, form 来る) and
    deinflecting to the form already checks it. None when nothing is dropped.
    """
    if reading is None:
        return None
    for k in range(1, len(surface)):
        vowel = _BARE_VOWELS.get(surface[k])
        tail = to_hiragana(surface[k:])
        if vowel is None or not is_kanji(surface[k - 1]) or not all(is_hiragana(ch) for ch in tail):
            continue
        before = reading[: -len(tail)] if reading.endswith(tail) else ""
        starts_form = form_reading is None or form_reading.startswith(before)
        if before and _VOWEL_OF.get(before[-1]) == vowel and starts_form:
            return surface[:k] + surface[k + 1 :]
    return None


_VU_ROW = {"ゔぁ": "ば", "ゔぃ": "び", "ゔぇ": "べ", "ゔぉ": "ぼ", "ゔ": "ぶ"}


def fold_reading(text: str) -> str:
    """A reading with ヴ folded into the バ row and ゆう into いう (SPEC.md §5).

    ヴォイド is ボイド, and どーゆう is どういう: §5 writes 言う's free variant
    ゆう only when the surface does. Used only to relate a reading to a form_reading.
    """
    for vu, ba in _VU_ROW.items():
        text = text.replace(vu, ba)
    return text.replace("ゆう", "いう")


def widen(text: str) -> str:
    """ASCII letters, digits and punctuation to their fullwidth forms.

    JMdict spells alphanumerics fullwidth (３つ, ＣＤ) while gold text keeps the
    source's ASCII (§2 of SPEC.md), so spellings compare after widening.
    """
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in text)


# Characters a number may be written with, before its counter (SPEC.md §4.4).
NUMERALS = frozenset("0123456789０１２３４５６７８９〇一二三四五六七八九十百千万億兆何数幾")
DIGITS = frozenset("0123456789０１２３４５６７８９")


def voiced(ch: str) -> str | None:
    """The voiced kana for ``ch`` (さ -> ざ, は -> ば), or None when it has none."""
    composed = unicodedata.normalize("NFC", ch + "\u3099")
    return composed if len(composed) == 1 else None


def is_symbol(ch: str) -> bool:
    """Characters that never belong to a unit: punctuation, symbols, spaces.

    ー and 〜 are excluded: they lengthen the word they sit in. (A 〜 that marks
    a range, as in 10時〜12時, may also stand outside any unit; the validator
    allows that.) ・ is a symbol.
    """
    if ch in "ー" + WAVE_DASH:
        return False
    return unicodedata.category(ch)[0] in "PSZ" or ch in "・"


SPACES = " 　"
DIGIT_COMMAS = ",，"
LENGTH_DASH = "―"  # U+2015, Aozora's length mark between kana (ナア――ンダ)
REPEAT_MARK = "／＼"  # Aozora's two-character repeat mark (そわ／＼した)
# Kana iteration marks: repeat the kana before them, unvoiced or voiced (いゝえ, みすゞ).
_ITERATION_MARKS = {"ゝ": False, "ゞ": True, "ヽ": False, "ヾ": True}


def read_inner_symbols(text: str) -> str:
    """A unit's surface without the symbols that split one word (SPEC.md §1).

    Spaces and digit-group commas drop out, ― reads as ー, ／＼ repeats the
    two characters before it (そわ／＼した -> そわそわした), and an iteration mark
    the kana before it (いゝえ -> いいえ, みすゞ -> みすず). Which symbols a unit
    may hold is the validator's ``span-inner-symbol`` check, not this one's.
    """
    out = text.replace(LENGTH_DASH, "ー")
    for ch in SPACES + DIGIT_COMMAS:
        out = out.replace(ch, "")
    while (k := out.find(REPEAT_MARK)) >= 2:
        out = out[:k] + out[k - 2 : k] + out[k + len(REPEAT_MARK) :]
    spelled: list[str] = []
    for ch in out:
        voiced = _ITERATION_MARKS.get(ch)
        if voiced is not None and spelled:
            base = unicodedata.normalize("NFD", spelled[-1])[0]
            ch = unicodedata.normalize("NFC", base + "\u3099") if voiced else base
        spelled.append(ch)
    return "".join(spelled)


def normalize_text(text: str) -> str:
    """The one normalization gold text gets, applied when the pool is built."""
    text = unicodedata.normalize("NFC", text)
    folded = []
    for ch in text:
        if ord(ch) in _HALFWIDTH_KANA:
            folded.append(unicodedata.normalize("NFKC", ch))
        else:
            folded.append(_TILDES.get(ch, ch))
    # NFC again: ｶﾞ folds to カ + combining U+3099, which composes to ガ.
    return unicodedata.normalize("NFC", "".join(folded))


def is_normalized(text: str) -> bool:
    return normalize_text(text) == text

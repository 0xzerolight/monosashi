"""Category hints for pool sentences, so selection can fill each category's quota.

The tagger guesses; labelers decide. It segments a sentence with a cheap
lattice over the JMdict candidate sheet (fewest units, common entries first),
then runs one detector per category over the units. A hint names the category
and the span that carries it. False hints only cost a category some of its
quota; the labeled ``targets`` are what scoring uses.

The segmenter is built from the gold machinery (JMdict and the deinflector),
not from any tool under test, so no tool's mistakes decide which sentences get
in.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import combinations

from monosashi.counters import DIGIT_COUNTERS, is_number_counter
from monosashi.deinflect import deinflect
from monosashi.jmdict import JMDICT, JMNEDICT, Dictionary, Entry
from monosashi.kana import (
    NUMERALS,
    has_kanji,
    has_katakana_letter,
    is_hiragana,
    is_kanji,
    is_katakana,
    is_symbol,
    stretch_key,
    to_hiragana,
    widen,
)
from monosashi.label.candidates import MAX_COUNTER, Candidate, candidate_sheet
from monosashi.sources import Hint, Sentence

# --- segmentation ------------------------------------------------------------------

# Single kana that are particles, the copula or chain glue; the candidate sheet leaves them out.
PARTICLES = frozenset("はがをにでとへのもやかよねなわぞぜさだしばてん")
_COST_COMMON = 1.0
_COST_RARE = 1.35
_COST_NAME = 2.0  # a name wins only where no word fits
_COST_RARE_KANA = 1.7  # a rare all-kana entry is more often a mis-match than a word
_COST_PARTICLE = 0.6  # two particle kana must cost more than one word (さ|ん vs さん)
_COST_UNKNOWN = 2.5
# A kana surface is rarely a word JMdict spells in kanji (しよう is する, not 仕様).
_COST_KANJI_WORD_IN_KANA = 0.6
# Each transform makes a reading a little less likely; a chain ending in the
# continuative (とっておき) is usually a noun that looks like a verb.
_COST_PER_TRANSFORM = 0.05
_COST_CONTINUATIVE = 0.6
# An expression or greeting spelled as a kanji word plus a particle (今日は) is
# usually that word and the particle.
_COST_KANJI_EXPRESSION = 1.0
# A katakana surface read as a native word (トム as 富む) loses to a name.
_COST_KATAKANA_AS_NATIVE = 1.2
# A number takes the counter after it (SPEC.md §4.4): 10年|間, not 10|年間.
_COST_COUNTER_BONUS = 0.1


@dataclass(frozen=True, slots=True)
class Piece:
    """One unit of the lattice path: a candidate, a particle, or an unknown character."""

    start: int
    end: int
    surface: str
    candidate: Candidate | None
    alternatives: tuple[Candidate, ...] = ()

    @property
    def is_particle(self) -> bool:
        return self.candidate is None and self.surface in PARTICLES

    @property
    def is_unknown(self) -> bool:
        return self.candidate is None and not self.is_particle


def _cost(c: Candidate) -> float:
    if c.entry.is_name:
        return _COST_NAME
    kana_surface = all(is_hiragana(ch) for ch in c.surface)
    cost = _COST_COMMON if c.entry.common else _COST_RARE_KANA if kana_surface else _COST_RARE
    if kana_surface and c.entry.kanji and "uk" not in c.entry.misc:
        cost += _COST_KANJI_WORD_IN_KANA
    if has_katakana_letter(c.surface) and not has_katakana_letter(c.form):
        cost += _COST_KATAKANA_AS_NATIVE
    cost += _COST_PER_TRANSFORM * len(c.chain)
    if c.chain[-1:] == ("continuative",):
        cost += _COST_CONTINUATIVE
    if set(c.entry.pos) <= {"exp", "int"} and has_kanji(c.surface[:-1]) and c.surface[-1] in PARTICLES:
        cost += _COST_KANJI_EXPRESSION
    if is_number_counter(c.surface, c.form, (c.entry,)):
        cost -= _COST_COUNTER_BONUS
    return cost


def _splits_katakana_run(text: str, start: int, end: int) -> bool:
    """A span that starts or ends inside a run of katakana (ト|ムはいい, マニア|ー愛好家).

    A span that is itself katakana may (ステレオ|ラジオ).
    """

    def joined(i: int) -> bool:
        return 0 < i < len(text) and is_katakana(text[i - 1]) and is_katakana(text[i])

    return joined(start) or joined(end)


def segment(text: str, candidates: Iterable[Candidate]) -> list[Piece]:
    """The cheapest path over the text: symbols are skipped, gaps become one-character pieces."""
    by_span: dict[tuple[int, int], list[Candidate]] = {}
    for c in candidates:
        whole_katakana = len(c.surface) >= 2 and _all_katakana(c.surface)
        if whole_katakana or not _splits_katakana_run(text, c.start, c.end):
            by_span.setdefault((c.start, c.end), []).append(c)
    for alts in by_span.values():
        alts.sort(key=_cost)
    n = len(text)
    Step = tuple[float, int, tuple[int, int] | None]
    best: list[Step] = [(0.0, -1, None)]
    best += [(float("inf"), -1, None)] * n
    ends: dict[int, list[tuple[int, int]]] = {}
    for span in by_span:
        ends.setdefault(span[1], []).append(span)
    for i in range(1, n + 1):
        ch = text[i - 1]
        if is_symbol(ch):
            step = 0.0
        elif ch in PARTICLES:
            step = _COST_PARTICLE
        else:
            step = _COST_UNKNOWN
        options: list[Step] = [(best[i - 1][0] + step, i - 1, None)]
        for span in ends.get(i, []):
            options.append((best[span[0]][0] + _cost(by_span[span][0]), span[0], span))
        best[i] = min(options, key=lambda o: o[0])
    pieces: list[Piece] = []
    i = n
    while i > 0:
        _, prev, taken = best[i]
        if taken is not None:
            alts = by_span[taken]
            pieces.append(Piece(prev, i, text[prev:i], alts[0], tuple(alts)))
        elif not is_symbol(text[prev]):
            pieces.append(Piece(prev, i, text[prev:i], None))
        i = prev
    return pieces[::-1]


# --- detectors -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Context:
    text: str
    pieces: list[Piece]
    dictionary: Dictionary


Detector = Callable[[Context], Iterator[tuple[int, int]]]
DETECTORS: dict[str, Detector] = {}


def detector(category: str) -> Callable[[Detector], Detector]:
    def register(fn: Detector) -> Detector:
        DETECTORS[category] = fn
        return fn

    return register


def _words(ctx: Context) -> Iterator[tuple[Piece, Candidate]]:
    for p in ctx.pieces:
        if p.candidate is not None and not p.candidate.entry.is_name:
            yield p, p.candidate


def _is_jmdict_word(dictionary: Dictionary, text: str) -> bool:
    return bool(dictionary.lookup(text, JMDICT))


_COMPOUND_POS = frozenset({"n", "n-adv", "n-t", "adj-no", "adj-na", "exp", "adv", "vs"})


@detector("compound")
def _compound(ctx: Context) -> Iterator[tuple[int, int]]:
    """A multi-kanji entry whose parts are words too (一人暮らし, 一日中, 気に入る)."""
    for p, c in _words(ctx):
        kanji = sum(is_kanji(ch) for ch in p.surface)
        if c.chain or p.surface != c.form:
            continue  # 失明する, 研究して: the noun + する, not a compound
        if len(p.surface) < 3 or kanji < 2 or _number_counter(p, ctx.dictionary) is not None:
            continue
        if not _COMPOUND_POS & set(c.entry.pos):
            continue
        for k in range(1, len(p.surface)):
            left, right = p.surface[:k], p.surface[k:]
            parts_ok = all(has_kanji(x) or len(x) >= 2 for x in (left, right))
            if parts_ok and all(_is_jmdict_word(ctx.dictionary, x) for x in (left, right)):
                yield p.start, p.end
                break


@detector("grammar-expression")
def _grammar_expression(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        if "exp" in c.entry.pos and len(p.surface) >= 3 and all(is_hiragana(ch) for ch in p.surface):
            yield p.start, p.end


@detector("inflection-chain")
def _inflection_chain(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        if len(c.chain) >= 2:
            yield p.start, p.end


TE_AUXILIARIES = frozenset(
    {"-いる", "-しまう", "-ちゃう", "-ちまう", "-おく", "-みる", "-くる", "-いく", "-ある", "-あげる", "-くれる",
     "-もらう", "-ほしい"}
)  # fmt: skip
CONTRACTIONS = frozenset(
    {"-ちゃう", "-ちまう", "-ちゃ", "-ゃ", "n-slang", "-ん", "imperative negative slang", "volitional slang"}
)
_CONTRACTED = re.compile(
    r"(?:[てで](?:る|た|て|ない|ます)|[とど](?:く|いた|いて|かない)|なきゃ|なくちゃ|ちゃ|じゃ)"
)


@detector("te-auxiliary")
def _te_auxiliary(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        if TE_AUXILIARIES & set(c.chain):
            yield p.start, p.end


@detector("contraction")
def _contraction(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        chain = set(c.chain)
        if CONTRACTIONS & chain:
            yield p.start, p.end
        elif {"-いる", "-おく"} & chain and _CONTRACTED.search(p.surface[len(c.form) - 1 :]):
            # ている without い (てる), ておく as とく
            tail = p.surface[len(c.form) - 1 :]
            if "てい" not in tail and "でい" not in tail and "てお" not in tail and "でお" not in tail:
                yield p.start, p.end


@detector("suru-verb")
def _suru_verb(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        if "vs" in c.entry.pos and p.surface.startswith(c.form) and len(p.surface) > len(c.form):
            yield p.start, p.end


@lru_cache(maxsize=4096)
def _jmdict_entries(dictionary: Dictionary, text: str) -> tuple[Entry, ...]:
    return tuple(dictionary.lookup(text, JMDICT))


def _number_counter(p: Piece, dictionary: Dictionary) -> tuple[str, str] | None:
    """(number, counter) when a piece is a number and its counter (SPEC.md §4.4).

    The counter is what ``counters.is_number_counter`` accepts: a ``ctr`` entry or
    one of ``COUNTER_WORDS`` (三本, 10年), or 万, 億 or 兆 after digits (50万).
    何か and 千二は are not counters, and neither is 年間 in 10年間.
    """
    if p.candidate is None or p.candidate.entry.is_name:
        return None
    surface = p.surface
    i = 0
    while i < len(surface) and surface[i] in NUMERALS:
        i += 1
    if i == len(surface) and surface[-1] in DIGIT_COUNTERS:
        i -= 1  # 50万: 万 counts after digits
    number, counter = surface[:i], surface[i:]
    if not number or len(counter) > MAX_COUNTER:
        return None
    if not is_number_counter(surface, counter, _jmdict_entries(dictionary, counter)):
        return None
    return number, counter


def _counters(ctx: Context) -> Iterator[tuple[Piece, str, str]]:
    for p in ctx.pieces:
        split = _number_counter(p, ctx.dictionary)
        if split is not None:
            yield p, split[0], split[1]


@detector("counter")
def _counter(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, _, _ in _counters(ctx):
        yield p.start, p.end


# How a number's last numeral changes the first sound of the counter after it: a small っ
# (いっぽん, ろっぴき, はっさつ, じゅっこ, ひゃっぽん) or a voiced は row after ん (さんぼん, なんびき).
_SOUND_CHANGES = {
    "一": "かさたは", "八": "かさたは", "十": "かさたは", "六": "かは", "百": "かは",
    "三": "は", "千": "は", "万": "は", "何": "は",
}  # fmt: skip
_ROWS = {"か": "かきくけこ", "さ": "さしすせそ", "た": "たちつてと", "は": "はひふへほ"}
# Changes particular to a numeral and a counter: the numeral's own reading (よにん, よじ, よねん,
# よえん, しがつ, くじ, くがつ), よんぷん, and voicing after ん (さんがい, なんげん, せんぞく).
_PAIR_CHANGES = {
    "四": frozenset({"人", "時", "年", "円", "月", "分"}),
    "九": frozenset({"時", "月"}),
    "三": frozenset({"階", "軒", "足"}),
    "何": frozenset({"階", "軒", "足"}),
    "千": frozenset({"軒", "足"}),
}
_KANJI_DIGITS = "〇一二三四五六七八九"
_POWERS = "十百千万"


def _kanji_number(n: int) -> str:
    """一 to 九十九 in kanji numerals: 14 is 十四, 20 is 二十."""
    tens, ones = divmod(n, 10)
    head = "" if tens == 0 else ("" if tens == 1 else _KANJI_DIGITS[tens]) + "十"
    return head + (_KANJI_DIGITS[ones] if ones else "")


# Counts read natively, not as number + counter: ついたち to とおか, はつか, ひとり, ふたり, はたち.
# Any number + つ (ひとつ, 3つ みっつ) is native too.
NATIVE_COUNTS = frozenset(
    spelling + counter
    for counter, numbers in (("日", (*range(1, 11), 14, 20, 24)), ("人", (1, 2)), ("歳", (20,)))
    for n in numbers
    for spelling in (_kanji_number(n), str(n), widen(str(n)))
)


def _last_numeral(number: str) -> str:
    """The numeral a number ends on when read: 14 and 十四 end on 四, 20 on 十, 300 on 百."""
    digits = unicodedata.normalize("NFKC", number)
    if not digits.isdecimal():
        return number[-1]
    stripped = digits.rstrip("0")
    if not stripped:
        return ""
    zeros = len(digits) - len(stripped)
    return _POWERS[min(zeros, 4) - 1] if zeros else _KANJI_DIGITS[int(stripped[-1])]


# How common counters read as counters: 人 is にん here, not ひと, and 本 is ほん, not もと.
COUNTER_READINGS = {
    "月": "がつ", "分": "ふん", "秒": "びょう", "番": "ばん", "割": "わり", "時": "じ", "円": "えん", "号": "ごう",
    "位": "い", "目": "め", "人": "にん", "週間": "しゅうかん", "時間": "じかん",
    "か月": "かげつ", "本": "ほん", "年": "ねん", "日": "にち", "杯": "はい",
    "匹": "ひき", "回": "かい", "階": "かい", "個": "こ", "冊": "さつ", "枚": "まい", "台": "だい", "度": "ど",
    "点": "てん", "歳": "さい", "才": "さい", "足": "そく", "軒": "けん", "頭": "とう", "羽": "わ", "泊": "はく",
    "件": "けん", "曲": "きょく", "品": "ひん", "歩": "ほ", "通": "つう", "発": "はつ", "杯目": "はいめ",
}  # fmt: skip


def _counter_readings_of(dictionary: Dictionary, counter: str) -> set[str]:
    """The counter's own reading: the listed one, else every reading of its ctr entries."""
    if counter in COUNTER_READINGS:
        return {COUNTER_READINGS[counter]}
    return {r for e in dictionary.lookup(counter, JMDICT) if "ctr" in e.pos for r in e.readings_of(counter)}


def _reading_changes(dictionary: Dictionary, number: str, counter: str) -> bool:
    """Whether a number and its counter read differently together than apart (三本 さんぼん, not 三冊).

    Covers a native count (ふつか, みっつ), a change particular to the pair (よにん,
    さんがい) and a sound change at the join (いっさい: 一切 is a ctr 切 after 一).
    """
    if counter == "つ" or number + counter in NATIVE_COUNTS:
        return True
    last = _last_numeral(number)
    if counter in _PAIR_CHANGES.get(last, ()):
        return True
    rows = "".join(_ROWS[row] for row in _SOUND_CHANGES.get(last, ""))
    return any(r[:1] in rows for r in _counter_readings_of(dictionary, counter))


@detector("counter-reading")
def _counter_reading(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, number, counter in _counters(ctx):
        if _reading_changes(ctx.dictionary, number, counter):
            yield p.start, p.end


PREFIXES = frozenset("おご御不無非未超再全各真")


@detector("prefix")
def _prefix(ctx: Context) -> Iterator[tuple[int, int]]:
    pieces = ctx.pieces
    for i, p in enumerate(pieces):
        nxt = pieces[i + 1] if i + 1 < len(pieces) else None
        if p.surface in PREFIXES and nxt is not None and nxt.candidate is not None and nxt.start == p.end:
            yield p.start, nxt.end  # お|仲間
        elif p.candidate is not None and len(p.surface) >= 2 and p.surface[0] in PREFIXES:
            rest = p.surface[1:]
            honorific = p.surface[0] in "おご御" and has_kanji(rest)
            kanji_prefix = p.surface[0] not in "おご御" and len(rest) >= 2
            if (honorific or kanji_prefix) and _is_jmdict_word(ctx.dictionary, rest):
                yield p.start, p.end  # ご注文, 不可能


SUFFIXES = frozenset(
    {"さん", "くん", "君", "ちゃん", "様", "さま", "たち", "達", "ら", "的", "化", "性", "者", "側", "ごと", "ぶり",
     "っぽい", "らしい", "屋", "先生", "氏", "殿", "共", "ども", "がち", "だらけ", "ずつ", "おき", "ごろ", "頃"}
)  # fmt: skip


@detector("suffix")
def _suffix(ctx: Context) -> Iterator[tuple[int, int]]:
    pieces = ctx.pieces
    for i, p in enumerate(pieces[1:], 1):
        prev = pieces[i - 1]
        if prev.candidate is None or prev.end != p.start or p.surface not in SUFFIXES:
            continue
        if prev.candidate.entry.is_name or {"n", "pn"} & set(prev.candidate.entry.pos):
            yield prev.start, p.end


_KANJI_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿々〆ヵヶ]{4,}")
_NOUN_POS = frozenset(
    {"n", "n-suf", "n-pref", "pref", "suf", "adj-no", "adj-na", "vs", "ctr", "n-adv", "n-t"}
)


@detector("long-compound")
def _long_compound(ctx: Context) -> Iterator[tuple[int, int]]:
    """Four or more kanji that are no single entry, made of two or more nouns (選挙管理委員会).

    The run must start and end on unit edges, so 私優柔不断 (a pronoun first) and
    時開始予定 (the tail of 10時) do not count.
    """
    for m in _KANJI_RUN.finditer(ctx.text):
        start, end = m.start(), m.end()
        if _is_jmdict_word(ctx.dictionary, m.group(0)):
            continue
        inside = [p for p in ctx.pieces if start <= p.start and p.end <= end]
        if not inside or inside[0].start != start or inside[-1].end != end or len(inside) < 2:
            continue
        if sum(p.end - p.start for p in inside) != end - start:
            continue
        if all(p.candidate is not None and _NOUN_POS & set(p.candidate.entry.pos) for p in inside):
            yield start, end


def _all_katakana(text: str) -> bool:
    return all(is_katakana(ch) for ch in text) and has_katakana_letter(text)


@detector("katakana")
def _katakana(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        if (
            len(p.surface) >= 3
            and _all_katakana(p.surface)
            and _all_katakana(c.entry.kana[0] if c.entry.kana else "")
        ):
            yield p.start, p.end


_HONORIFICS = ("さん", "くん", "君", "ちゃん", "様", "先生", "氏", "殿")
_COMMON_FOREIGN = frozenset({"トム", "メアリー", "ジョン", "ケン", "ボブ", "マイク", "ジャック", "メアリ"})


@detector("name")
def _name(ctx: Context) -> Iterator[tuple[int, int]]:
    """A name with an honorific after it, or a span only JMnedict explains."""
    for p in ctx.pieces:
        if p.surface in _COMMON_FOREIGN or not any(a.entry.is_name for a in p.alternatives):
            continue
        if ctx.text.startswith(_HONORIFICS, p.end):
            yield p.start, p.end
            continue
        shaped = sum(is_kanji(ch) for ch in p.surface) >= 2 or (
            len(p.surface) >= 3 and _all_katakana(p.surface)
        )
        if (
            p.candidate is not None
            and p.candidate.entry.is_name
            and shaped
            and p.surface[-1] not in PARTICLES
        ):
            yield p.start, p.end


_FUNCTION_POS = frozenset({"prt", "conj", "aux", "aux-v", "aux-adj", "exp", "int", "pn", "adv", "cop"})


def _kanji_first(c: Candidate) -> bool:
    e = c.entry
    return bool(e.kanji) and "uk" not in e.misc and not _FUNCTION_POS & set(e.pos)


@detector("kana-written")
def _kana_written(ctx: Context) -> Iterator[tuple[int, int]]:
    """A word JMdict spells in kanji, written in kana (わかる, きれい), with no kana-first reading."""
    for p, c in _words(ctx):
        hira = p.surface
        if (
            len(hira) >= 3
            and all(is_hiragana(ch) for ch in hira)
            and stretch_key(hira) == hira
            and not _KANA_RUN.search(hira)
            and c.entry.common
            and all(_kanji_first(a) for a in p.alternatives if not a.entry.is_name)
        ):
            yield p.start, p.end


@detector("jiru-zuru")
def _jiru_zuru(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        if has_kanji(c.form) and c.form.endswith(("じる", "ずる")) and {"v1", "vz"} & set(c.entry.pos):
            yield p.start, p.end


_CLASSICAL_CHAIN = frozenset({"-ぬ", "-ざる", "-ねば", "-む", "-んとする", "-んばかり", "-き"})
_CLASSICAL_POS = ("v2", "v4", "adj-ku", "adj-shiku", "adj-nari", "vn", "vr")
# べき and べく are everyday written Japanese, and まじ is modern slang, so neither counts.
_CLASSICAL_TEXT = re.compile(r"べし|(?<!こと)ごと[きくし]|けり|ざる|たまえ|候")


_MODERN_POS = ("v1", "v5", "vk", "vs", "vz", "adj-i", "adj-na", "n")


@detector("archaic-classical")
def _archaic(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        pos = c.entry.pos
        classical_only = any(x.startswith(_CLASSICAL_POS) for x in pos) and not any(
            x.startswith(_MODERN_POS) for x in pos
        )
        if _CLASSICAL_CHAIN & set(c.chain) or classical_only:
            yield p.start, p.end
    for m in _CLASSICAL_TEXT.finditer(ctx.text):
        if not _spelled_inside(ctx, m.start(), m.end()):
            yield m.start(), m.end()


def _spelled_inside(ctx: Context, start: int, end: int) -> bool:
    """Whether a longer word spells the span as part of itself (候 in 候補者, ざる in ざるを得ない)."""
    span = ctx.text[start:end]
    return any(
        p.candidate is not None and p.start <= start and end <= p.end and len(p.surface) > len(span)
        and span in p.candidate.form
        for p in ctx.pieces
    )  # fmt: skip


_NEGATIVE = frozenset({"negative", "-ず", "-ぬ", "-ん", "kansai-ben negative"})
# ませぬ is ます + -ぬ, and が出来る and も出来ない are phrases, not 増す, がする or もする with a potential.
_NOT_POTENTIAL_BASES = frozenset({"ます", "がする", "もする"})


def _is_potential(p: Piece, c: Candidate, dictionary: Dictionary) -> bool:
    """Whether a chain is a potential form the hint should name (SPEC.md §6).

    A ra-nuki potential always is (見れる, 来れない). ``potential or passive`` is
    only taken for a potential when a negative follows it (食べられない, 食べられません;
    not 用いられた or 見られたくない). A godan or する potential is not one in the
    imperative (誘えよ), or when its potential verb has an entry of its own (思える,
    行ける, 開ける in 眼を開けて): the derived verb carries no transform. 書ける has none.
    JMdict lists 見れる and 食べられる too, but the spec names both as potentials.
    """
    chain = c.chain
    if c.form in _NOT_POTENTIAL_BASES:
        return False
    if "potential or passive" in chain:
        after = [t for t in chain[chain.index("potential or passive") + 1 :] if t != "-ます"]
        return bool(after) and after[0] in _NEGATIVE
    if "potential" not in chain:
        return False
    k = chain.index("potential")
    if chain[k + 1 : k + 2] == ("imperative",):
        return False
    if {"v1", "vk"} & set(c.entry.pos):
        return True
    outer = chain[k + 1 :]
    phrase = "exp" in c.entry.pos
    return not any(
        r.chain == outer and _has_own_entry(dictionary, r.text, phrase) for r in deinflect(p.surface)
    )


# Case particles inside a phrase entry, after which its verb starts (眼を開く).
_CASE_PARTICLES = frozenset("をがにでとへのもは")


def _has_own_entry(dictionary: Dictionary, verb: str, phrase: bool) -> bool:
    """Whether JMdict spells a verb, in kana too, or, in a phrase, its kanji verb (開ける in 眼を開ける).

    Nothing else is split: 聞き取れる, 話し合える and 理解できる have no entry, though
    取れる, 合える and きる do.
    """
    words = {verb, to_hiragana(verb)}
    if phrase:
        words |= {
            verb[k:] for k in range(1, len(verb)) if verb[k - 1] in _CASE_PARTICLES and is_kanji(verb[k])
        }
    return any(_jmdict_entries(dictionary, w) for w in words)


@detector("potential-ranuki")
def _potential(ctx: Context) -> Iterator[tuple[int, int]]:
    """A potential form, ra-nuki or not (見れる, 書ける, 食べられない); see ``_is_potential``."""
    for p, c in _words(ctx):
        if _is_potential(p, c, ctx.dictionary):
            yield p.start, p.end


@detector("kanji-variant")
def _kanji_variant(ctx: Context) -> Iterator[tuple[int, int]]:
    """A kanji spelling that is no entry's first spelling (判る, 逢う)."""
    for p, c in _words(ctx):
        if not has_kanji(c.form) or _number_counter(p, ctx.dictionary) is not None:
            continue
        spelled = [a.entry for a in p.alternatives if not a.entry.is_name and c.form in a.entry.kanji]
        if spelled and all(e.kanji[0] != c.form for e in spelled):
            yield p.start, p.end


# すげー, やべえ, 知らねえ: an e-row mora stretched after at least one other mora
# (a bare ねえ or へえ is an interjection).
_E_STRETCH = re.compile(r".[けげせぜてでねへべぺめれ][えぇー]")


@detector("colloquial-variant")
def _colloquial(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, _ in _words(ctx):
        if not has_katakana_letter(p.surface) and _E_STRETCH.search(p.surface):
            yield p.start, p.end


_SMALL_VOWELS = "ぁぃぅぇぉ"


@detector("elongation")
def _elongation(ctx: Context) -> Iterator[tuple[int, int]]:
    text = ctx.text
    for i, ch in enumerate(text):
        if i == 0 or ch not in "ー〜" + _SMALL_VOWELS:
            continue
        prev = text[i - 1]
        stretched = (is_hiragana(prev) or is_kanji(prev)) and not (
            ch in _SMALL_VOWELS and prev in "ふゔてでうくぐつしじちぢ"
        )
        if stretched:
            piece = next((p for p in ctx.pieces if p.start <= i - 1 < p.end), None)
            yield (piece.start, max(piece.end, i + 1)) if piece else (i - 1, i + 1)
    for p, c in _words(ctx):
        hira = to_hiragana(p.surface)
        if hira[0] in "ー〜" or has_katakana_letter(p.surface):
            continue
        reached_by_stretch = not c.entry.has_spelling(p.surface) and not c.entry.has_spelling(hira)
        if reached_by_stretch and not c.chain and stretch_key(hira) == stretch_key(to_hiragana(c.form)):
            yield p.start, p.end  # かわいいいい, a stretch the sheet resolved to its word


_KANA_RUN = re.compile(r"([ぁ-ゖァ-ヺ])\1{2,}|([ぁ-ゖァ-ヺ]{2})\2{2,}")


@detector("kana-run")
def _kana_run(ctx: Context) -> Iterator[tuple[int, int]]:
    for m in _KANA_RUN.finditer(ctx.text):
        yield m.start(), m.end()


@detector("katakana-form")
def _katakana_form(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        e = c.entry
        if "on-mim" in e.misc:
            continue  # katakana is the usual way to write a sound (グウグウ)
        if has_katakana_letter(p.surface) and e.kana and to_hiragana(e.kana[0]) == e.kana[0]:
            standard = e.kanji[0] if e.kanji else e.kana[0]
            if not has_katakana_letter(standard):
                yield p.start, p.end


@detector("heteronym")
def _heteronym(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        if _number_counter(p, ctx.dictionary) is not None:
            continue  # counter-reading's job
        if has_kanji(c.form) and _is_heteronym(ctx.dictionary, c.form):
            yield p.start, p.end


@lru_cache(maxsize=65536)
def _is_heteronym(dictionary: Dictionary, spelling: str) -> bool:
    """Two common readings of a kanji spelling that are different words (SPEC.md §6).

    The readings belong to different entries (方 かた, ほう) or to senses restricted
    to different readings (今日 こんにち 'these days'). Free variants of one word
    (行く いく, ゆく) are not heteronyms, nor is a register variant JMdict files as an
    entry of its own (私 あたし, fem).
    """
    entries = _jmdict_entries(dictionary, spelling)
    readings = sorted(dictionary.common_readings(spelling))
    return any(
        not any(_one_word(e, spelling, a, b) for e in entries)
        and not _register_variant(entries, spelling, a, b)
        for a, b in combinations(readings, 2)
    )


# JMdict misc tags that mark a reading as the speaker's choice of register, not of meaning.
_REGISTER_TAGS = frozenset(
    {"fem", "male", "col", "sl", "vulg", "hum", "pol", "hon", "joc", "chn", "arch", "dated"}
)


def _register_variant(entries: Sequence[Entry], spelling: str, a: str, b: str) -> bool:
    """Whether ``a`` and ``b`` are entries of their own with one meaning, one of them marked
    as a register (私: わたし 'I; me' and あたし 'I; me', fem). 何 なに and なん, untagged, are
    picked by the next sound and stay a heteronym."""
    for x, y in ((a, b), (b, a)):
        for ex in entries:
            if x not in ex.readings_of(spelling) or not ex.senses:
                continue
            for ey in entries:
                if ey is ex or y not in ey.readings_of(spelling) or not ey.senses:
                    continue
                shared = set(ex.senses[0].glosses) & set(ey.senses[0].glosses)
                if shared and _REGISTER_TAGS & set(ey.senses[0].misc):
                    return True
    return False


def _one_word(entry: Entry, spelling: str, a: str, b: str) -> bool:
    """Whether readings ``a`` and ``b`` of ``spelling`` are one word of ``entry``, sense for sense."""
    if not {a, b} <= entry.readings_of(spelling):
        return False
    for sense in entry.senses:
        only = {to_hiragana(k) for k in sense.kana}
        if (not sense.kanji or spelling in sense.kanji) and only and (a in only) != (b in only):
            return False
    return True


# Address forms written with kanji, whose reading is not the bare noun's (お兄ちゃん おにいちゃん,
# 父さん とうさん). The kana spellings (おじいさん) are no kinship target (SPEC.md §6).
KINSHIP = frozenset(
    {"お父さん", "お母さん", "お兄さん", "お姉さん", "お兄ちゃん", "お姉ちゃん", "父さん", "母さん", "兄さん",
     "姉さん", "兄ちゃん", "姉ちゃん", "兄貴", "姉貴", "親父", "お袋", "お祖父さん", "お祖母さん", "お爺さん",
     "お婆さん", "爺ちゃん", "婆ちゃん", "叔父さん", "伯父さん", "叔母さん", "伯母さん", "奥さん", "旦那さん",
     "息子さん", "娘さん", "父上", "母上", "兄上", "姉上", "お袋さん", "母ちゃん", "父ちゃん"}
)  # fmt: skip


@detector("kinship")
def _kinship(ctx: Context) -> Iterator[tuple[int, int]]:
    for p in ctx.pieces:
        if not has_kanji(p.surface):
            continue
        if p.surface in KINSHIP or (p.candidate is not None and p.candidate.form in KINSHIP):
            yield p.start, p.end


_END = r"(?=[。、！？!?」』…ー〜]|$)"
# Markers that are Kansai on their own, and markers that are only Kansai next to another one
# (はった is also 張った, やろ also the volitional of やる, and めっちゃ is common everywhere).
_KANSAI_STRONG = re.compile(
    "|".join(
        [
            r"やねん", r"やんか", r"あかん", r"ほんま", r"おおきに", r"しゃあない", r"知らんけど",
            r"へんかった", r"へんねん", r"まへん", r"かまへん", r"あらへん", r"おれへん", r"せえへん", r"けえへん",
            r"きいひん", r"でんがな", r"まんがな", r"さかい" + _END, r"なんでやねん",
        ]
    )
)  # fmt: skip
_KANSAI_WEAK = re.compile(
    "|".join(
        [
            r"ねん" + _END, r"やん" + _END, r"せやな?", r"ちゃう" + _END, r"(?<=[かさまらわなが])へん" + _END,
            r"はる" + _END, r"はった", r"やろ" + _END, r"やで", r"やわ", r"かいな", r"ほな", r"ええ(?:やん|で|わ|ねん)",
            r"めっちゃ",
        ]
    )
)  # fmt: skip


@detector("kansai")
def _kansai(ctx: Context) -> Iterator[tuple[int, int]]:
    strong = list(_KANSAI_STRONG.finditer(ctx.text))
    weak = list(_KANSAI_WEAK.finditer(ctx.text))
    if strong or len(weak) >= 2:
        for m in strong + weak:
            yield m.start(), m.end()


# An ellipsis cuts a word off; a dash (――) in Aozora is punctuation, not a truncation.
_ELLIPSIS = re.compile(r"…+|‥+|\.{2,}|・{3,}")
# A stammer: a word's first kana or two, then a comma or an ellipsis, then the word (あ、あの; ソ……そんな).
# It opens the text, a clause or a quote: after 彼 or 』 the kana is a particle (彼は、母).
_STAMMER = re.compile(r"(?<![^、。！？!?…‥「『（(　 ―])([ぁ-ゖァ-ヺ]{1,2})(?:、|…+|‥+|\.{2,}|・{3,})")
# Conjunctions that open a sentence: が、外出 is 'but, going out', と、とうとう 'and then, at last'.
_NOT_STAMMERS = frozenset({"が", "と"})
_SMALL_KANA = frozenset("ぁぃぅぇぉっゃゅょゎゕゖ")
# Particle kana that may end a cut-off stem rather than follow a whole noun: 欲|し… but 私|も….
_STEM_TAILS = frozenset("して")


def _letters(text: str) -> bool:
    """Hiragana or kanji that can start a word: no small kana or っ."""
    return all(is_kanji(ch) or (is_hiragana(ch) and ch not in _SMALL_KANA) for ch in text)


def _cut_word(ctx: Context, end: int) -> tuple[int, int] | None:
    """The word an ellipsis at ``end`` cuts off, or None when a whole word trails off (待って…, そう…).

    The text before it is a gap in the lattice right after a known unit (ちょっと待…;
    a gap after a gap is an unknown word, 焚殺…), or a kanji word and し or て that
    are no word but the start of a longer spelling (欲|し… is the start of 欲しい).
    """
    before = [p for p in ctx.pieces if p.end <= end]
    if not before or before[-1].end != end:
        return None
    k, tail = len(before) - 1, ""
    if before[k].surface in _STEM_TAILS and k > 0 and before[k - 1].end == before[k].start:
        k, tail = k - 1, before[k].surface
    word = before[k]
    after_known = k > 0 and before[k - 1].end == word.start and not before[k - 1].is_unknown
    unknown = word.is_unknown and _letters(word.surface) and after_known
    spelled_on = (
        word.candidate is not None
        and bool(tail)
        and has_kanji(word.surface)
        and not _jmdict_entries(ctx.dictionary, word.surface + tail)
        and ctx.dictionary.spells_on(word.surface + tail, JMDICT)
    )
    return (word.start, end) if unknown or spelled_on else None


def _reads_from(p: Piece, kana: str) -> bool:
    """Whether a piece starts with ``kana`` (hiragana) as written or as read: そんな, 貴様 from き."""
    c = p.candidate
    readings = c.entry.readings_of(c.form) if c is not None else frozenset()
    return any(r.startswith(kana) for r in (to_hiragana(p.surface), *readings))


@detector("ellipsis-truncation")
def _ellipsis(ctx: Context) -> Iterator[tuple[int, int]]:
    """A word an ellipsis cuts off (欲し…), or a stammered word (あ、あの; キ……貴様).

    Never the punctuation, and never a whole word that trails off (待って…).
    """
    for m in _ELLIPSIS.finditer(ctx.text):
        cut = _cut_word(ctx, m.start())
        if cut is not None:
            yield cut
    for m in _STAMMER.finditer(ctx.text):
        fragment = m.group(1)
        word = next((p for p in ctx.pieces if p.start == m.end()), None)
        if fragment in _NOT_STAMMERS or word is None or word.surface == fragment:
            continue
        if _reads_from(word, to_hiragana(fragment)):
            yield m.start(), word.end


@detector("onomatopoeia")
def _onomatopoeia(ctx: Context) -> Iterator[tuple[int, int]]:
    for p, c in _words(ctx):
        if "on-mim" in c.entry.misc:
            yield p.start, p.end


_REPEAT = re.compile(r"(..+)\1")


_KATAKANA_RUN = re.compile(r"[ァ-ヺー]{4,}")
_HIRAGANA_OR_KANJI_RUN = re.compile(r"[ぁ-ゖ]+|[㐀-䶿一-鿿豈-﫿々]+")


@detector("oov")
def _oov(ctx: Context) -> Iterator[tuple[int, int]]:
    """A word JMdict has no entry for: katakana of four or more letters, or a hiragana or kanji gap.

    A katakana run JMdict spells whole, or one JMnedict name, is known, and so is a
    run inside one unit (the name セントヘレナ島). So is a run the lattice tiles
    with words or names of two or more letters (ステレオ|ラジオ, セント|ヘレナ):
    oov is never a name (SPEC.md §6). Anything else, with
    unknown or short pieces, is a candidate OOV word; repeating runs are sounds (ピイピイ).
    Hiragana or kanji count where the lattice matches nothing in three or more
    hiragana or two or more kanji in a row. Shorter gaps are mostly old spellings
    (思|ふ, 違 for 違い, 滑べり), not words.
    """
    yield from _unknown_runs(ctx)
    for m in _KATAKANA_RUN.finditer(ctx.text):
        word, start, end = m.group(0), m.start(), m.end()
        if (
            _KANA_RUN.search(word)
            or _REPEAT.search(word)
            or word[0] in "ーッァィゥェォャュョ"
            or word[-1] == "ッ"
        ):
            continue
        if _is_jmdict_word(ctx.dictionary, word) or ctx.dictionary.lookup(word, JMNEDICT):
            continue
        if any(p.candidate is not None and p.start <= start and end <= p.end for p in ctx.pieces):
            continue  # one unit spans the run and more (セントヘレナ島)
        inside = [p for p in ctx.pieces if start <= p.start and p.end <= end]
        tiled = bool(inside) and sum(p.end - p.start for p in inside) == end - start
        known = all(p.candidate is not None and len(p.surface) >= 2 for p in inside)
        if not (tiled and known):
            yield start, end


def _unknown_runs(ctx: Context) -> Iterator[tuple[int, int]]:
    """Three or more hiragana, or two or more kanji, in a row that the lattice left unknown."""
    unknown = {p.start for p in ctx.pieces if p.is_unknown}  # an unknown piece is one character
    for m in _HIRAGANA_OR_KANJI_RUN.finditer(ctx.text):
        i = m.start()
        while i < m.end():
            j = i
            while j < m.end() and j in unknown:
                j += 1
            word = ctx.text[i:j]
            if (
                word
                and len(word) >= (2 if is_kanji(word[0]) else 3)
                and _letters(word[0])
                and not _KANA_RUN.search(word)
                and not _REPEAT.search(word)
            ):
                yield i, j
            i = max(j, i + 1)


# --- entry point ---------------------------------------------------------------------


def hints_for(text: str, dictionary: Dictionary) -> tuple[Hint, ...]:
    ctx = Context(text, segment(text, candidate_sheet(text, dictionary)), dictionary)
    found = {
        Hint(category, start, end)
        for category, find in DETECTORS.items()
        for start, end in find(ctx)
        if 0 <= start < end <= len(text)
    }
    return tuple(sorted(found, key=lambda h: (h.start, h.end, h.category)))


def tag(sentence: Sentence, dictionary: Dictionary) -> Sentence:
    """The sentence with the tagger's hints added to any it already declares.

    A synthetic sentence declares the category it was written for, which the
    tagger may not see (an OOV word in hiragana).
    """
    found = set(sentence.hints) | set(hints_for(sentence.text, dictionary))
    return replace(sentence, hints=tuple(sorted(found, key=lambda h: (h.start, h.end, h.category))))

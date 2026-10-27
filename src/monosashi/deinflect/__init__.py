"""Deinflection: where an inflection chain ends, and what it deinflects to.

SPEC.md makes the vendored Yomitan rule table the authority on chains: a unit's
chain is the transform path that turns its surface back into its dictionary
form. Supplements sit on top of the vendored table where the owner's unit rules
put a form inside the chain and the table has no transform for it: て + an
auxiliary verb (みる, くる, いく, ある, あげる, くれる, もらう, ほしい), modelled on the
table's own ``-いる`` rules, and a few Kansai and colloquial forms. Each
supplement is listed in SPEC.md §4.1 so the rule set stays explicit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from monosashi.deinflect._vendor.engine import Deinflector, conditions_match_mask
from monosashi.deinflect._vendor.transforms import CONDITIONS, TRANSFORMS, suffix_inflection


def _te(auxiliaries: list[str], condition: str) -> list[dict[str, Any]]:
    """て / で + each spelling of an auxiliary, back to the te-form.

    ``condition`` is the auxiliary's own conjugation class, so the table's rules
    go on past it: 見せてもらった is ``-て, -もらう, -た``.
    """
    return [
        suffix_inflection(te + aux, te, [condition], ["-て"]) for aux in auxiliaries for te in ("て", "で")
    ]


SUPPLEMENT_TRANSFORMS: list[dict[str, Any]] = [
    {"id": "-みる", "name": "-みる", "rules": _te(["みる"], "v1")},
    {"id": "-くる", "name": "-くる", "rules": _te(["くる", "来る"], "vk")},
    {
        "id": "-いく",
        "name": "-いく",
        "rules": [
            *_te(["いく", "行く", "ゆく"], "v5"),
            # Contracted いく. The table's -た undoes った to く only for 行く itself,
            # so てった is listed whole, and so is てってる, with the table's てる
            # condition v1p: the continuative reads 待ってって as 待ってってる with
            # v1d, which must not match. A bare てって is not listed: it would read
            # the quotative って after a te-form (待ってって) as part of the verb.
            *_te(["く"], "v5"),
            *_te(["った"], "-た"),
            *_te(["ってる"], "v1p"),
        ],
    },
    {"id": "-ある", "name": "-ある", "rules": _te(["ある"], "v5")},
    {"id": "-あげる", "name": "-あげる", "rules": _te(["あげる", "上げる"], "v1")},
    {"id": "-くれる", "name": "-くれる", "rules": _te(["くれる", "呉れる"], "v1")},
    {"id": "-もらう", "name": "-もらう", "rules": _te(["もらう", "貰う"], "v5")},
    {"id": "-ほしい", "name": "-ほしい", "rules": _te(["ほしい", "欲しい"], "adj-i")},
    {
        # Kansai る -> ん before ねん / の: わかんねん, 何すんねん. Godan and する only:
        # an ichidan 見ん is the table's negative.
        "id": "-ん (kansai)",
        "name": "-ん (kansai)",
        "rules": [
            suffix_inflection("ん", "る", [], ["v5"]),
            suffix_inflection("すん", "する", [], ["vs"]),
        ],
    },
    {
        # The Kansai adjective negative without く (おもろない). Only ろない, so that
        # 少ない never reads as a negative of its search-only spelling 少い.
        "id": "-ない (kansai)",
        "name": "-ない (kansai)",
        "rules": [suffix_inflection("ろない", "ろい", ["adj-i"], ["adj-i"])],
    },
    {
        "id": "volitional (short)",
        "name": "volitional (short)",
        "rules": [
            suffix_inflection("こよ", "くる", [], ["vk"]),
            suffix_inflection("しよ", "する", [], ["vs"]),
        ],
    },
    {
        # やがる after a contracted stem (行きゃがる), mirroring the table's -やがる.
        "id": "-ゃがる",
        "name": "-ゃがる",
        "rules": [
            suffix_inflection("きゃがる", "く", ["v5"], ["v5"]),
            suffix_inflection("ぎゃがる", "ぐ", ["v5"], ["v5"]),
            suffix_inflection("しゃがる", "す", ["v5"], ["v5"]),
            suffix_inflection("ちゃがる", "つ", ["v5"], ["v5"]),
            suffix_inflection("にゃがる", "ぬ", ["v5"], ["v5"]),
            suffix_inflection("びゃがる", "ぶ", ["v5"], ["v5"]),
            suffix_inflection("みゃがる", "む", ["v5"], ["v5"]),
            suffix_inflection("りゃがる", "る", ["v5"], ["v5"]),
            suffix_inflection("しゃがる", "する", ["v5"], ["vs"]),
            suffix_inflection("きゃがる", "くる", ["v5"], ["vk"]),
        ],
    },
    {
        # The table's continuative needs a kana before る (食べ -> 食べる), so a one-kanji
        # ichidan stem never reaches its verb: 見 in 見ながら. Listed by kanji, as the table
        # lists 来 for 来る: the one-kanji ichidan verbs whose spelling JMdict marks common.
        "id": "continuative (kanji stem)",
        "name": "continuative (kanji stem)",
        "rules": [suffix_inflection(k, k + "る", [], ["v1d"]) for k in "似出寝射居干得煮看着経見観診鋳"],
    },
]

# JMdict POS tag of an entry whose headword itself inflects -> Yomitan
# dictionary-form condition. The coarse conditions cover their subclasses through
# the table's subConditions, so every modern godan class maps to v5. Archaic
# classes (v2*, v4*, v5uru, vs-c, vn, vr) have no transforms and stay unmapped.
_POS_TO_CONDITION: dict[str, str] = {
    "v1": "v1",
    "v1-s": "v1",
    **{tag: "v5" for tag in ("v5aru", "v5b", "v5g", "v5k", "v5k-s", "v5m", "v5n", "v5r", "v5r-i")},
    **{tag: "v5" for tag in ("v5s", "v5t", "v5u", "v5u-s")},
    "vk": "vk",
    "vs-i": "vs",
    "vs-s": "vs",
    "vz": "vz",
    "adj-i": "adj-i",
    "adj-ix": "adj-i",
}

# A plain "vs" tag marks a noun that takes する (勉強). Its headword does not
# inflect, but its units deinflect to headword + する.
NOUN_SURU_TAG = "vs"
SURU = "する"


@dataclass(frozen=True, slots=True)
class Deinflection:
    """One candidate: the text a surface deinflects to, and the chain that gets there.

    ``chain`` lists transform ids in attachment order, dictionary form outward:
    始めてしまった gives ``("-て", "-しまう", "-た")``. The identity result has an
    empty chain.
    """

    text: str
    conditions: int
    chain: tuple[str, ...]


@lru_cache(maxsize=1)
def _deinflector() -> Deinflector:
    return Deinflector(CONDITIONS, [*TRANSFORMS, *SUPPLEMENT_TRANSFORMS])


# Transforms that strip て + an auxiliary verb, leaving the te-form (SPEC.md §4.1).
_TE_AUXILIARY_IDS = frozenset(
    {
        "-いる",
        "-しまう",
        "-おく",
        "-みる",
        "-くる",
        "-いく",
        "-ある",
        "-あげる",
        "-くれる",
        "-もらう",
        "-ほしい",
    }
)


def stops_at_te_auxiliary(chain: tuple[str, ...], conditions: int) -> bool:
    """Whether a chain strips て + an auxiliary and stops at the bare te-form (としてくれる -> として).

    That is no inflection of an exp-only entry ending in て or で: the auxiliary is
    a unit of its own (SPEC.md §4.3). The auxiliary may sit anywhere in the
    chain, since the Kansai te-form rules map a te-form to a te-form after it
    (に沿うている -> に沿うて -> に沿って). With no auxiliary stripped, a te-form
    variant still counts: Kansai に沿うて is に沿って by ``kansai-ben -て``.
    """
    return conditions == _deinflector().condition_flags("-て") and any(t in _TE_AUXILIARY_IDS for t in chain)


def transform_ids() -> frozenset[str]:
    """Every transform id a chain may contain."""
    return frozenset(str(t["id"]) for t in [*TRANSFORMS, *SUPPLEMENT_TRANSFORMS])


@lru_cache(maxsize=65536)
def deinflect(surface: str) -> tuple[Deinflection, ...]:
    """All deinflection candidates for ``surface``, the identity first."""
    results = _deinflector().transform(surface)
    return tuple(
        Deinflection(r.text, r.conditions, tuple(frame[0] for frame in reversed(r.trace))) for r in results
    )


def pos_condition_flags(pos_tags: Iterable[str]) -> int:
    """Condition mask for an entry's JMdict POS tags; 0 when its headword never inflects."""
    deinflector = _deinflector()
    flags = 0
    for tag in pos_tags:
        condition = _POS_TO_CONDITION.get(tag)
        if condition is not None:
            flags |= deinflector.condition_flags(condition)
    return flags


def reach(
    surface: str, spellings: Iterable[str], pos_tags: Iterable[str]
) -> dict[str, list[tuple[str, ...]]]:
    """Which of an entry's ``spellings`` ``surface`` reaches, and by which chains.

    The identity (``surface`` is the spelling) yields the empty chain. Otherwise
    a chain counts only when its final conditions fit the entry's POS, as in
    Yomitan's lookup. A noun tagged vs is also reached through する: bare
    (勉強する, empty chain) or inflected (勉強している -> 勉強).

    JMdict tags some inflecting expressions only ``exp`` (かもしれない), which
    gives no condition to check; for those any chain reaching the spelling counts,
    except one that strips て + an auxiliary and stops at the te-form
    (``stops_at_te_auxiliary``), so として|くれる and 一人で|いる stay two units.
    """
    targets = set(spellings)
    tags = tuple(pos_tags)
    flags = pos_condition_flags(tags)
    suru_flags = _deinflector().condition_flags("vs") if NOUN_SURU_TAG in tags else 0
    exp_only = not flags and "exp" in tags
    found: dict[str, list[tuple[str, ...]]] = {}
    for result in deinflect(surface):
        noun = result.text[: -len(SURU)] if suru_flags and result.text.endswith(SURU) else None
        if not result.chain:
            if result.text in targets:
                found.setdefault(result.text, []).append(())
            elif noun in targets:
                found.setdefault(noun, []).append(())
            continue
        if result.text in targets and (
            (exp_only and not stops_at_te_auxiliary(result.chain, result.conditions))
            or (flags and conditions_match_mask(result.conditions, flags))
        ):
            found.setdefault(result.text, []).append(result.chain)
        elif noun is not None and noun in targets and conditions_match_mask(result.conditions, suru_flags):
            found.setdefault(noun, []).append(result.chain)
    return found


def chains_to(surface: str, form: str, pos_tags: Iterable[str]) -> list[tuple[str, ...]]:
    """Chains that turn ``surface`` into ``form`` for an entry with ``pos_tags`` (see ``reach``)."""
    return reach(surface, [form], pos_tags).get(form, [])

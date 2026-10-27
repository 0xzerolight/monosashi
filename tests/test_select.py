"""Pool filters and the stratified selection, on synthetic sentences."""

from __future__ import annotations

from collections import Counter

import pytest

from monosashi.pool import build_pool, usable
from monosashi.schema import Source
from monosashi.select import (
    EXCLUDED_IDS,
    MAX_PER_SURFACE,
    MAX_PER_WORK,
    PLAIN_SHARE,
    TATOEBA_CONTRIBUTOR_SHARE,
    _group,
    select,
    summary,
)
from monosashi.sources import Hint, Sentence


def _s(
    sid: str,
    text: str,
    *hints: tuple[str, int, int],
    corpus: str = "tatoeba",
    slice_: str = "open",
    ref: str | None = None,
    attribution: str | None = None,
) -> Sentence:
    if attribution is None:  # a Tatoeba record needs its owner; by default each has its own
        attribution = (
            f"Tatoeba sentence #{sid} by {sid} (export v)" if corpus == "tatoeba" else "monosashi tests"
        )
    return Sentence(
        id=sid,
        text=text,
        source=Source(corpus, ref or sid, "CC-BY-SA-4.0", attribution),
        register="conversation",
        slice=slice_,
        hints=tuple(Hint(c, a, b) for c, a, b in hints),
    )


def _tatoeba(i: int, owner: str, *hints: tuple[str, int, int]) -> Sentence:
    attribution = f"Tatoeba sentence #{i} by {owner} (export 2026-10-10)"
    return _s(f"tat-{i}", f"食べた{i:04d}", *hints, ref=str(i), attribution=attribution)


def _mixed_pool() -> list[Sentence]:
    """Hinted records in every corpus, and hint-free ones in open text, seeds and synthetic."""
    seeds = {"ichiran", "jiten", "anki_miner"}
    pool = []
    for c in ["tatoeba", "aozora", "ud-gsd", "ichiran", "jiten", "anki_miner", "synthetic"]:
        slice_ = "seed" if c in seeds else "synthetic" if c == "synthetic" else "open"
        for i in range(100):
            text = f"食べた{c}{i:03d}"
            hints = [("heteronym", 0, len(text))] if i < 60 else []
            attribution = f"Tatoeba sentence #{i} by user{i % 9} (export v)" if c == "tatoeba" else "x"
            ref = f"{i % 25}:1:{i}" if c == "aozora" else None
            pool.append(
                _s(f"{c}-{i}", text, *hints, corpus=c, slice_=slice_, ref=ref, attribution=attribution)
            )
    return pool


def test_usable_filters_length_and_script() -> None:
    assert usable(_s("a", "食べてしまった"))
    assert not usable(_s("b", "食べ"))  # too short for open text
    assert usable(_s("c", "食べ", slice_="seed"))  # seeds may be short
    assert not usable(_s("d", "Hello world, 世界"))
    assert not usable(_s("e", "あ" * 61))


def test_build_pool_drops_duplicates_keeping_the_first() -> None:
    first = _s("seed-1", "食べてしまった", corpus="ichiran", slice_="seed")
    again = _s("tat-1", "食べてしまった")
    other = _s("tat-2", "寝てしまった")
    assert [s.id for s in build_pool([[first], [again, other]])] == ["seed-1", "tat-2"]


def test_quotas_are_met_and_reserve_is_disjoint() -> None:
    pool = [_s(f"t{i}", f"食べた{i:03d}", ("heteronym", 0, 3 + i % 4)) for i in range(200)]
    sel = select(pool, quota=10, reserve_per_category=2, target_core=40)
    core_ids = {s.id for s in sel.core}
    assert len(sel.core) >= 10
    assert sum("heteronym" in s.categories for s in sel.reserve) == 2
    assert not core_ids & {s.id for s in sel.reserve}


def test_one_surface_cannot_fill_a_category() -> None:
    pool = [_s(f"t{i}", f"何{i:03d}", ("heteronym", 0, 1)) for i in range(20)]
    sel = select(pool, quota=5, reserve_per_category=0, target_core=20)
    assert len(sel.core) == MAX_PER_SURFACE
    assert sel.deficits["heteronym"] == 5 - MAX_PER_SURFACE


def test_synthetic_only_fills_what_real_text_cannot() -> None:
    real = [_s(f"t{i}", f"食べた{i:02d}", ("compound", 0, 3 + i % 3)) for i in range(12)]
    synthetic = [
        _s(f"syn{i}", f"やねん{i:02d}", ("kansai", 0, 3 + i % 3), ("compound", 0, 5), corpus="synthetic",
           slice_="synthetic")
        for i in range(12)
    ]  # fmt: skip
    sel = select(real + synthetic, quota=3, reserve_per_category=0, target_core=12)
    picked = [s for s in sel.core if s.slice == "synthetic"]
    assert len(picked) == 3
    assert all("kansai" in s.categories for s in picked)


def test_a_corpus_stays_near_its_share() -> None:
    pool = [_s(f"t{i}", f"食べた{i:03d}", ("heteronym", 0, 3 + i % 4)) for i in range(200)]
    sel = select(pool, quota=50, reserve_per_category=0, target_core=10)
    assert len(sel.core) <= 4  # tatoeba's 30% of 10, with the overflow allowance


def test_selection_is_deterministic() -> None:
    first = select(_mixed_pool(), quota=5, reserve_per_category=1, target_core=200)
    again = select(_mixed_pool(), quota=5, reserve_per_category=1, target_core=200)
    assert first == again


def test_the_plain_slice_is_hint_free_open_text() -> None:
    pool = _mixed_pool()
    sel = select(pool, quota=5, reserve_per_category=0, target_core=200)
    plain = [s for s in sel.core if s.slice == "plain"]
    assert len(sel.core) == 200 and len(plain) == round(PLAIN_SHARE * 200)
    by_id = {s.id: s for s in pool}
    # Picked from open text with no hints; no seed or synthetic sentence is ever plain.
    assert all(not s.hints and by_id[s.id].slice == "open" and not by_id[s.id].hints for s in plain)
    assert {s.id for s in sel.core if not s.hints} == {s.id for s in plain}
    report = summary(sel)
    assert report.startswith("Core: 200 records. Reserve:")
    assert "| plain | 20 |" in report
    group, n = Counter(g for g in map(_group, sel.core) if g).most_common(1)[0]
    assert f"| {group} | {n} |" in report.split("| largest groups |")[1]


def test_group_names_the_contributor_or_the_work() -> None:
    assert _group(_tatoeba(1, "small_snow")) == "tatoeba:small_snow"
    assert _group(_s("aoz-1", "食べた", corpus="aozora", ref="789:518:10")) == "aozora:789"
    assert _group(_s("ud-1", "食べた", corpus="ud-gsd")) is None
    # A Tatoeba record with no owner would escape the cap.
    with pytest.raises(ValueError, match="no Tatoeba owner"):
        _group(_s("tat-1", "食べた", attribution="Tatoeba sentence #1"))


def test_no_tatoeba_contributor_passes_a_fifth_of_tatoeba() -> None:
    # Half the pool is one contributor's.
    pool = [_tatoeba(i, "small_snow" if i % 2 else f"user{i % 7}", ("heteronym", 0, 7)) for i in range(300)]
    sel = select(pool, quota=50, reserve_per_category=0, target_core=60)
    owners = Counter(_group(s) for s in sel.core)
    assert sum(owners.values()) >= 10
    assert max(owners.values()) <= TATOEBA_CONTRIBUTOR_SHARE * sum(owners.values())


def test_caps_hold_across_core_and_reserve() -> None:
    # One work and one contributor supply most of their corpus; the reserve must not add to them.
    aozora = [
        _s(
            f"aoz-{i}",
            f"食べた{i:03d}",
            ("heteronym", 0, 6),
            corpus="aozora",
            ref=f"{789 if i < 150 else i}:1:{i}",
        )
        for i in range(200)
    ]
    tatoeba = [
        _tatoeba(i, "small_snow" if i % 2 else f"user{i % 7}", ("heteronym", 0, 7)) for i in range(300)
    ]
    sel = select(aozora + tatoeba, quota=50, reserve_per_category=20, target_core=150, reserve_share=0.5)
    both = sel.core + sel.reserve
    groups = Counter(_group(s) for s in both)
    assert groups["aozora:789"] == MAX_PER_WORK
    assert max(n for g, n in groups.items() if g and g.startswith("aozora:")) <= MAX_PER_WORK
    owners = [n for g, n in groups.items() if g and g.startswith("tatoeba:")]
    assert max(owners) <= TATOEBA_CONTRIBUTOR_SHARE * sum(owners)


def test_the_contributor_cap_holds_when_tatoeba_falls_short() -> None:
    # 90 of 100 records are one contributor's, so Tatoeba cannot fill its share of the core.
    pool = [_tatoeba(i, "small_snow" if i < 90 else f"user{i}", ("heteronym", 0, 7)) for i in range(100)]
    sel = select(pool, quota=50, reserve_per_category=0, target_core=100)
    owners = Counter(_group(s) for s in sel.core + sel.reserve)
    assert sum(owners.values()) >= 10
    assert owners["tatoeba:small_snow"] <= TATOEBA_CONTRIBUTOR_SHARE * sum(owners.values())
    assert summary(sel).startswith(
        f"Core: {len(sel.core)} records ({100 - len(sel.core)} short of the target of 100)"
    )


def test_no_aozora_work_passes_ten_records() -> None:
    pool = [
        _s(
            f"aoz-{i}",
            f"食べた{i:03d}",
            ("heteronym", 0, 6),
            corpus="aozora",
            ref=f"{789 if i < 150 else i}:1:{i}",
        )
        for i in range(200)
    ]
    sel = select(pool, quota=50, reserve_per_category=0, target_core=200)
    works = Counter(_group(s) for s in sel.core)
    assert works["aozora:789"] == MAX_PER_WORK
    assert max(works.values()) <= MAX_PER_WORK


def test_excluded_records_are_never_selected() -> None:
    assert "tat-769311" in EXCLUDED_IDS  # the iroha poem written without dakuten
    pool = [_s("tat-769311", "いろはにほへと", ("archaic-classical", 0, 3))]
    pool += [_s(f"t{i}", f"食べた{i:03d}", ("archaic-classical", 0, 6)) for i in range(5)]
    sel = select(pool, quota=10, reserve_per_category=2, target_core=10)
    assert "tat-769311" not in {s.id for s in sel.core + sel.reserve}


def test_the_core_reaches_its_target_when_real_text_allows() -> None:
    corpora = ["tatoeba", "aozora", "ud-gsd", "ichiran", "jiten", "anki_miner"]
    pool = [
        _s(f"{c}-{i}", f"食べた{c}{i:03d}", ("heteronym", 0, len(f"食べた{c}{i:03d}")), corpus=c)
        for c in corpora
        for i in range(100)
    ]
    sel = select(pool, quota=5, reserve_per_category=0, target_core=200)
    assert len(sel.core) == 200  # synthetic took none of its share, so real corpora fill it
    assert len(sel.reserve) == 20  # 10% of the core
    assert all(n > 0 for n in sel.deficits.values())


def test_oov_draws_synthetic_sentences_first() -> None:
    real = [_s(f"t{i}", f"ゼーロン{i:02d}", ("oov", 0, 6)) for i in range(10)]
    synthetic = [
        _s(f"syn{i}", f"ググってみた{i:02d}", ("oov", 0, 8), corpus="synthetic", slice_="synthetic")
        for i in range(10)
    ]
    sel = select(real + synthetic, quota=2, reserve_per_category=0, target_core=8)
    # The quota of 2 is met from synthetic text; real text only tops the core up afterwards.
    assert sum(s.slice == "synthetic" for s in sel.core) == 2

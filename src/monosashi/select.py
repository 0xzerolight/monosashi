"""Stratified selection: the candidate set labeling starts from.

Records in ``EXCLUDED_IDS`` never enter. Every category gets ``QUOTA`` records,
scarcest category first, so rare categories are not crowded out by common ones.
Each corpus has a share of the core (``CORPUS_SHARES``), which keeps registers
and source slices balanced: the draw always prefers the corpus furthest below
its share, then the record that helps the most categories still under quota.
Synthetic sentences come last and fill only what real text cannot. A record
picked for a category may not repeat a target surface already picked
``MAX_PER_SURFACE`` times for it, so 何 cannot fill the heteronym quota on its
own (a record picked for another category may still bring 何 along). No Tatoeba
contributor supplies more than ``TATOEBA_CONTRIBUTOR_SHARE`` of the Tatoeba
records, and no Aozora work more than ``MAX_PER_WORK``, across the core and the
reserve together, so a record swapped in from the reserve keeps both caps. The
contributor cap is a share of the Tatoeba records there is room for; when
Tatoeba falls short of that room, the draw is repeated with the count it reached.

After the quotas comes the plain slice: ``PLAIN_SHARE`` of the core drawn from
open text the tagger found nothing in, a baseline for ordinary sentences. Those
records carry slice ``plain``. The core is then topped up to ``TARGET_CORE``
from real text, the real corpora sharing whatever synthetic text did not need.
A reserve of ``RESERVE_SHARE`` of the core, at least ``RESERVE_PER_CATEGORY``
per category, is set aside for records labeling drops.

A record counts toward every category it has a hint for. The draw is
deterministic for a given pool and seed.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from monosashi.sources import Sentence
from monosashi.taxonomy import CATEGORIES

QUOTA = 35
RESERVE_PER_CATEGORY = 4
RESERVE_SHARE = 0.10
TARGET_CORE = 1000
MAX_PER_SURFACE = 2
PLAIN_SHARE = 0.10
TATOEBA_CONTRIBUTOR_SHARE = 0.20
MAX_PER_WORK = 10
SELECT_SEED = 20261015
# The iroha poem written without dakuten: every unit would be a workaround.
EXCLUDED_IDS = frozenset({"tat-769311"})
# Shares of the core by corpus: about 60% open text, 30% seeds, and at most 25%
# synthetic. They overlap on purpose: synthetic only fills deficits, so real
# text has room to reach the target without it.
CORPUS_SHARES = {
    "tatoeba": 0.30,
    "aozora": 0.15,
    "ud-gsd": 0.15,
    "anki_miner": 0.08,
    "ichiran": 0.11,
    "jiten": 0.11,
    "synthetic": 0.25,
}
# A category with no candidate left under its corpus's share may go this far over it.
OVERFLOW = 1.25
# Categories whose detector is unreliable on real text draw synthetic sentences first:
# a katakana run with no JMdict entry in open text is nearly always a foreign name.
SYNTHETIC_FIRST = frozenset({"oov"})


@dataclass
class _State:
    caps: Mapping[str, int]
    chosen: dict[str, Sentence] = field(default_factory=dict)
    categories: Counter[str] = field(default_factory=Counter)
    surfaces: Counter[tuple[str, str]] = field(default_factory=Counter)
    corpora: Counter[str] = field(default_factory=Counter)
    groups: Counter[str] = field(default_factory=Counter)  # records per contributor or work
    # The reserve's caps count the core too: its Tatoeba records, and its groups above.
    tatoeba_before: int = 0
    # A smaller Tatoeba room, from an earlier draw that fell short of the planned one.
    room_limit: int | None = None

    def add(self, s: Sentence) -> None:
        self.chosen[s.id] = s
        self.categories.update(s.categories)
        self.surfaces.update({(h.category, s.text[h.start : h.end]) for h in s.hints})
        self.corpora[_corpus(s)] += 1
        group = _group(s)
        if group is not None:
            self.groups[group] += 1

    def load(self, s: Sentence) -> float:
        return self.corpora[_corpus(s)] / max(self.caps.get(_corpus(s), 1), 1)

    def fits_group(self, s: Sentence) -> bool:
        """Whether ``s`` keeps its contributor or work within its cap."""
        group = _group(s)
        if group is None:
            return True
        if group.startswith("aozora:"):
            return self.groups[group] < MAX_PER_WORK
        # A share of the Tatoeba records there is room for, or of those taken when Tatoeba overflows.
        taken = self.tatoeba_before + self.corpora["tatoeba"]
        planned = self.tatoeba_before + self.caps.get("tatoeba", 0)
        if self.room_limit is not None:
            planned = min(planned, self.room_limit)
        return self.groups[group] + 1 <= max(1, TATOEBA_CONTRIBUTOR_SHARE * max(taken + 1, planned))


@dataclass(frozen=True)
class Selection:
    core: list[Sentence]
    reserve: list[Sentence]
    # Records each category still needs to reach QUOTA + RESERVE_PER_CATEGORY.
    deficits: dict[str, int]
    target_core: int = TARGET_CORE


def _corpus(s: Sentence) -> str:
    return "synthetic" if s.slice == "synthetic" else s.source.corpus


_TATOEBA_OWNER = re.compile(r" by (.+) \(export ")


def _group(s: Sentence) -> str | None:
    """The contributor or work a record comes from: ``tatoeba:<owner>``, ``aozora:<work>``, else None.

    The owner is read from the attribution ``tatoeba.py`` writes; the work is the
    first field of an Aozora ref (``789:518:10`` is card 789). A Tatoeba record
    without an owner is an error: it would escape the contributor cap.
    """
    if s.source.corpus == "tatoeba":
        m = _TATOEBA_OWNER.search(s.source.attribution)
        if m is None:
            raise ValueError(f"{s.id}: no Tatoeba owner in {s.source.attribution!r}")
        return f"tatoeba:{m.group(1)}"
    if s.source.corpus == "aozora":
        return f"aozora:{s.source.ref.split(':')[0]}"
    return None


def _caps(total: int) -> dict[str, int]:
    return {corpus: math.ceil(share * total) for corpus, share in CORPUS_SHARES.items()}


def _surfaces(s: Sentence, category: str) -> set[str]:
    return {s.text[h.start : h.end] for h in s.hints if h.category == category}


def _pick(
    category: str | None,
    candidates: Sequence[Sentence],
    state: _State,
    taken: Mapping[str, Sentence],
    quota: int | None,
    *,
    allow_synthetic: bool,
    overflow: float = 1.0,
) -> Sentence | None:
    """The best next record for ``category`` (None for the plain slice), within every cap."""
    best: tuple[object, ...] | None = None
    choice = None
    for order, s in enumerate(candidates):
        if s.id in taken or (s.slice == "synthetic" and not allow_synthetic):
            continue
        load = state.load(s)
        if load >= overflow or not state.fits_group(s):
            continue
        if category is not None and any(
            state.surfaces[(category, x)] >= MAX_PER_SURFACE for x in _surfaces(s, category)
        ):
            continue
        useful = 0 if quota is None else sum(1 for c in s.categories if state.categories[c] < quota)
        # Quartiles of the corpus's share first, so a record that helps many
        # categories cannot keep drawing from one corpus.
        synthetic_rank = (s.slice != "synthetic") if category in SYNTHETIC_FIRST else (s.slice == "synthetic")
        key = (synthetic_rank, math.floor(load * 4), -useful, order)
        if best is None or key < best:
            best, choice = key, s
    return choice


def _fill(
    order: Sequence[str],
    by_category: Mapping[str, Sequence[Sentence]],
    state: _State,
    taken: Mapping[str, Sentence],
    quota: int,
) -> None:
    for category in order:
        while state.categories[category] < quota:
            s = _pick(category, by_category[category], state, taken, quota, allow_synthetic=True)
            if s is None:
                s = _pick(
                    category,
                    by_category[category],
                    state,
                    taken,
                    quota,
                    allow_synthetic=True,
                    overflow=OVERFLOW,
                )
            if s is None:
                break
            state.add(s)


def select(
    pool: Iterable[Sentence],
    *,
    quota: int = QUOTA,
    reserve_per_category: int = RESERVE_PER_CATEGORY,
    reserve_share: float = RESERVE_SHARE,
    target_core: int = TARGET_CORE,
    seed: int = SELECT_SEED,
    plain_share: float = PLAIN_SHARE,
) -> Selection:
    sentences = [s for s in pool if s.id not in EXCLUDED_IDS]
    rng = random.Random(seed)
    candidates = [s for s in sentences if s.hints]
    rng.shuffle(candidates)
    plain = [s for s in sentences if s.slice == "open" and not s.hints]
    rng.shuffle(plain)
    room_limit = None
    while True:
        selection = _draw(
            candidates,
            plain,
            quota=quota,
            reserve_per_category=reserve_per_category,
            reserve_share=reserve_share,
            target_core=target_core,
            plain_share=plain_share,
            room_limit=room_limit,
        )
        groups = map(_group, selection.core + selection.reserve)
        owners = Counter(g for g in groups if g is not None and g.startswith("tatoeba:"))
        tatoeba = sum(owners.values())
        if not owners or max(owners.values()) <= max(1, TATOEBA_CONTRIBUTOR_SHARE * tatoeba):
            return selection
        if room_limit == tatoeba:
            return selection  # fewer than five Tatoeba records: one each is as fair as it gets
        room_limit = tatoeba


def _draw(
    candidates: Sequence[Sentence],
    plain: Sequence[Sentence],
    *,
    quota: int,
    reserve_per_category: int,
    reserve_share: float,
    target_core: int,
    plain_share: float,
    room_limit: int | None,
) -> Selection:
    by_category: dict[str, list[Sentence]] = {c: [] for c in CATEGORIES}
    for s in candidates:
        for c in s.categories:
            by_category[c].append(s)
    order = sorted(CATEGORIES, key=lambda c: (len(by_category[c]), c))

    core = _State(caps=_caps(target_core), room_limit=room_limit)
    _fill(order, by_category, core, core.chosen, quota)
    # Real corpora share the room synthetic text did not take, in their own proportions.
    real = {c: v for c, v in CORPUS_SHARES.items() if c != "synthetic"}
    room = (target_core - core.corpora["synthetic"]) / (sum(real.values()) * target_core)
    core.caps = {**core.caps, **{c: math.ceil(v * target_core * room) for c, v in real.items()}}
    for _ in range(round(plain_share * target_core)):
        pick = _pick(None, plain, core, core.chosen, None, allow_synthetic=False)
        if pick is None:
            break
        core.add(replace(pick, slice="plain"))
    # Top up from real text: the least covered category first.
    while len(core.chosen) < target_core:
        for category in sorted(CATEGORIES, key=lambda c: (core.categories[c], c)):
            pick = _pick(category, by_category[category], core, core.chosen, None, allow_synthetic=False)
            if pick is not None:
                core.add(pick)
                break
        else:
            break

    reserve_size = max(round(reserve_share * len(core.chosen)), 1)
    reserve = _State(
        caps=_caps(reserve_size),
        groups=Counter(core.groups),
        tatoeba_before=core.corpora["tatoeba"],
        room_limit=room_limit,
    )
    taken = dict(core.chosen)
    for category in order:
        while reserve.categories[category] < reserve_per_category:
            pick = _pick(
                category, by_category[category], reserve, taken, None, allow_synthetic=True, overflow=10.0
            )
            if pick is None:
                break
            reserve.add(pick)
            taken[pick.id] = pick
    while len(reserve.chosen) < reserve_size:
        for category in sorted(CATEGORIES, key=lambda c: (reserve.categories[c], c)):
            pick = _pick(category, by_category[category], reserve, taken, None, allow_synthetic=False)
            if pick is not None:
                reserve.add(pick)
                taken[pick.id] = pick
                break
        else:
            break

    deficits = {
        c: max(0, quota - core.categories[c]) + max(0, reserve_per_category - reserve.categories[c])
        for c in CATEGORIES
    }
    deficits = {c: n for c, n in deficits.items() if n}
    return Selection(_ordered(core.chosen.values()), _ordered(reserve.chosen.values()), deficits, target_core)


def _ordered(sentences: Iterable[Sentence]) -> list[Sentence]:
    return sorted(sentences, key=lambda s: (s.slice, s.source.corpus, s.id))


LARGEST_GROUPS = 10


def summary(selection: Selection) -> str:
    """Markdown tables of the selection: per category and the plain slice, corpus, group and register."""
    core, reserve = selection.core, selection.reserve
    short = selection.target_core - len(core)
    shortfall = f" ({short} short of the target of {selection.target_core})" if short > 0 else ""
    lines = [f"Core: {len(core)} records{shortfall}. Reserve: {len(reserve)}.", ""]
    slices = sorted({s.slice for s in core})
    lines.append("| category | core | " + " | ".join(slices) + " | distinct targets | reserve | short by |")
    lines.append("|---" * (len(slices) + 5) + "|")
    for c in CATEGORIES:
        having = [s for s in core if c in s.categories]
        by_slice = Counter(s.slice for s in having)
        distinct = len({x for s in having for x in _surfaces(s, c)})
        in_reserve = sum(c in s.categories for s in reserve)
        cells = [str(len(having)), *(str(by_slice[x]) for x in slices), str(distinct), str(in_reserve)]
        lines.append(f"| {c} | " + " | ".join(cells) + f" | {selection.deficits.get(c, '')} |")
    plain = sum(s.slice == "plain" for s in core)
    cells = [str(plain), *(str(plain if x == "plain" else 0) for x in slices), "", "0"]
    lines.append("| plain | " + " | ".join(cells) + " |  |")
    lines += ["", "| corpus | core | reserve |", "|---|---|---|"]
    reserve_corpora = Counter(_corpus(s) for s in reserve)
    for corpus, n in Counter(_corpus(s) for s in core).most_common():
        lines.append(f"| {corpus} | {n} | {reserve_corpora[corpus]} |")
    lines += ["", "| largest groups | core | reserve |", "|---|---|---|"]
    core_groups = Counter(g for g in map(_group, core) if g is not None)
    reserve_groups = Counter(g for g in map(_group, reserve) if g is not None)
    for group, n in core_groups.most_common(LARGEST_GROUPS):
        lines.append(f"| {group} | {n} | {reserve_groups[group]} |")
    lines += ["", "| register | core |", "|---|---|"]
    for register, n in Counter(s.register for s in core).most_common():
        lines.append(f"| {register} | {n} |")
    return "\n".join(lines) + "\n"

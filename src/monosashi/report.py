"""Markdown tables from scored runs: overall, seed suites, by category, by register and by slice."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from monosashi import SPEC_VERSION
from monosashi.predictions import description_from_dict, load_predictions
from monosashi.schema import REGISTERS, SLICES, Record
from monosashi.score import (
    METRICS,
    Scorer,
    ToolScores,
    bootstrap,
    category_scores,
    coverage,
    paired_difference,
    score_tool,
    subset,
)
from monosashi.taxonomy import CATEGORIES

OVERALL = tuple(METRICS)
# Metrics whose overall cells carry a bootstrap interval: the headline, junk next to it, segmentation.
INTERVALS = ("card", "junk", "seg", "content")
BREAKDOWN = ("card", "reading_tiled", "form")
# How a tool was set up, where a reader needs it next to the numbers, by the name its
# adapter describes itself with. adapters/<name>/README.md has the detail.
NOTES = {
    "anki_miner": (
        "runs with four of its settings changed from the defaults: number + counter cards on, "
        "pre-noun adjectives and conjunctions mined, proper nouns and numerals not excluded"
    ),
    "jiten": (
        "the adapter widens ASCII digits before placing words (1人 as １人), which jiten.moe does not; "
        "runs without jiten.moe's corpus frequency ranks, which are not public"
    ),
}


def score_runs(scorer: Scorer, records: Sequence[Record], run_dirs: Sequence[Path]) -> list[ToolScores]:
    """Each run directory (describe.json + predictions.jsonl) scored against the same records."""
    out = []
    for run_dir in run_dirs:
        description = description_from_dict(
            json.loads((run_dir / "describe.json").read_text(encoding="utf-8"))
        )
        predictions = load_predictions(run_dir / "predictions.jsonl")
        out.append(score_tool(scorer, run_dir.name, description, records, predictions))
    return out


def _not_seed(record: Record) -> bool:
    """Seeds stay out of the overall rows: a tool's own test sentences can't judge it fairly."""
    return record.slice != "seed"


def _seed_suite(corpus: str) -> Callable[[Record], bool]:
    return lambda record: record.slice == "seed" and record.source.corpus == corpus


def _register(register: str) -> Callable[[Record], bool]:
    """Records of one register, seeds left out: a seed's register is its test suite's, not its text's."""
    return lambda record: record.register == register and _not_seed(record)


def _where(attribute: str, value: str) -> Callable[[Record], bool]:
    return lambda record: bool(getattr(record, attribute) == value)


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{100 * value:.1f}"


def _cell(tool: ToolScores, metric: str, ci: dict[str, dict[str, tuple[float, float]]]) -> str:
    value = tool.value(metric)
    if value is None:
        return "–"
    text = _pct(value)
    interval = ci.get(metric, {}).get(tool.name)
    if interval is not None:
        text += f" ({_pct(interval[0])}–{_pct(interval[1])})"
    cov = coverage(tool.total(), metric)
    if cov is not None:
        text += f" [{_pct(cov)}%]"
    return text


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _tally(values: Iterable[str]) -> str:
    """Each value with its count, most frequent first: 'open 314, synthetic 25'."""
    return ", ".join(f"{v} {n}" for v, n in sorted(Counter(values).items(), key=lambda kv: (-kv[1], kv[0])))


def _breakdown(
    title: str,
    groups: Sequence[tuple[str, Sequence[ToolScores]]],
    tools: Sequence[ToolScores],
    *,
    composition: bool = False,
) -> list[str]:
    """One row per non-empty group, a BREAKDOWN cell per tool; ``composition`` adds its slices and sources."""
    lines = ["", f"## {title}", "", f"Each cell: {', '.join(METRICS[m] for m in BREAKDOWN)}.", ""]
    rows = []
    for name, scored in groups:
        records = scored[0].records
        if not records:
            continue
        extra = (
            [_tally(r.slice for r in records), _tally(r.source.corpus for r in records)]
            if composition
            else []
        )
        rows.append(
            [
                f"{name} ({len(records)})",
                *extra,
                *(" / ".join(_pct(s.value(m)) for m in BREAKDOWN) for s in scored),
            ]
        )
    header = ["", *(["slices", "sources"] if composition else []), *(t.name for t in tools)]
    return lines + _table(header, rows)


def render(scorer: Scorer, tools: Sequence[ToolScores], *, samples: int = 1000) -> str:
    if not tools:
        return "No runs.\n"
    records = tools[0].records
    seeds = [r for r in records if r.slice == "seed"]
    lines = [f"# Results (spec {SPEC_VERSION})", ""]
    lines += [f"Gold records: {len(records)}. Seeds: {len(seeds)}, left out of Overall and scored by suite. "
             "Percentages; 95% bootstrap intervals in parentheses; coverage of exact or tiled spans in "
             "brackets. Median ms is measured inside each adapter, overhead included.", ""]  # fmt: skip

    lines += ["## Tools", ""]
    lines += _table(
        [
            "tool",
            "version",
            "dictionary",
            "date",
            "partition",
            "fields",
            "records ok / repaired / garbled / failed",
            "notes",
        ],
        [
            [
                t.name,
                t.description.version,
                t.description.dictionary,
                t.description.dictionary_date,
                "yes" if t.description.partition else "no",
                ", ".join(t.description.fields),
                " / ".join(str(t.statuses()[s]) for s in ("ok", "repaired", "garbled"))
                + f" / {t.statuses()['crash'] + t.statuses()['timeout'] + t.statuses()['missing']}",
                NOTES.get(t.description.name, ""),
            ]
            for t in tools
        ],
    )

    overall = [subset(t, _not_seed) for t in tools]
    lines += ["", "## Overall", ""]
    if not overall[0].records:
        lines.append("No non-seed records.")
    else:
        lines += [f"{len(overall[0].records)} records, seeds left out.", ""]
        lines += _overall(overall, samples)

    if seeds:
        suites = sorted({r.source.corpus for r in seeds})
        lines += _breakdown(
            "Seed suites", [(c, [subset(t, _seed_suite(c)) for t in tools]) for c in suites], tools
        )
    else:
        lines += ["", "## Seed suites", "", "No seed records."]
    lines += _breakdown(
        "By category (target units only)",
        [(c, [category_scores(scorer, t, c) for t in tools]) for c in CATEGORIES],
        tools,
    )
    lines += _breakdown(
        "By register (seeds left out)",
        [(r, [subset(t, _register(r)) for t in tools]) for r in sorted(REGISTERS)],
        tools,
        composition=True,
    )
    lines += _breakdown(
        "By slice", [(s, [subset(t, _where("slice", s)) for t in tools]) for s in sorted(SLICES)], tools
    )
    return "\n".join(lines) + "\n"


def _overall(tools: Sequence[ToolScores], samples: int) -> list[str]:
    """The overall table, best card-ready rate first, and the top two tools' paired difference."""
    ci = {m: bootstrap(tools, m, samples) for m in INTERVALS}
    header = ["tool", *(METRICS[m] for m in OVERALL), "entry ids not in the pin", "median ms"]
    rows = []
    for t in sorted(tools, key=lambda t: -(t.value("card") or -1)):
        ms = t.median_ms()
        rows.append(
            [
                t.name,
                *(_cell(t, m, ci) for m in OVERALL),
                str(t.total()["entry.mismatch"]) if "entries" in t.description.fields else "–",
                "–" if ms is None else f"{ms:.2f}",
            ]
        )
    lines = _table(header, rows)

    ranked = sorted((t for t in tools if t.value("card") is not None), key=lambda t: -(t.value("card") or 0))
    if len(ranked) >= 2:
        diff = paired_difference(ranked[0], ranked[1], "card", samples)
        if diff is not None:
            lines += [
                "",
                f"Card-ready, {ranked[0].name} minus {ranked[1].name}: {_pct(diff[0])} to {_pct(diff[1])} points (95%).",
            ]
    return lines

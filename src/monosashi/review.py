"""The owner's review loop over the queue: one prompt per disputed unit.

    monosashi review RUN [--tools RUN_DIR ...] [--recheck-tags N]

Each item shows the sentence with the region marked, labeler A's and B's units
for it, each entry id with a spelling and its first gloss, and, when run
directories are given, how each tool split the sentence, named only "oracle
1..n" so no tool's name sways the call. Every answer is appended to the
decisions file at once, with the seconds it took, so the loop can stop and
resume anywhere and the pilot can measure review time.

Items a tag agent decided (``decisions-tags-*.jsonl``) are skipped;
``--recheck-tags N`` shows N of those ``targets`` items too, drawn by a hash
of their ids, and the owner's answer overrides the agent's.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from monosashi.jmdict import JMDICT, JMNEDICT, Dictionary
from monosashi.label.compare import QueueItem, rank
from monosashi.label.merge import (
    OK_ITEMS,
    Decision,
    decision_from_dict,
    load_decisions,
    load_tag_decisions,
    merge_record,
    merge_units,
)
from monosashi.predictions import Prediction, load_predictions
from monosashi.schema import Record, SchemaError, unit_to_dict
from monosashi.validate import validate_record

HELP = "[a] take A  [b] take B  [o] ok as is  [e] edit (JSON units)  [f] flag a spec question  [s] skip  [q] quit"


def _entry_label(seq: int, form: str | None, dictionary: Dictionary | None, source: str) -> str:
    """``1307550 (始める: to start …)``: the id with the unit's form, when it is a spelling of
    the entry, or else the entry's first spelling, and the first gloss; "…" marks more glosses."""
    entry = dictionary.entry(seq, source) if dictionary is not None else None
    glosses = [g for sense in entry.senses for g in sense.glosses] if entry is not None else []
    if entry is None or not glosses:
        return str(seq)
    spelling = form if form and entry.has_spelling(form) else (entry.kanji or entry.kana)[0]
    more = " …" if len(glosses) > 1 else ""
    return f"{seq} ({spelling}: {glosses[0]}{more})"


def _unit_line(u: Mapping[str, Any], dictionary: Dictionary | None = None) -> str:
    def entries(ids: Sequence[int], form: str | None, source: str) -> str:
        return ", ".join(_entry_label(e, form, dictionary, source) for e in ids)

    parts = [f"[{u['start']}:{u['end']}] {u['surface']}", u["kind"]]
    if u.get("entries"):
        parts.append(
            "entries=" + entries(u["entries"], u.get("form"), JMNEDICT if u["kind"] == "name" else JMDICT)
        )
    for key in ("form", "reading", "form_reading"):
        if u.get(key) is not None:
            parts.append(f"{key}={u[key]}")
    for key in ("chain", "split_points", "targets"):
        if u.get(key):
            parts.append(f"{key}=" + ",".join(str(x) for x in u[key]))
    if u.get("normalized"):
        n = u["normalized"]
        parts.append(f"normalized={n['form']}/{n['form_reading']}/{entries(n['entries'], n['form'], JMDICT)}")
    return "  " + "  ".join(parts)


def _oracle_order(names: Sequence[str]) -> list[str]:
    return sorted(names, key=lambda n: hashlib.sha256(n.encode()).hexdigest())


def render_item(
    item: Mapping[str, Any],
    text: str,
    oracles: Sequence[Mapping[str, Prediction]] = (),
    dictionary: Dictionary | None = None,
) -> str:
    start, end = item["start"], item["end"]
    lines = [
        f"{item['type'].upper()}  {item['record']}  {item.get('note', '')}".rstrip(),
        f"  {text[:start]}【{text[start:end]}】{text[end:]}",
    ]
    if item["type"] in ("field", "targets"):
        lines.append("  differs on: " + ", ".join(item["fields"]))
    if item["a"] == item["b"]:
        lines += ["Both:"] + [_unit_line(u, dictionary) for u in item["a"]]
    else:
        lines += ["A:"] + [_unit_line(u, dictionary) for u in item["a"]]
        lines += ["B:"] + [_unit_line(u, dictionary) for u in item["b"]]
    for n, predictions in enumerate(oracles, 1):
        p = predictions.get(item["record"])
        if p is not None:
            split = "|".join(text[u.start : u.end] for u in p.units)
            lines.append(f"oracle {n}: {split}")
    return "\n".join(lines)


def load_oracles(run_dirs: Sequence[Path]) -> list[dict[str, Prediction]]:
    by_name = {d.name: {p.id: p for p in load_predictions(d / "predictions.jsonl")} for d in run_dirs}
    return [by_name[n] for n in _oracle_order(list(by_name))]


Check = Callable[[Mapping[str, Any], Mapping[str, Any]], list[str]]


def decision_checker(
    a: Sequence[Record], b: Sequence[Record], items: Sequence[QueueItem], dictionary: Dictionary
) -> Check:
    """A check for one decision: it parses, an edit stays inside its item, and the record
    it produces (other items of the record taken as their default) validates there."""
    a_by_id, b_by_id = {r.id: r for r in a}, {r.id: r for r in b}
    by_record: dict[str, list[QueueItem]] = {}
    for item in items:
        by_record.setdefault(item.record_id, []).append(item)

    def check(item: Mapping[str, Any], decision: Mapping[str, Any]) -> list[str]:
        try:
            d = decision_from_dict({"item": item["id"], **decision})
        except (SchemaError, KeyError, TypeError, ValueError) as exc:
            return [f"not a decision: {exc}"]
        start, end = item["start"], item["end"]
        if d.choice == "edit":
            outside = [u.surface for u in d.units if not (start <= u.start and u.end <= end)]
            if outside:
                return [f"units outside [{start}:{end}]: {', '.join(outside)}"]
        record_id = item["record"]
        defaults = {
            i.id: Decision(i.id, "ok" if i.type in OK_ITEMS else "a") for i in by_record.get(record_id, [])
        }
        try:
            merged = merge_record(
                a_by_id[record_id], b_by_id[record_id], by_record.get(record_id, []), {**defaults, d.item: d}
            )
        except ValueError as exc:
            return [str(exc)]
        if merged is None:
            return ["the record could not be merged"]
        spans = {i: (u.start, u.end) for i, u in enumerate(merged.units)}
        return [
            str(issue)
            for issue in validate_record(merged, dictionary)
            if issue.unit is None or (start <= spans[issue.unit][0] and spans[issue.unit][1] <= end)
        ]

    return check


def tag_chunk(
    a: Sequence[Record],
    b: Sequence[Record],
    queue: Sequence[QueueItem],
    first: int,
    last: int,
    decisions: Path,
    dictionary: Dictionary,
) -> str:
    """A tag agent's chunk (the tag workflow): the ``targets`` items numbered
    ``first`` to ``last``, counted from 1 in queue order.

    Before ``decisions`` exists, each item as the review screen shows it, with its edit
    base: the two labelers' unit merged (``merge_units``), so an edit that changes only
    its targets keeps only the entry ids both list and both sides' split points. Once
    the file exists, what is wrong with the decisions in it, checked as the owner's are.
    """
    mine = [i for i in queue if i.type == "targets"][first - 1 : last]
    if not decisions.exists():
        texts = {r.id: r.text for r in a}
        shown = []
        for item in mine:
            base = unit_to_dict(merge_units(item.a[0], item.b[0]))
            shown += [
                item.id,
                render_item(item.to_dict(), texts[item.record_id], dictionary=dictionary),
                "Edit base (the merged unit): " + json.dumps(base, ensure_ascii=False),
                "",
            ]
        return "\n".join([*shown, f"{len(mine)} item(s)"])
    check = decision_checker(a, b, queue, dictionary)
    lines = decisions.read_text(encoding="utf-8").splitlines()
    decided = {d.get("item"): d for d in map(json.loads, filter(str.strip, lines))}
    ids = {i.id for i in mine}
    problems = [f"{i}: no decision" for i in sorted(ids - decided.keys())]
    problems += [f"{i}: not one of your items" for i in decided.keys() - ids]
    problems += [f"{i}: by must be tag-agent" for i, d in decided.items() if d.get("by") != "tag-agent"]
    for item in mine:
        if item.id in decided:
            decision = {k: v for k, v in decided[item.id].items() if k != "item"}
            problems += [f"{item.id}: {p}" for p in check(item.to_dict(), decision)]
    summary = f"{len(ids & decided.keys())} of {len(mine)} decided, {len(problems)} problem(s)"
    return "\n".join([summary, *problems])


def review(
    queue: Path,
    decisions_path: Path,
    texts: Mapping[str, str],
    oracles: Sequence[Mapping[str, Prediction]] = (),
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    check: Check | None = None,
    dictionary: Dictionary | None = None,
    recheck_tags: int = 0,
) -> int:
    """Prompt for every undecided item; return how many were decided this session.

    Items a tag agent decided, in ``decisions-tags-*.jsonl`` beside the decisions
    file, count as decided; ``recheck_tags`` of their ``targets`` items the owner
    has not answered yet, drawn by a hash of their ids, are shown after the rest.
    An edit that fails ``check`` is refused and asked again; a, b or ok that fails
    it is accepted with a warning, since the other side may be no better.
    """
    items = [json.loads(line) for line in queue.read_text(encoding="utf-8").splitlines() if line.strip()]
    done = load_decisions(decisions_path)
    by_agent = load_tag_decisions(decisions_path.parent)
    todo = [i for i in items if i["id"] not in done and i["id"] not in by_agent]
    ruled = [i for i in items if i["type"] == "targets" and i["id"] in by_agent and i["id"] not in done]
    recheck = sorted(ruled, key=lambda i: rank(i["id"]))[:recheck_tags]
    rechecking = f", and {len(recheck)} tag rulings to recheck" if recheck else ""
    say(f"{len(todo)} of {len(items)} items to review{rechecking}. {HELP}")
    todo += recheck
    decided = 0
    with decisions_path.open("a", encoding="utf-8") as out:
        for k, item in enumerate(todo, 1):
            say(f"\n[{k}/{len(todo)}] " + render_item(item, texts[item["record"]], oracles, dictionary))
            started = time.monotonic()
            can_ok = item["type"] in OK_ITEMS
            sides_differ = item["a"] != item["b"]
            decision: dict[str, Any] | None = None
            try:
                while decision is None:
                    answer = ask("> ").strip()
                    if answer == "q":
                        return decided
                    if answer == "s":
                        break
                    if answer in ("a", "b") and sides_differ:
                        decision = {"choice": answer}
                    elif answer == "o" and can_ok:
                        decision = {"choice": "ok"}
                    elif answer == "e":
                        try:
                            units = json.loads(ask("units JSON> "))
                        except json.JSONDecodeError as exc:
                            say(f"not JSON: {exc}")
                            continue
                        problems = check(item, {"choice": "edit", "units": units}) if check else []
                        if problems:
                            say("refused: " + "; ".join(problems))
                            continue
                        decision = {"choice": "edit", "units": units}
                    elif answer == "f":
                        note = ask("spec question> ").strip()
                        options = ("a", "b") if sides_differ else ("ok",) if can_ok else ()
                        fallback = (
                            options[0] if len(options) == 1 else ask("meanwhile take [a] or [b]> ").strip()
                        )
                        if fallback in options:
                            decision = {"choice": fallback, "flag": note}
                    else:
                        say(HELP)
            except EOFError:
                return decided
            if decision is None:
                continue
            if check and decision["choice"] != "edit":
                problems = check(item, decision)
                if problems:
                    say("warning: " + "; ".join(problems))
            seconds = round(time.monotonic() - started, 1)
            decision = {"item": item["id"], **decision, "seconds": seconds, "by": "owner"}
            out.write(json.dumps(decision, ensure_ascii=False) + "\n")
            out.flush()
            decided += 1
    return decided

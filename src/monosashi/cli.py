"""``monosashi`` command line."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from monosashi import pool as pool_mod
from monosashi import report as report_mod
from monosashi import review as review_mod
from monosashi import runner
from monosashi import select as select_mod
from monosashi.jmdict import Dictionary, Entry, ensure_index, repo_root
from monosashi.kana import normalize_text
from monosashi.label import batches, blind, compare, merge
from monosashi.label.candidates import candidate_sheet, format_senses, render_senses, render_sheet
from monosashi.predictions import Prediction, load_predictions
from monosashi.schema import Record, dump_records, load_records
from monosashi.score import Scorer
from monosashi.sources import dump_sentences, load_sentences, sentence_problems
from monosashi.tag import hints_for
from monosashi.validate import ADVISORY_RULES, validate_files, validate_record

# Gold records, relative to the repository; seed records live in its private twin.
CORE = Path("data") / "core"


def _dictionary(args: argparse.Namespace) -> Dictionary:
    return Dictionary(Path(args.index) if args.index else ensure_index())


def _cmd_jmdict_build(args: argparse.Namespace) -> int:
    path = ensure_index()
    print(path)
    return 0


def _cmd_jmdict_lookup(args: argparse.Namespace) -> int:
    dictionary = _dictionary(args)
    for text in args.text:
        for e in dictionary.lookup(text):
            print(
                f"{e.source} {e.seq} ({' '.join(e.pos)}) {_lookup_pairs(e, text) or text} - {format_senses(e)}"
            )
    return 0


def _lookup_pairs(entry: Entry, text: str) -> str:
    """The entry's spelling【reading】 pairs that include ``text``, in JMdict's order, each
    spelling with its JMdict tags (iK, io, sK, ...) and a common reading starred: the
    order and the stars are what SPEC.md §5's free-variant rule reads."""
    order = {s: k for k, s in enumerate(entry.kanji + entry.kana)}
    pairs = sorted(
        (p for p in entry.pairs if text in p), key=lambda p: (order.get(p[0], -1), order.get(p[1], 0))
    )

    def mark(spelling: str) -> str:
        tags = sorted(tag for s, tag in entry.spelling_tags if s == spelling)
        return spelling + (f"({','.join(tags)})" if tags else "")

    star = {r: "*" for r in entry.common_spellings}
    return ", ".join(f"{mark(s)}【{r if r == s else mark(r)}{star.get(r, '')}】" for s, r in pairs)


def _cmd_candidates(args: argparse.Namespace) -> int:
    dictionary = _dictionary(args)
    text = normalize_text(args.text)
    candidates = candidate_sheet(text, dictionary)
    if args.json:
        rows = [
            {
                "start": c.start,
                "end": c.end,
                "surface": c.surface,
                "form": c.form,
                "chain": list(c.chain),
                "source": c.entry.source,
                "seq": c.entry.seq,
                "readings": sorted(c.entry.readings_of(c.form)),
                "pos": list(c.entry.pos),
                "gloss": c.entry.gloss,
                "senses": [{"pos": list(s.pos), "glosses": list(s.glosses)} for s in c.entry.senses],
            }
            for c in candidates
        ]
        print(json.dumps({"text": text, "candidates": rows}, ensure_ascii=False))
    else:
        print(render_sheet(text, candidates))
        if candidates:
            print("\n" + render_senses(c.entry for c in candidates))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    found = validate_files([Path(p) for p in args.files], _dictionary(args), advisories=True)
    issues = [i for i in found if i.rule not in ADVISORY_RULES]
    notes = [i for i in found if i.rule in ADVISORY_RULES]
    for issue in issues:
        print(issue)
    # Advisories fail nothing; the review queue picks them up (SPEC.md §8).
    for note in notes:
        print(f"note: {note}")
    print(f"{len(issues)} issue(s), {len(notes)} advisory note(s)", file=sys.stderr)
    return 1 if issues else 0


def _cmd_pool(args: argparse.Namespace) -> int:
    streams = [
        pool_mod.committed_sentences("seeds", "synthetic"),
        pool_mod.open_sentences(),
    ]
    sentences = pool_mod.build_pool(streams)
    print(f"{len(sentences)} usable sentences; tagging", file=sys.stderr)
    tagged = pool_mod.tag_pool(sentences, Path(args.index) if args.index else None, args.workers)
    print(pool_mod.write_pool(tagged, "tagged"))
    return 0


def _cmd_tag(args: argparse.Namespace) -> int:
    text = normalize_text(args.text)
    for hint in hints_for(text, _dictionary(args)):
        print(f"[{hint.start}:{hint.end}] {text[hint.start : hint.end]} {hint.category}")
    return 0


def _cmd_select(args: argparse.Namespace) -> int:
    source = Path(args.pool) if args.pool else pool_mod.pool_dir() / "tagged.jsonl"
    selection = select_mod.select(load_sentences(source))
    bad = [(s.id, p) for s in selection.core + selection.reserve for p in sentence_problems(s)]
    if bad:
        raise SystemExit(f"{len(bad)} problem(s) in the selection, nothing written: {bad[:5]}")
    out = Path(args.out) if args.out else repo_root() / "data" / "selection"
    dump_sentences(out / "core.jsonl", selection.core)
    dump_sentences(out / "reserve.jsonl", selection.reserve)
    report = select_mod.summary(selection)
    (out / "summary.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def _gold_paths(args: argparse.Namespace) -> list[Path]:
    paths = (
        [Path(p) for p in args.gold]
        if args.gold
        else [p for d in (CORE, _private(CORE)) for p in sorted((repo_root() / d).glob("*.jsonl"))]
    )
    if not paths:
        raise SystemExit("no gold records: pass --gold FILES (data/core/ is empty)")
    return paths


def _cmd_run(args: argparse.Namespace) -> int:
    registry = runner.load_registry()
    unknown = sorted(set(args.adapters) - set(registry))
    if unknown:
        raise SystemExit(f"unknown adapter(s): {', '.join(unknown)}; known: {', '.join(sorted(registry))}")
    inputs = runner.read_inputs(_gold_paths(args))
    out = Path(args.out) if args.out else repo_root() / "runs"
    for name in args.adapters:
        print(runner.run_to_dir(registry[name], inputs, out / name))
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    records = [r for path in _gold_paths(args) for r in load_records(path)]
    scorer = Scorer(_dictionary(args))
    tools = report_mod.score_runs(scorer, records, [Path(p) for p in args.runs])
    text = report_mod.render(scorer, tools, samples=args.samples)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


def _labels_dir() -> Path:
    return repo_root() / "data" / "labels"


def _cmd_label_prepare(args: argparse.Namespace) -> int:
    sentences = list(load_sentences(Path(args.input)))[args.skip :]
    if args.limit is not None:
        # A blind pilot draws from the whole selection, which is sorted by slice.
        sentences = (blind.shuffled(sentences) if args.bundle else sentences)[: args.limit]
    run_dir = _labels_dir() / args.run
    out: dict[str, object] = {"run": str(run_dir)}
    if args.bundle:
        # The workflow's bundle_root must be absolute: labelers' shells start elsewhere.
        bundle = Path(args.bundle).resolve()
        try:
            names = blind.prepare(sentences, run_dir, bundle, _dictionary(args), args.batch_size)
        except (ValueError, FileExistsError) as exc:
            raise SystemExit(f"nothing prepared: {exc}") from exc
        out["bundle"] = str(bundle)
    else:
        names = batches.prepare(sentences, run_dir, _dictionary(args), args.batch_size)
        for labeler in batches.LABELERS:
            (run_dir / f"labels-{labeler}").mkdir(parents=True, exist_ok=True)
    print(json.dumps({**out, "batches": names, "sentences": len(sentences)}, ensure_ascii=False))
    return 0


def _cmd_label_collect(args: argparse.Namespace) -> int:
    run_dir = _labels_dir() / args.run
    sentences = list(load_sentences(Path(args.input)))
    try:
        found = blind.collect(run_dir, Path(args.bundle).resolve(), sentences, _dictionary(args))
    except ValueError as exc:
        raise SystemExit(f"nothing collected: {exc}") from exc
    for batch, issues in found.items():
        for issue in issues:
            print(f"{batch}: {issue}")
    total = sum(map(len, found.values()))
    print(f"collected {len(found)} batch file(s) into {run_dir}; {total} issue(s)", file=sys.stderr)
    return 1 if total else 0


def _labelings(run_dir: Path, labeler: str) -> list[Record]:
    return [
        r
        for path in sorted((run_dir / f"labels-{labeler}").glob("batch-*.jsonl"))
        for r in load_records(path)
    ]


def _tool_predictions(run_dirs: list[str]) -> dict[str, dict[str, Prediction]]:
    return {d: {p.id: p for p in load_predictions(Path(d) / "predictions.jsonl")} for d in run_dirs}


def _cmd_label_compare(args: argparse.Namespace) -> int:
    run_dir = _labels_dir() / args.run
    if not args.tools:
        print("no --tools: no tools items, and the spot draw differs from a run with tools", file=sys.stderr)
    tools = _tool_predictions(args.tools or [])
    a, b = _labelings(run_dir, "A"), _labelings(run_dir, "B")
    result = compare.compare(a, b, tools, args.quorum, dictionary=_dictionary(args))
    compare.dump_queue(run_dir / "queue.jsonl", result.items)
    summary = result.summary()
    (run_dir / "agreement.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_label_merge(args: argparse.Namespace) -> int:
    """Merge from the queue the owner reviewed; a record that fails validation waits."""
    run_dir = _labels_dir() / args.run
    a, b = _labelings(run_dir, "A"), _labelings(run_dir, "B")
    dictionary = _dictionary(args)
    items = compare.load_queue(run_dir / "queue.jsonl")
    # The queue must still describe these labelings: every item compare would build
    # now must be in it, unchanged. Tools items need the runs, and the spot draw
    # depends on them, so neither is rebuilt here.
    queued = {i.id: i for i in items}
    fresh = [
        i
        for i in compare.compare(a, b, dictionary=dictionary).items
        if i.type not in compare.TOOL_DEPENDENT_ITEMS
    ]
    stale = [i.id for i in fresh if queued.get(i.id) != i]
    if stale:
        print(
            f"queue.jsonl is stale for {len(stale)} item(s), e.g. {stale[:3]}; rerun compare", file=sys.stderr
        )
        return 1
    decisions = merge.load_all_decisions(run_dir)
    merged, waiting = merge.merge(a, b, items, decisions)
    valid: list[Record] = []
    invalid: list[Record] = []
    for record in merged:
        issues = validate_record(record, dictionary)
        for issue in issues:
            print(issue)
        (invalid if issues else valid).append(record)
    out = Path(args.out) if args.out else repo_root() / CORE
    written = _write_gold(out, valid)
    summary = {
        "merged": len(valid),
        "waiting": len(waiting),
        "invalid": [r.id for r in invalid],
        "written": written,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if invalid else 0


def _private(core: Path) -> Path:
    """Where seed records go beside ``core``: data/core keeps them in data/private/core."""
    return core.parent / "private" / core.name


def _write_gold(out: Path, records: list[Record]) -> dict[str, int]:
    """Write merged records to ``out``, except seed records, which quote lines that are
    not ours to publish (song lyrics, novels): those go to the gitignored private twin."""
    seeds = [r for r in records if r.slice == "seed"]
    written = _write_core(out, [r for r in records if r.slice != "seed"])
    if seeds:
        written |= {f"private/{k}": n for k, n in _write_core(_private(out), seeds).items()}
    return written


def _write_core(out: Path, records: list[Record]) -> dict[str, int]:
    """Add records to data/core/<register>.jsonl, replacing any with the same id."""
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    by_register: dict[str, list[Record]] = {}
    for r in records:
        by_register.setdefault(r.register, []).append(r)
    for register, new in by_register.items():
        path = out / f"{register}.jsonl"
        existing = {r.id: r for r in load_records(path)} if path.exists() else {}
        existing.update({r.id: r for r in new})
        dump_records(path, sorted(existing.values(), key=lambda r: r.id))
        counts[register] = len(existing)
    return counts


def _cmd_review(args: argparse.Namespace) -> int:
    run_dir = _labels_dir() / args.run
    a, b = _labelings(run_dir, "A"), _labelings(run_dir, "B")
    texts = {r.id: r.text for r in a}
    oracles = review_mod.load_oracles([Path(d) for d in args.tools or []])
    dictionary = _dictionary(args)
    check = review_mod.decision_checker(a, b, compare.load_queue(run_dir / "queue.jsonl"), dictionary)
    decided = review_mod.review(
        run_dir / "queue.jsonl",
        run_dir / "decisions.jsonl",
        texts,
        oracles,
        check=check,
        dictionary=dictionary,
        recheck_tags=args.recheck_tags,
    )
    print(f"{decided} decided this session")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="monosashi")
    parser.add_argument("--index", help="a built JMdict index (default: the pinned one in the cache)")
    sub = parser.add_subparsers(dest="command", required=True)

    jmdict = sub.add_parser("jmdict", help="the pinned JMdict/JMnedict snapshot")
    jmdict_sub = jmdict.add_subparsers(dest="jmdict_command", required=True)
    jmdict_sub.add_parser("build", help="fetch and index the pinned snapshot").set_defaults(
        func=_cmd_jmdict_build
    )
    lookup = jmdict_sub.add_parser("lookup", help="entries with a spelling")
    lookup.add_argument("text", nargs="+")
    lookup.set_defaults(func=_cmd_jmdict_lookup)

    candidates = sub.add_parser("candidates", help="the labeler's candidate sheet for one sentence")
    candidates.add_argument("text")
    candidates.add_argument("--json", action="store_true")
    candidates.set_defaults(func=_cmd_candidates)

    pool = sub.add_parser("pool", help="build and tag the sentence pool in the cache")
    pool.add_argument("--workers", type=int, default=None)
    pool.set_defaults(func=_cmd_pool)

    tag = sub.add_parser("tag", help="the category hints for one sentence")
    tag.add_argument("text")
    tag.set_defaults(func=_cmd_tag)

    select = sub.add_parser("select", help="draw the candidate set from the tagged pool into data/selection/")
    select.add_argument("--pool", help="a tagged pool (default: the one in the cache)")
    select.add_argument("--out", help="output directory (default: data/selection)")
    select.set_defaults(func=_cmd_select)

    run = sub.add_parser("run", help="run adapters over the gold sentences into runs/NAME/")
    run.add_argument("adapters", nargs="+")
    run.add_argument(
        "--gold",
        nargs="+",
        help="input JSONL with id and text (default: data/core/*.jsonl and data/private/core/*.jsonl)",
    )
    run.add_argument("--out", help="runs directory (default: runs/)")
    run.set_defaults(func=_cmd_run)

    score = sub.add_parser("score", help="score run directories against the gold records")
    score.add_argument("runs", nargs="+")
    score.add_argument(
        "--gold", nargs="+", help="gold JSONL (default: data/core/*.jsonl and data/private/core/*.jsonl)"
    )
    score.add_argument("--samples", type=int, default=1000, help="bootstrap resamples")
    score.add_argument("--out", help="also write the report here")
    score.set_defaults(func=_cmd_score)

    label = sub.add_parser("label", help="labeling runs under data/labels/RUN")
    label_sub = label.add_subparsers(dest="label_command", required=True)
    selection = str(repo_root() / "data" / "selection" / "core.jsonl")
    prepare = label_sub.add_parser("prepare", help="write batches and candidate sheets for two labelers")
    prepare.add_argument("run")
    prepare.add_argument("--input", default=selection)
    prepare.add_argument("--skip", type=int, default=0, help="skip this many sentences of the input")
    prepare.add_argument("--limit", type=int, default=None, help="with --bundle, drawn at random")
    prepare.add_argument("--batch-size", type=int, default=batches.BATCH_SIZE)
    prepare.add_argument("--bundle", help="write a blind bundle per labeler under this directory")
    prepare.set_defaults(func=_cmd_label_prepare)
    collect = label_sub.add_parser("collect", help="restore a blind run's labels into data/labels/RUN")
    collect.add_argument("run")
    collect.add_argument("--input", default=selection, help="the selection the run was prepared from")
    collect.add_argument("--bundle", required=True, help="the bundle directory given to prepare")
    collect.set_defaults(func=_cmd_label_collect)
    for name, func, text in (
        ("compare", _cmd_label_compare, "agreement between labelers A and B, and the review queue"),
        ("merge", _cmd_label_merge, "write decided records to data/core, seed records to data/private/core"),
    ):
        p = label_sub.add_parser(name, help=text)
        p.add_argument("run")
        if name == "compare":
            p.add_argument(
                "--tools", nargs="*", help="run directories of learner-unit tools, for the tools queue"
            )
            p.add_argument(
                "--quorum", type=int, default=1, help="learner-unit tools that must reproduce an agreed unit"
            )
        if name == "merge":
            p.add_argument("--out", help="core directory (default: data/core)")
        p.set_defaults(func=func)

    review = sub.add_parser("review", help="adjudicate a labeling run's queue (interactive)")
    review.add_argument("run")
    review.add_argument("--tools", nargs="*", help="run directories shown as anonymous oracles")
    review.add_argument(
        "--recheck-tags",
        type=int,
        default=0,
        metavar="N",
        help="also show N targets items a tag agent decided, drawn by hash",
    )
    review.set_defaults(func=_cmd_review)

    validate = sub.add_parser("validate", help="check gold JSONL files against SPEC.md")
    validate.add_argument("files", nargs="+")
    validate.set_defaults(func=_cmd_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

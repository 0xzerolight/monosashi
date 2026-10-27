"""Blind labeling bundles: each labeler gets a directory that hides where a sentence comes from.

``prepare`` shuffles the sentences, gives each an opaque id (``RUN-0001``) and
writes one bundle per labeler, ``A/`` and ``B/``. A bundle holds the spec, the
labeling instructions, the worked examples, each batch's input, sheets and
senses (``batches.write_batch``), and an empty ``labels/`` for the labeler's
output. Records in a bundle carry placeholder source, register and slice and
never a seed's expected answer, so no record says where it comes from. The spec
and the worked examples are verbatim copies, and the spec does name a few tools
and repository paths.

``RUN/blind.json`` keeps what the bundles leave out: the opaque-to-real id map,
and digests of the spec, the JMdict pin (``data/sources.toml``) and every module
the validator or the candidate sheet loads (labelers run both), which stay
frozen for the length of a run. ``collect`` refuses a run where any of them
changed, or where a labeler's records drifted from the batches they were given;
otherwise it writes ``RUN/labels-X/NAME.jsonl`` with the real ids, sources,
registers and slices restored, and validates every record again.

The bundle hides the repository's files only by instruction: Workflow labelers
start in the repository, so its tool output stays readable to an agent that goes
looking for it.
"""

from __future__ import annotations

import hashlib
import json
import random
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import monosashi
from monosashi import SPEC_VERSION
from monosashi.jmdict import Dictionary, repo_root
from monosashi.label import batches
from monosashi.schema import Record, Source, dump_records, load_records
from monosashi.sources import Sentence
from monosashi.validate import validate_record

BLIND_SEED = 20261017
BLIND_JSON = "blind.json"
SPEC = "SPEC.md"
SOURCES = "data/sources.toml"
# The command INSTRUCTIONS.md gives labelers: this checkout's own interpreter, so no
# path of the machine that prepared the run is written into the repository.
MONOSASHI = f"{shlex.quote(sys.executable)} -m monosashi.cli"

# What every bundle holds besides its batches, under these names.
_DOCS = {
    "SPEC.md": repo_root() / SPEC,
    "INSTRUCTIONS.md": Path(__file__).with_name("INSTRUCTIONS.md"),
    "spec-examples.jsonl": repo_root() / "tests" / "fixtures" / "spec-examples.jsonl",
}

# Run in a fresh interpreter: the caller may have loaded modules neither the validator
# nor the candidate sheet imports (the CLI loads them all), and a change to those must
# not stop a collect.
_FROZEN_MODULES = """
import json, sys
sys.path.insert(0, sys.argv[1])
import monosashi.validate, monosashi.label.candidates
print(json.dumps([m.__file__ for n, m in sys.modules.items() if n.split(".")[0] == "monosashi" and getattr(m, "__file__", None)]))
"""


def shuffled(sentences: Sequence[Sentence], seed: int = BLIND_SEED) -> list[Sentence]:
    out = list(sentences)
    random.Random(seed).shuffle(out)
    return out


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_files() -> list[str]:
    """``SPEC.md``, the JMdict pin and every module file the validator or the candidate
    sheet loads, relative to the repo root."""
    src = Path(monosashi.__file__).resolve().parents[1]
    found = subprocess.run(
        [sys.executable, "-I", "-c", _FROZEN_MODULES, str(src)], capture_output=True, text=True
    )
    if found.returncode:
        raise RuntimeError(f"could not list the frozen modules: {found.stderr.strip()}")
    root = repo_root()
    modules = {Path(f).resolve().relative_to(root).as_posix() for f in json.loads(found.stdout)}
    return [SPEC, SOURCES, *sorted(modules)]


def _blinded(sentence: Sentence, opaque: str) -> Sentence:
    source = Source("blind", opaque, "CC-BY-SA-4.0", "withheld while labeling")
    return Sentence(opaque, sentence.text, source, "conversation", "open", hints=sentence.hints)


def prepare(
    sentences: Sequence[Sentence],
    run_dir: Path,
    bundle_root: Path,
    dictionary: Dictionary,
    batch_size: int = batches.BATCH_SIZE,
    seed: int = BLIND_SEED,
) -> list[str]:
    """Write a bundle per labeler under ``bundle_root`` and ``run_dir/blind.json``; return the batch names.

    Refuses a bundle inside the repository, where its files could be committed and
    labelers would have to open the repository to read it, and a run directory an
    earlier run used, whose labels would mix with this run's. Writes nothing then,
    and leaves no partial bundle when writing fails.
    """
    if bundle_root.resolve().is_relative_to(repo_root()):
        raise ValueError(f"{bundle_root} is inside the repository; put the bundle outside it")
    if used := [
        p.relative_to(run_dir).as_posix()
        for p in [run_dir / BLIND_JSON, *run_dir.glob("labels-*/*")]
        if p.exists()
    ]:
        raise FileExistsError(f"{run_dir} holds an earlier run ({', '.join(used[:3])}); pick a new run name")
    bundles = [bundle_root / labeler for labeler in batches.LABELERS]
    if taken := [str(b) for b in bundles if b.exists()]:
        raise FileExistsError(f"bundle already exists: {', '.join(taken)}")
    order = shuffled(sentences, seed)
    blinded = [_blinded(s, f"{run_dir.name}-{n:04d}") for n, s in enumerate(order, 1)]
    meta = {
        "spec_version": SPEC_VERSION,
        "digests": {path: _sha256(repo_root() / path) for path in _frozen_files()},
        "ids": {b.id: s.id for b, s in zip(blinded, order, strict=True)},
    }
    first, *others = bundles
    try:
        names = batches.prepare(blinded, first, dictionary, batch_size)
        (first / "labels").mkdir()
        for name, path in _DOCS.items():
            shutil.copyfile(path, first / name)
        instructions = first / "INSTRUCTIONS.md"
        instructions.write_text(
            instructions.read_text(encoding="utf-8").replace("{monosashi}", MONOSASHI), encoding="utf-8"
        )
        for other in others:
            shutil.copytree(first, other)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / BLIND_JSON).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except BaseException:
        for bundle in bundles:
            shutil.rmtree(bundle, ignore_errors=True)
        raise
    return names


def _check_frozen(meta: dict[str, Any]) -> None:
    if meta["spec_version"] != SPEC_VERSION:
        raise ValueError(f"the run was prepared under spec {meta['spec_version']}, current is {SPEC_VERSION}")
    root = repo_root()
    digests: dict[str, str] = meta["digests"]
    changed = [p for p, d in digests.items() if not (root / p).is_file() or _sha256(root / p) != d]
    if changed:
        raise ValueError(
            f"changed since prepare, while the spec, JMdict pin, validator and candidate sheet are frozen: "
            f"{', '.join(changed)}"
        )


def _check_batch(where: str, got: list[str], expected: list[str]) -> None:
    if got == expected:
        return
    if missing := Counter(expected) - Counter(got):
        raise ValueError(f"{where}: missing {sorted(missing)}")
    if extra := Counter(got) - Counter(expected):
        raise ValueError(f"{where}: extra {sorted(extra)}")
    raise ValueError(f"{where}: records out of order")


def _restore(bundle: Path, ids: dict[str, str], real: dict[str, Sentence]) -> dict[str, list[Record]]:
    """A labeler's records per batch, checked against its inputs and restored to their real ids."""
    names = sorted(p.name.removesuffix(".input.jsonl") for p in bundle.glob("*.input.jsonl"))
    inputs = {name: [r.id for r in load_records(bundle / f"{name}.input.jsonl")] for name in names}
    if [i for name in names for i in inputs[name]] != list(ids):
        raise ValueError(f"{bundle}: its batches are not the ones blind.json describes")
    if extra := sorted({p.stem for p in (bundle / "labels").glob("*.jsonl")} - set(names)):
        raise ValueError(f"{bundle}/labels: no such batch: {', '.join(extra)}")
    restored: dict[str, list[Record]] = {}
    for name in names:
        path = bundle / "labels" / f"{name}.jsonl"
        if not path.is_file():
            raise ValueError(f"{path}: missing; batch {name} is not labeled")
        labeled = list(load_records(path))
        _check_batch(str(path), [r.id for r in labeled], inputs[name])
        restored[name] = []
        for r in labeled:
            s = real[ids[r.id]]
            if r.text != s.text:
                raise ValueError(f"{path}: {r.id}: text changed from {s.text!r} to {r.text!r}")
            restored[name].append(replace(r, id=s.id, source=s.source, register=s.register, slice=s.slice))
    return restored


def collect(
    run_dir: Path, bundle_root: Path, sentences: Sequence[Sentence], dictionary: Dictionary
) -> dict[str, list[str]]:
    """Restore every labeler's records into ``run_dir/labels-X/``; return the validator's issues per batch file.

    Nothing is written unless both labelers' records pass every check.
    """
    meta: dict[str, Any] = json.loads((run_dir / BLIND_JSON).read_text(encoding="utf-8"))
    _check_frozen(meta)
    ids: dict[str, str] = meta["ids"]
    real = {s.id: s for s in sentences}
    if unknown := [r for r in ids.values() if r not in real]:
        raise ValueError(f"{len(unknown)} record(s) of blind.json are not in the input, e.g. {unknown[:3]}")
    restored = {labeler: _restore(bundle_root / labeler, ids, real) for labeler in batches.LABELERS}
    issues: dict[str, list[str]] = {}
    for labeler, by_batch in restored.items():
        out = run_dir / f"labels-{labeler}"
        out.mkdir(exist_ok=True)
        for name, records in by_batch.items():
            dump_records(out / f"{name}.jsonl", records)
            issues[f"{out.name}/{name}.jsonl"] = [
                str(i) for r in records for i in validate_record(r, dictionary)
            ]
    return issues

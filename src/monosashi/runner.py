"""Run an adapter over a set of sentences and keep what it says, checked.

Adapters are listed in ``adapters/registry.toml``. The runner starts the
adapter's command once, sends one ``{"id", "text"}`` line at a time and reads
one answer back, with a timeout. A record the tool crashes on, times out on or
answers garbled is kept with that status and scores as if the tool had output
nothing; it is never dropped. A crashed or hung adapter is restarted for the
next record, and so is one that answers with a line that is not a JSON object
(a library printing to stdout) or with another record's id: its answers are
out of step, so the next line would be read as the next record's answer.

Every unit is checked against the text: ``text[start:end] == surface``. When
a tool's offsets are wrong (UTF-16 or byte offsets, skipped spaces), the
surfaces are re-found in order; a unit that matches nowhere, or whose own
span overlaps the unit before it, is dropped.
"""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Any

from monosashi.jmdict import cache_dir, repo_root
from monosashi.predictions import (
    Description,
    PredictedUnit,
    Prediction,
    description_from_dict,
    description_to_dict,
    dump_predictions,
    fits,
    unit_from_dict,
)
from monosashi.schema import SchemaError, mapping

TIMEOUT_S = 120.0
REGISTRY = "adapters/registry.toml"


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    name: str
    command: tuple[str, ...]
    env: Mapping[str, str]
    # Whether src/ goes on PYTHONPATH, for adapters in other venvs that import the protocol.
    pythonpath: bool = False


def _expand(value: str) -> str:
    return value.format(python=sys.executable, repo=repo_root(), cache=cache_dir(), home=Path.home())


def load_registry(path: Path | None = None) -> dict[str, AdapterSpec]:
    with (path or repo_root() / REGISTRY).open("rb") as fh:
        data = tomllib.load(fh)
    return {
        name: AdapterSpec(
            name=name,
            command=tuple(_expand(str(part)) for part in raw["command"]),
            env={k: _expand(str(v)) for k, v in raw.get("env", {}).items()},
            pythonpath=bool(raw.get("pythonpath", False)),
        )
        for name, raw in data.items()
    }


def _environment(spec: AdapterSpec) -> dict[str, str]:
    env = dict(os.environ) | dict(spec.env)
    if spec.pythonpath:
        src = str(repo_root() / "src")
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def describe(spec: AdapterSpec) -> Description:
    result = subprocess.run(
        [*spec.command, "--describe"],
        capture_output=True,
        text=True,
        env=_environment(spec),
        cwd=repo_root(),
        timeout=600,
        check=True,
    )
    return description_from_dict(json.loads(result.stdout.strip().splitlines()[-1]))


def repair(text: str, units: Sequence[PredictedUnit]) -> tuple[list[PredictedUnit], str]:
    """Units whose spans match the text, and the status that took.

    Units are taken in order; a wrong span is re-found by its surface after the
    previous unit. A unit whose span is right but overlaps the previous unit,
    and one whose surface is not found, are dropped, and the record is garbled.
    """
    status = "ok"
    out: list[PredictedUnit] = []
    pos = 0
    for unit in sorted(units, key=lambda u: (u.start, u.end)):
        start, end = unit.start, unit.end
        if fits(text, unit):
            if start < pos:
                status = "garbled"
                continue
        else:
            at = text.find(unit.surface, pos) if unit.surface else -1
            if at < 0:
                status = "garbled"
                continue
            start, end = at, at + len(unit.surface)
            status = "repaired" if status == "ok" else status
        out.append(replace(unit, start=start, end=end))
        pos = end
    return out, status


class _Process:
    """One live adapter process, restarted after a crash or a timeout."""

    def __init__(self, spec: AdapterSpec, stderr: IO[str]) -> None:
        self.spec = spec
        self.stderr = stderr
        self.proc: subprocess.Popen[str] | None = None

    def _start(self) -> subprocess.Popen[str]:
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(
                list(self.spec.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=_environment(self.spec),
                cwd=repo_root(),
            )
        return self.proc

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc = None

    def ask(self, request: Mapping[str, str], timeout: float) -> dict[str, Any] | tuple[str, str]:
        """The adapter's answer, or (status, why) when there is none to use.

        A line that is not a JSON object is garbled, and the process is killed:
        the real answer may still be in the pipe, to be read as the next record's.
        """
        proc = self._start()
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(json.dumps(dict(request), ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except BrokenPipeError:
            self.kill()
            return "crash", "the adapter exited"
        with selectors.DefaultSelector() as sel:
            sel.register(proc.stdout, selectors.EVENT_READ)
            if not sel.select(timeout):
                self.kill()
                return "timeout", f"no answer in {timeout:g} s"
        line = proc.stdout.readline()
        if not line:
            self.kill()
            return "crash", "the adapter exited"
        try:
            answer = json.loads(line)
        except json.JSONDecodeError:
            answer = None
        if not isinstance(answer, dict):
            self.kill()
            return "garbled", f"not a JSON object: {line.strip()[:200]!r}"
        return answer

    def close(self) -> None:
        if self.proc is not None and self.proc.stdin is not None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.kill()


def run(
    spec: AdapterSpec, sentences: Iterable[tuple[str, str]], stderr: IO[str], timeout: float = TIMEOUT_S
) -> Iterator[Prediction]:
    """Predictions for (id, text) pairs, in order.

    ``stderr`` is a real file: the adapter writes its own stderr there, and the
    runner adds a line for every record it could not use.
    """
    process = _Process(spec, stderr)
    try:
        for sid, text in sentences:
            answer = process.ask({"id": sid, "text": text}, timeout)
            if isinstance(answer, dict) and answer.get("id") != sid:
                process.kill()  # out of step: every later answer would be the previous record's
                answer = ("garbled", f"answer for another id: {str(answer.get('id'))[:100]!r}")
            elif isinstance(answer, dict) and "error" in answer:
                answer = ("crash", str(answer["error"]))
            if isinstance(answer, tuple):
                status, why = answer
                stderr.write(f"monosashi: {sid}: {status}: {why}\n")
                stderr.flush()
                yield Prediction(sid, (), None, status)
                continue
            try:
                raw = answer.get("units", [])
                if not isinstance(raw, list):
                    raise SchemaError(f"{sid}.units: expected a list")
                units = [
                    unit_from_dict(mapping(u, f"{sid}.units[{i}]"), f"{sid}.units[{i}]")
                    for i, u in enumerate(raw)
                ]
            except SchemaError as exc:
                stderr.write(f"monosashi: {sid}: garbled: {exc}\n")
                stderr.flush()
                yield Prediction(sid, (), None, "garbled")
                continue
            kept, status = repair(text, units)
            ms = answer.get("ms")  # a tool's own timing; anything but a number is left out
            ms = float(ms) if isinstance(ms, int | float) and not isinstance(ms, bool) else None
            yield Prediction(sid, tuple(kept), ms, status)
    finally:
        process.close()


def read_inputs(paths: Iterable[Path]) -> list[tuple[str, str]]:
    """(id, text) from any JSONL with those two fields: gold records or selected sentences."""
    out = []
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    data = json.loads(line)
                    out.append((str(data["id"]), str(data["text"])))
    return out


def run_to_dir(spec: AdapterSpec, inputs: Sequence[tuple[str, str]], out_dir: Path) -> Path:
    """Write describe.json, predictions.jsonl and stderr.log for one adapter run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    description = describe(spec)
    (out_dir / "describe.json").write_text(
        json.dumps(description_to_dict(description), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (out_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
        dump_predictions(out_dir / "predictions.jsonl", run(spec, inputs, stderr))
    return out_dir

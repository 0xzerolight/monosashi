"""The adapter side of the contract, in the standard library only.

An adapter that runs in another environment (anki_miner's venv, a heavy tool's
own venv) imports this one module with ``PYTHONPATH`` pointing at ``src/``, so
it must not import anything outside the standard library.

    from monosashi.adapters.protocol import serve

    def analyze(text: str) -> list[dict]:
        ...  # units with start, end, surface and whatever else the tool gives

    serve(analyze, describe={"name": ..., "version": ..., ...})
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

Unit = dict[str, Any]


def serve(analyze: Callable[[str], list[Unit]], describe: Mapping[str, Any]) -> None:
    """Answer ``--describe``, or one JSON line per input line until stdin closes.

    A record the tool fails on gets ``{"id", "error"}``, so one bad sentence
    never takes the run down.
    """
    out = sys.stdout
    if "--describe" in sys.argv[1:]:
        out.write(json.dumps(dict(describe), ensure_ascii=False) + "\n")
        return
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        started = time.perf_counter()
        try:
            units = analyze(request["text"])
        except Exception as exc:  # the runner records it as a crash for this record
            reply: dict[str, Any] = {"id": request["id"], "error": f"{type(exc).__name__}: {exc}"}
        else:
            reply = {"id": request["id"], "units": units, "ms": (time.perf_counter() - started) * 1000}
        out.write(json.dumps(reply, ensure_ascii=False) + "\n")
        out.flush()


def spans_in_order(text: str, surfaces: Iterable[str]) -> list[tuple[int, int] | None]:
    """Code point spans for surfaces a tool lists in text order without offsets.

    Each surface is searched from where the previous one ended, so a repeated
    word lands on the right occurrence; a surface not found gets None.
    """
    spans: list[tuple[int, int] | None] = []
    pos = 0
    for surface in surfaces:
        at = text.find(surface, pos) if surface else -1
        if at < 0:
            spans.append(None)
            continue
        spans.append((at, at + len(surface)))
        pos = at + len(surface)
    return spans


def to_hiragana(text: str) -> str:
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text)

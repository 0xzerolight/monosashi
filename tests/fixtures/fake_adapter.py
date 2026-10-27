"""A stand-in adapter for runner tests: one unit per character, with planted faults.

CRASH exits, HANG sleeps, OFFSET returns UTF-16-style offsets (wrong for 𠮷),
ERROR raises inside analyze, JUNK returns a unit that matches nothing, and
NOISE / EXTRA print a stray stdout line (not JSON / a JSON object) before the answer.
"""

from __future__ import annotations

import sys
import time

from monosashi.adapters.protocol import serve


def analyze(text: str) -> list[dict[str, object]]:
    if text.startswith("CRASH"):
        sys.exit(3)
    if text.startswith("HANG"):
        time.sleep(30)
    if text.startswith("ERROR"):
        raise ValueError("planted")
    if text.startswith("NOISE"):
        print("loading model...")
    if text.startswith("EXTRA"):
        print('{"log": "warm"}')
    units: list[dict[str, object]] = []
    pos = 0
    for ch in text:
        width = 2 if text.startswith("OFFSET") and ord(ch) > 0xFFFF else 1
        units.append({"start": pos, "end": pos + width, "surface": ch})
        pos += width
    if text.startswith("JUNK"):
        units.append({"start": 0, "end": 1, "surface": "?"})
    return units


serve(analyze, {"name": "fake", "version": "0", "dictionary": "none", "dictionary_date": "-", "partition": True,
                "fields": []})  # fmt: skip

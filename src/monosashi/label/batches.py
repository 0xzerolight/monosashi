"""Labeling batches: what two blind labelers get for each slice of the candidate set.

``prepare`` splits the selection into batches. For each batch it writes:

- ``batch-NNN.input.jsonl``: one skeleton record per sentence, with every
  record field already filled except ``units``;
- ``batch-NNN.sheets.md``: for each sentence, its text, the category hints the
  tagger found, and the JMdict candidate sheet;
- ``batch-NNN.senses.md``: every sense of every entry on those sheets, once
  per entry, so the sheets stay one line per candidate.

Labelers write ``labels-<labeler>/batch-NNN.jsonl``. Nothing in a batch comes
from a tool under test, so labelers stay blind to tool output. A blind run
(``monosashi.label.blind``) writes the same files into each labeler's own
bundle, for sentences whose id and source it has replaced.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from monosashi import SPEC_VERSION
from monosashi.jmdict import Dictionary
from monosashi.label.candidates import Candidate, candidate_sheet, render_senses, render_sheet
from monosashi.schema import source_to_dict
from monosashi.sources import Sentence

BATCH_SIZE = 25
# Two blind labelers per sentence; their labelings are compared unit by unit.
LABELERS = ("A", "B")


def batch_name(index: int) -> str:
    return f"batch-{index:03d}"


def skeleton(sentence: Sentence) -> dict[str, object]:
    return {
        "id": sentence.id,
        "text": sentence.text,
        "source": source_to_dict(sentence.source),
        "register": sentence.register,
        "slice": sentence.slice,
        "units": [],
        "label": {"status": "draft", "spec": SPEC_VERSION},
    }


def sheet(sentence: Sentence, candidates: list[Candidate]) -> str:
    hints = sorted({(h.start, h.end, h.category) for h in sentence.hints})
    lines = [f"## {sentence.id}", ""]
    if hints:
        lines.append("Hints (the tagger's guesses; confirm or drop each one):")
        lines += [f"- [{a}:{b}] {sentence.text[a:b]} → {c}" for a, b, c in hints]
        lines.append("")
    lines += ["```", render_sheet(sentence.text, candidates), "```", ""]
    return "\n".join(lines)


def write_batch(name: str, batch: Sequence[Sentence], out_dir: Path, dictionary: Dictionary) -> None:
    """Write one batch's input skeletons, candidate sheets and senses into ``out_dir``."""
    sheets = [candidate_sheet(s.text, dictionary) for s in batch]
    with (out_dir / f"{name}.input.jsonl").open("w", encoding="utf-8") as fh:
        for s in batch:
            fh.write(json.dumps(skeleton(s), ensure_ascii=False) + "\n")
    (out_dir / f"{name}.sheets.md").write_text(
        f"# {name}: candidate sheets\n\nEvery sense of every entry below is in {name}.senses.md.\n\n"
        + "\n".join(sheet(s, candidates) for s, candidates in zip(batch, sheets, strict=True)),
        encoding="utf-8",
    )
    (out_dir / f"{name}.senses.md").write_text(
        f"# {name}: senses\n\nEvery sense of every entry on {name}.sheets.md, one line per entry:"
        " `seq: 1) gloss; gloss (pos; tags) [notes] {only spellings} 2) ...`."
        " `name` marks a JMnedict entry.\n\n"
        f"```\n{render_senses(c.entry for candidates in sheets for c in candidates)}\n```\n",
        encoding="utf-8",
    )


def prepare(
    sentences: Sequence[Sentence], out_dir: Path, dictionary: Dictionary, batch_size: int = BATCH_SIZE
) -> list[str]:
    """Write every batch's input, sheets and senses; return the batch names."""
    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for start in range(0, len(sentences), batch_size):
        name = batch_name(start // batch_size + 1)
        write_batch(name, sentences[start : start + batch_size], out_dir, dictionary)
        names.append(name)
    return names

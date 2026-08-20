#!/usr/bin/env python3
"""Deterministically assemble chapter drafts from ru-parts (replaces LLM close-agent assembly).

Usage: python3 assemble.py <chapter_id> [...]
Writes work/ru-draft/<chapter_id>.md: parts joined by blank lines in chunk order,
'## Примечания' heading inserted before the first notes-kind chunk.
Exits 1 if any part is missing.
"""
import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]


def assemble(ch_id):
    chunks = json.loads((WORK / "chunks" / f"{ch_id}.json").read_text())
    pieces, notes_started = [], False
    for c in chunks:
        part = WORK / "ru-parts" / ch_id / f"{c['id']}.md"
        if not part.exists():
            sys.exit(f"MISSING part: {part}")
        if c["kind"] == "notes" and not notes_started:
            pieces.append("## Примечания")
            notes_started = True
        pieces.append(part.read_text().strip())
    out = WORK / "ru-draft" / f"{ch_id}.md"
    out.write_text("\n\n".join(pieces) + "\n")
    print(f"assembled {out.name}: {len(chunks)} chunks")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for ch in sys.argv[1:]:
        assemble(ch)

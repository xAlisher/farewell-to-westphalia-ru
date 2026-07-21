#!/usr/bin/env python3
"""Build the Workflow args for translate-chapters.js.

Usage: python3 batches.py <chapter_id> [<chapter_id> ...]
Prints JSON {chapters: [{id, batches: [[chunk_id,...],...]}]} — body chunks in
order, batched 4 per translator call; notes chunks batched separately (they
carry different rules: citations stay EN).
"""
import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]
BATCH = 4


def main():
    out = []
    for ch_id in sys.argv[1:]:
        chunks = json.loads((WORK / "chunks" / f"{ch_id}.json").read_text())
        body = [c["id"] for c in chunks if c["kind"] == "body"]
        notes = [c["id"] for c in chunks if c["kind"] == "notes"]
        batches = [body[i:i + BATCH] for i in range(0, len(body), BATCH)]
        if notes:
            batches.append(notes)
        out.append({"id": ch_id, "batches": batches})
    print(json.dumps({"chapters": out}))


if __name__ == "__main__":
    sys.exit(main())

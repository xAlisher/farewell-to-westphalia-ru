#!/usr/bin/env python3
"""W0 step 5: freeze chunk boundaries for translation.

Reads work/en/<chapter>.md, splits body into paragraph-aligned chunks of
~8-12 sentences (never splitting a paragraph or blockquote), and the
``## Notes`` block into notes-chunks of ~10 entries. Writes
work/chunks/<chapter>.json.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"

ABBREV = re.compile(
    r"\b(e\.g|i\.e|etc|vs|cf|ca|Dr|Mr|Mrs|Ms|Prof|St|no|No|vol|Vol|p|pp|"
    r"ed|eds|trans|Inc|Ltd|Co|U\.S|U\.K|Ph\.D)\.$")
SENT_END = re.compile(r"(?<=[.!?…])[’”'\")\]]*\s+")

TARGET_MIN, TARGET_MAX = 8, 12


def count_sentences(text):
    # crude but deterministic: split on sentence-final punctuation + space,
    # rejoin abbreviation false-splits
    parts = SENT_END.split(text.strip())
    sents = []
    for part in parts:
        if sents and ABBREV.search(sents[-1]):
            sents[-1] += " " + part
        elif part.strip():
            sents.append(part.strip())
    return max(1, len(sents))


def split_blocks(md):
    """Split markdown into blocks: headings, paragraphs, blockquotes."""
    lines = md.split("\n")
    blocks, cur, kind = [], [], None

    def flush():
        nonlocal cur, kind
        if cur:
            blocks.append({"kind": kind or "para", "text": "\n".join(cur).strip()})
        cur, kind = [], None

    for ln in lines:
        if ln.startswith("#"):
            flush()
            blocks.append({"kind": "heading", "text": ln.strip()})
        elif ln.startswith(">"):
            if kind != "quote":
                flush()
                kind = "quote"
            cur.append(ln)
        elif not ln.strip():
            flush()
        else:
            if kind == "quote":
                cur.append(ln)  # continuation of quote block
            else:
                kind = "para"
                cur.append(ln)
    flush()
    return [b for b in blocks if b["text"]]


def chunk_chapter(ch_id, md):
    # split off Notes block
    m = re.search(r"^## (Notes|Примечания)\s*$", md, flags=re.M)
    body, notes = (md[: m.start()], md[m.start():]) if m else (md, "")

    blocks = split_blocks(body)
    chunks, cur_blocks, cur_sents = [], [], 0

    def flush_chunk():
        nonlocal cur_blocks, cur_sents
        if cur_blocks:
            text = "\n\n".join(b["text"] for b in cur_blocks)
            chunks.append({
                "id": f"{ch_id.split('_')[1]}-{len(chunks):03d}",
                "kind": "body",
                "en_sentences": cur_sents,
                "en_chars": len(text),
                "en_words": len(text.split()),
                "text": text,
            })
        cur_blocks, cur_sents = [], 0

    for b in blocks:
        sents = 0 if b["kind"] == "heading" else count_sentences(b["text"])
        # headings start a new chunk so section boundaries align
        if b["kind"] == "heading" and cur_sents >= TARGET_MIN:
            flush_chunk()
        cur_blocks.append(b)
        cur_sents += sents
        if cur_sents >= TARGET_MAX:
            flush_chunk()
    if cur_sents > 0 and cur_sents < TARGET_MIN and chunks:
        # merge trailing runt into previous chunk
        prev = chunks.pop()
        text = prev["text"] + "\n\n" + "\n\n".join(b["text"] for b in cur_blocks)
        chunks.append({**prev, "en_sentences": prev["en_sentences"] + cur_sents,
                       "en_chars": len(text), "en_words": len(text.split()),
                       "text": text})
    else:
        flush_chunk()

    # notes chunks: ~10 footnote entries each
    if notes:
        note_entries = re.findall(r"^\[\^\d+\]:.*(?:\n(?!\[\^|\#).*)*",
                                  notes, flags=re.M)
        for i in range(0, len(note_entries), 10):
            group = note_entries[i:i + 10]
            text = "\n\n".join(e.strip() for e in group)
            chunks.append({
                "id": f"{ch_id.split('_')[1]}-N{i // 10:02d}",
                "kind": "notes",
                "en_sentences": sum(count_sentences(e) for e in group),
                "en_chars": len(text),
                "en_words": len(text.split()),
                "text": text,
            })
    return chunks


def main():
    outdir = WORK / "chunks"
    outdir.mkdir(exist_ok=True)
    total = 0
    for f in sorted((WORK / "en").glob("chapter_*.md")):
        ch_id = f.stem
        chunks = chunk_chapter(ch_id, f.read_text())
        (outdir / f"{ch_id}.json").write_text(
            json.dumps(chunks, indent=1, ensure_ascii=False))
        total += len(chunks)
        body = [c for c in chunks if c["kind"] == "body"]
        print(f"{ch_id}: {len(body)} body + {len(chunks)-len(body)} notes chunks")
    print(f"TOTAL: {total} chunks")


if __name__ == "__main__":
    sys.exit(main())

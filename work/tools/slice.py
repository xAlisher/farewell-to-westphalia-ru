#!/usr/bin/env python3
"""Pre-filter glossary + proper-noun entries relevant to given chunks.

Usage: python3 slice.py <chapter_id> <chunk_id> [<chunk_id> ...]
Prints JSON {glossary: [...], nouns: [...]} with only the entries whose English
form (or a crude stem of it) occurs in the chunk texts. Keeps translator prompts
lean while guaranteeing every term that appears is covered.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"


def stem(term):
    # crude: strip plural/verbal endings from each word, lowercase
    words = re.findall(r"[A-Za-z][A-Za-z-]+", term.lower())
    return [re.sub(r"(ies|es|s|ing|ed)$", "", w) for w in words if len(w) > 3] or \
           [w for w in words]


def matches(term, text):
    stems = stem(term)
    if not stems:
        return term.lower() in text
    return all(s in text for s in stems)


def main():
    chapter_id, chunk_ids = sys.argv[1], sys.argv[2:]
    chunks = {c["id"]: c for c in json.loads(
        (WORK / "chunks" / f"{chapter_id}.json").read_text())}
    text = " ".join(chunks[cid]["text"] for cid in chunk_ids if cid in chunks).lower()

    glossary = json.loads((WORK / "glossary.json").read_text())
    nouns = json.loads((WORK / "proper-nouns.json").read_text())
    out = {
        "glossary": [g for g in glossary if matches(g["en"], text)],
        "nouns": [n for n in nouns if matches(n["en"], text)],
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

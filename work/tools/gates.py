#!/usr/bin/env python3
"""Alignment gate: deterministic omission/expansion checks for translated chunks.

Usage:
  python3 gates.py check <chapter_id> <chunk_id> [<chunk_id> ...]

For each chunk id, compares work/chunks/<chapter>.json entry against
work/ru-parts/<chapter>/<chunk_id>.md and prints a JSON verdict list:
sentence-count delta, char ratio, footnote-marker preservation.
Exit code 0 always (verdicts carry the result).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"

ABBREV_EN = re.compile(
    r"\b(e\.g|i\.e|etc|vs|cf|ca|Dr|Mr|Mrs|Ms|Prof|St|no|No|vol|Vol|p|pp|"
    r"ed|eds|trans|Inc|Ltd|Co|U\.S|U\.K|Ph\.D)\.$")
ABBREV_RU = re.compile(
    r"\b(т\.\s?е|т\.\s?д|т\.\s?п|см|напр|др|проч|г|гг|в|вв|н\.\s?э|ок|стр|с|"
    r"им|тыс|млн|млрд)\.$", re.IGNORECASE)
SENT_END = re.compile(r"(?<=[.!?…])[’”'\")\]»]*\s+")
FOOTNOTE = re.compile(r"\[\^(\d+)\]")

RATIO_MIN, RATIO_MAX = 0.85, 1.40
SENT_TOLERANCE = 2  # RU merges/splits sentences legitimately; ±2 before flagging


def count_sentences(text, abbrev):
    text = re.sub(r"^#+ .*$", "", text, flags=re.M)  # headings don't count
    text = re.sub(r"^\[\^\d+\]:", "", text, flags=re.M)
    parts = SENT_END.split(text.strip())
    sents = []
    for part in parts:
        if sents and abbrev.search(sents[-1]):
            sents[-1] += " " + part
        elif part.strip():
            sents.append(part.strip())
    return max(1, len(sents))


def check(chapter_id, chunk_ids):
    chunks = {c["id"]: c for c in json.loads(
        (WORK / "chunks" / f"{chapter_id}.json").read_text())}
    out = []
    for cid in chunk_ids:
        c = chunks.get(cid)
        if not c:
            out.append({"chunk_id": cid, "ok": False, "error": "unknown chunk id"})
            continue
        part = WORK / "ru-parts" / chapter_id / f"{cid}.md"
        if not part.exists():
            out.append({"chunk_id": cid, "ok": False, "error": "missing RU part file"})
            continue
        ru = part.read_text()
        ru_sents = count_sentences(ru, ABBREV_RU)
        en_sents = c["en_sentences"]
        ratio = len(ru) / max(1, c["en_chars"])
        en_marks = sorted(set(FOOTNOTE.findall(c["text"])))
        ru_marks = sorted(set(FOOTNOTE.findall(ru)))
        problems = []
        if abs(ru_sents - en_sents) > SENT_TOLERANCE:
            problems.append(f"sentence delta {ru_sents - en_sents} (EN {en_sents}, RU {ru_sents})")
        if not (RATIO_MIN <= ratio <= RATIO_MAX) and c["kind"] == "body":
            problems.append(f"char ratio {ratio:.2f} outside [{RATIO_MIN},{RATIO_MAX}]")
        if en_marks != ru_marks:
            problems.append(f"footnote markers EN {en_marks} vs RU {ru_marks}")
        out.append({"chunk_id": cid, "ok": not problems,
                    "ratio": round(ratio, 3),
                    "en_sents": en_sents, "ru_sents": ru_sents,
                    "problems": problems})
    return out


def main():
    if len(sys.argv) < 4 or sys.argv[1] != "check":
        print(__doc__)
        return 1
    print(json.dumps(check(sys.argv[2], sys.argv[3:]),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

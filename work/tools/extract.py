#!/usr/bin/env python3
"""W0 step 2: deterministic per-chapter extraction from the PDF.

Runs pdftotext (reflow mode) per chapter from work/page-map.json, then applies
mechanical cleanup: ligatures, line-end de-hyphenation, running header/footer
stripping, unicode normalization. Output: work/en-raw/<chapter_id>.txt
Agents do the semantic cleanup (headings, footnotes, paragraphs) afterwards.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"
PAGE_MAP = json.loads((WORK / "page-map.json").read_text())
PDF = ROOT / PAGE_MAP["pdf_file"]

LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl",
    "’": "’",  # keep curly apostrophe
}

# Running headers: "N / Farewell to Westphalia" or "<Chapter Title> / N",
# emitted by pdftotext as separate short lines around page breaks.
HEADER_BOOK = re.compile(r"^\s*Farewell to Westphalia\s*$")
PAGE_NUM = re.compile(r"^\s*\d{1,3}\s*$")


def clean_pages(chapter, raw_pages):
    title_upper = chapter["title_en"].upper()
    out_lines = []
    for page_text in raw_pages:
        lines = page_text.splitlines()
        # Strip header/footer furniture: standalone page numbers, book title,
        # chapter-title running heads (case-insensitive match on title words).
        kept = []
        for ln in lines:
            s = ln.strip()
            if PAGE_NUM.match(s):
                continue
            if HEADER_BOOK.match(s):
                continue
            # running head repeats the chapter title (often broken oddly);
            # only strip if the line is EXACTLY the title (short line)
            if s and len(s) < 80 and s.upper() == title_upper:
                continue
            kept.append(ln)
        out_lines.append("\n".join(kept))
    text = "\n".join(out_lines)
    for lig, rep in LIGATURES.items():
        text = text.replace(lig, rep)
    # soft hyphens (U+00AD): mid-word artifacts like "­listening"
    text = text.replace("­", "")
    # de-hyphenate line-end breaks: "gover-\nnance" -> "governance"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # collapse 3+ blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def extract_chapter(chapter):
    pages = []
    for p in range(chapter["pdf_start"], chapter["pdf_end"] + 1):
        r = subprocess.run(
            ["pdftotext", "-f", str(p), "-l", str(p), "-nopgbrk",
             "-enc", "UTF-8", str(PDF), "-"],
            capture_output=True, text=True, check=True)
        pages.append(r.stdout)
    return clean_pages(chapter, pages)


def main():
    outdir = WORK / "en-raw"
    outdir.mkdir(exist_ok=True)
    report = {}
    for ch in PAGE_MAP["chapters"]:
        text = extract_chapter(ch)
        out = outdir / f"{ch['id']}.txt"
        out.write_text(text)
        words = len(text.split())
        report[ch["id"]] = {"words": words, "chars": len(text)}
        print(f"{ch['id']}: {words} words")
    (WORK / "en-raw" / "_extract_report.json").write_text(
        json.dumps(report, indent=2))


if __name__ == "__main__":
    sys.exit(main())

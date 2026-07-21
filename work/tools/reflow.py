#!/usr/bin/env python3
"""Mechanical chapter cleanup from -layout pdftotext (no LLM in the copy path).

Used for chapters where agent-based cleanup is blocked (content-filter trips on
large verbatim outputs). Produces work/en/<chapter>.md directly from the PDF:
paragraph reflow, footnote extraction to [^N]/## Notes, header stripping.
An agent then reviews with small targeted edits only.

Usage: python3 reflow.py <chapter_id>
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

LIG = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "­": ""}


def get_pages(start, end):
    pages = []
    for p in range(start, end + 1):
        r = subprocess.run(
            ["pdftotext", "-f", str(p), "-l", str(p), "-layout", "-nopgbrk",
             "-enc", "UTF-8", str(PDF), "-"],
            capture_output=True, text=True, check=True)
        t = r.stdout
        for a, b in LIG.items():
            t = t.replace(a, b)
        pages.append(t)
    return pages


def indent(line):
    return len(line) - len(line.lstrip())


def clean_page(page, title_upper, printed_num):
    """Return (body_lines, footnote_lines) for one page; lines keep indent."""
    lines = [ln.rstrip() for ln in page.splitlines()]
    # drop furniture: page numbers (the known printed number), running heads.
    # Other standalone small digits are footnote markers — keep them.
    kept = []
    for ln in lines:
        s = ln.strip()
        if not s:
            kept.append(ln)
            continue
        if re.fullmatch(r"\d{1,3}", s) and printed_num is not None \
           and int(s) == printed_num:
            continue
        if re.fullmatch(r"\d{1,3}\s+Farewell to Westphalia", s):
            continue
        if re.fullmatch(r"(CHAPTER \d+)", s):
            continue
        if s.upper() == title_upper and len(s) < 80:
            continue
        # running head form "Title   211"
        if re.fullmatch(r".{0,70}\s\d{1,3}", s) and \
           s.rsplit(None, 1)[0].strip().upper() in (title_upper, "FAREWELL TO WESTPHALIA"):
            continue
        kept.append(ln)
    # footnotes: a line that is ONLY a small number (marker) starts the
    # footnote zone at page bottom; everything after belongs to footnotes.
    body, foots = [], []
    i = 0
    fn_start = None
    for idx, ln in enumerate(kept):
        s = ln.strip()
        if re.fullmatch(r"\d{1,2}", s) and int(s) < 80:
            # footnote-number line: small number in lower part of the page
            if idx > len(kept) * 0.4:
                fn_start = idx
                break
    if fn_start is not None:
        body = kept[:fn_start]
        foots = kept[fn_start:]
    else:
        body = kept
    return body, foots


def reflow_body(all_lines):
    """Join wrapped lines into paragraphs using indentation cues."""
    # find base indent = most common indent of non-empty lines
    indents = [indent(l) for l in all_lines if l.strip()]
    if not indents:
        return []
    base = max(set(indents), key=indents.count)
    paras, cur, kind = [], [], "para"

    def flush():
        nonlocal cur, kind
        if cur:
            text = " ".join(w.strip() for w in cur)
            text = re.sub(r"(\w)- (\w)", r"\1\2", text)  # de-hyphenate joins
            text = re.sub(r"\s{2,}", " ", text).strip()
            if text:
                paras.append((kind, text))
        cur, kind = [], "para"

    for ln in all_lines:
        s = ln.strip()
        if not s:
            flush()
            continue
        ind = indent(ln)
        if re.fullmatch(r"\d+\.\d+ .+", s):  # section heading
            flush()
            paras.append(("heading", s))
            continue
        if ind >= base + 4:  # block quote / offset material
            if kind != "quote":
                flush()
                kind = "quote"
            cur.append(s)
            continue
        if ind > base and kind != "quote":  # indented => new paragraph
            flush()
            cur.append(s)
            continue
        if kind == "quote" and ind <= base:
            flush()
        cur.append(s)
    flush()
    return paras


def extract_footnotes(foot_chunks):
    """foot_chunks: list of line-lists from page bottoms. Return {n: text}."""
    notes = {}
    for chunk in foot_chunks:
        cur_n = None
        cur = []
        for ln in chunk:
            s = ln.strip()
            if not s:
                continue
            m = re.fullmatch(r"(\d{1,2})", s)
            m2 = re.match(r"^(\d{1,2})\s+(\S.*)$", s) if not m else None
            if m or (m2 and indent(ln) <= 2 and cur_n is not None):
                if cur_n is not None and cur:
                    notes[cur_n] = re.sub(r"\s{2,}", " ",
                                          re.sub(r"(\w)- (\w)", r"\1\2",
                                                 " ".join(cur))).strip()
                if m:
                    cur_n, cur = int(m.group(1)), []
                else:
                    cur_n, cur = int(m2.group(1)), [m2.group(2)]
            else:
                if cur_n is not None:
                    cur.append(s)
        if cur_n is not None and cur:
            notes[cur_n] = re.sub(r"\s{2,}", " ",
                                  re.sub(r"(\w)- (\w)", r"\1\2",
                                         " ".join(cur))).strip()
    return notes


def convert_markers(text, valid_numbers):
    """Attach [^N] markers: digits glued to punctuation, in valid set."""
    def repl(m):
        n = int(m.group(2))
        if n in valid_numbers:
            return f"{m.group(1)}[^{n}]"
        return m.group(0)
    return re.sub(r"(?<![0-9])([.,;:’”'\")\]])(\d{1,2})(?![0-9.%])", repl, text)


def main():
    ch_id = sys.argv[1]
    ch = next(c for c in PAGE_MAP["chapters"] if c["id"] == ch_id)
    pages = get_pages(ch["pdf_start"], ch["pdf_end"])
    title_upper = ch["title_en"].upper()

    bodies, foot_chunks = [], []
    printed_start = ch["printed"][0] if ch.get("printed") else None
    for pi, pg in enumerate(pages):
        printed_num = printed_start + pi if printed_start is not None else None
        b, f = clean_page(pg, title_upper, printed_num)
        bodies.extend(b + [""])
        if f:
            foot_chunks.append(f)

    notes = extract_footnotes(foot_chunks)
    paras = reflow_body(bodies)

    num = ch_id.split("_")[1]
    out = [f"# {int(num)}. {ch['title_en']}", ""]
    # drop the chapter-title lines that survive as body (all-caps fragments)
    for kind, text in paras:
        up = text.upper()
        if up in title_upper or (len(text) < 60 and up.replace(" ", "") in
                                 title_upper.replace(" ", "")):
            continue
        text = convert_markers(text, set(notes))
        if kind == "heading":
            out.append(f"## {text}")
        elif kind == "quote":
            out.append("> " + text)
        else:
            out.append(text)
        out.append("")
    if notes:
        out.append("## Notes")
        out.append("")
        for n in sorted(notes):
            out.append(f"[^{n}]: {convert_markers(notes[n], set())}")
            out.append("")

    dest = WORK / "en" / f"{ch_id}.md"
    dest.write_text("\n".join(out))
    body_marks = sorted(set(int(x) for x in re.findall(
        r"\[\^(\d+)\]", "\n".join(o for o in out if not o.startswith("[^")))))
    print(json.dumps({
        "chapter": ch_id, "paras": len(paras), "footnotes": len(notes),
        "note_numbers": sorted(notes), "body_markers": body_marks,
        "words": sum(len(t.split()) for _, t in paras),
    }))


if __name__ == "__main__":
    sys.exit(main())

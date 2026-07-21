# EN cleanup spec (W0 step 3)

Input: `work/en-raw/<chapter_id>.txt` (mechanically cleaned pdftotext reflow output).
Output: `work/en/<chapter_id>.md` — the canonical English source for translation.
The output must contain **every body sentence of the input exactly once** — no
paraphrase, no summarising, no dropped or invented text. You are re-formatting,
not editing.

## Known artifacts to fix

1. **Drop caps**: chapter openers appear as a lone capital on its own line followed
   by the rest of the word (`I\nn 1994, during…` → `In 1994, during…`).
2. **Hard line wraps**: prose is wrapped mid-sentence; rejoin each paragraph into a
   single line. Blank line between paragraphs. Paragraph boundaries in the print
   layout are usually visible as indentation or short final lines — use sense; when
   uncertain, prefer FEWER paragraph breaks (splitting is worse than joining here,
   because chunking never splits a paragraph).
3. **Running-head remnants**: stray short lines repeating the chapter title or
   `Farewell to Westphalia` mid-text — delete them (they are furniture, not content).
4. **Footnotes interleaved with body**: footnote citation text from page bottoms
   appears in the flow right after the page's body text (e.g. body reads
   `…will kill me.1` and a nearby line starts `Immaculée Ilibagiza and Steve Erwin,
   Left to Tell: …`). Rules:
   - Body marker: digit(s) attached directly after a word/punctuation (`me.1`,
     `million.2`, `cannibalism.’3`) → replace with `[^1]`, `[^2]` etc. Distinguish
     from real numbers in prose (years, counts, percentages) by position: markers sit
     flush after sentence punctuation or a closing quote and match the chapter's
     footnote sequence.
   - Move each footnote's text to a `## Notes` section at chapter end, formatted
     `[^N]: text` in numeric order. Footnote numbering restarts per chapter and must
     be continuous 1..N.
5. **Headings**: `# <Chapter title in Title Case>` once at top (e.g.
   `# 2. Nation States Are Obsolete Governance Technologies`), sections as
   `## 2.1 Preliminaries` etc., matching the TOC in `work/page-map.json` notes.
   Kill the all-caps `CHAPTER N` artifact lines.
6. **Block quotes**: indented/offset quotations (like the Left to Tell passage)
   become `>` blockquotes. Epigraphs with attribution: `>` quote + `> — Author,
   *Work*` line.
7. **Italics**: pdftotext loses italics. Restore `*…*` ONLY where unambiguous:
   titles of books/films/papers (*Left to Tell*), foreign phrases (*de facto*),
   ship-of-state style emphasis you can see from context (repeated internal
   monologue like *If they catch me, they will kill me.*). When unsure, leave plain.
8. **Unicode**: keep curly quotes/apostrophes as-is in EN; keep en/em dashes as
   printed.

## Special chapters

- `chapter_00_front_matter`: DROP the table-of-contents pages entirely (the site
  generates its own TOC). Keep: title block, copyright/license page, dedication,
  acknowledgements, the Timothy May epigraph. Use `## Acknowledgements` etc.
- `chapter_19_bibliography`: keep every entry VERBATIM, one entry per paragraph,
  `# Bibliography` heading. No footnote processing.
- `chapter_18_about_the_authors`: two bio paragraphs, `## Jarrad Hope` /
  `## Peter Ludlow` if headings are present in the raw text.

## Return value (JSON)

`{"chapter_id": "...", "en_words": N, "footnote_count": N,
"footnotes_continuous": true|false, "headings": ["# …", "## …"], "issues": ["…"]}`

`issues`: anything you could not resolve confidently (ambiguous footnote marker,
uncertain paragraph boundary, suspected missing text) — be honest, the verifier
uses this list.

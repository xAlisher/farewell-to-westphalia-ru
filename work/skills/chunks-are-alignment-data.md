---
id: chunks-are-alignment-data
title: Reuse pipeline chunk artifacts as EN↔RU alignment — never build an aligner
severity: medium
severity_reason: Rebuilding alignment wastes days and yields worse pairing than the free artifacts
created: "2026-08-19"
last_used: "2026-08-19"
status: active
---

## Problem

Any bilingual feature (parallel review pages, per-fragment issue mapping, TTS per-segment sync,
diff tooling) seems to need sentence/paragraph alignment between the EN original and RU
translation — an expensive, error-prone thing to build.

## Recipe

The alignment already exists, chunk-for-chunk and block-for-block:

- EN: `work/chunks/<chapter>.json` — list of `{id, kind, text}` in reading order.
- RU: `work/ru-parts/<chapter>/<id>.md` — the translation of exactly that chunk.
- Within a chunk, split both sides on blank lines: block counts match almost always because
  translators preserve markdown structure and the gate enforces it (measured: 1417/1417 block
  pairs across all 20 chapters, zero mismatches). On mismatch, fall back to one chunk-level pair.
- Carry `data-chunk="<id>"` through to any UI — it lets user feedback (issues) map straight back
  to the pipeline fragment that produced the text.

Implementation reference: `review_pairs()` in `build_site.py`; consumed by
`docs/review/chapter-NN.html` and `docs/assets/suggest.js` (chunk id in created issues).

## Why

The review split-view shipped in one evening because pairing was a zip(), not a model.

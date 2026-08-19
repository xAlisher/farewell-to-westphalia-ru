---
id: chapter-done-definition
title: Treat a chapter as done only on state.json draft_accepted + close commit
severity: high
severity_reason: Parts-on-disk look complete while judge/close never ran — ch14 shipped-looking but unclosed
created: "2026-08-19"
last_used: "2026-08-19"
status: active
---

## Problem

Translator agents write `work/ru-parts/<ch>/*.md` in the FIRST pipeline phase. A chapter can have
every part on disk while judging, revision, assembly, and the QA record never happened. Counting
files says "done"; the pipeline says otherwise.

## Recipe

A chapter is done iff ALL of:

```bash
python3 -c "import json; print(json.load(open('work/state.json'))['chapters']['<ch>']['status'])"
# → draft_accepted
git log --oneline --grep "ru(chapter_NN)" | head -1     # close commit exists
ls work/ru-draft/<ch>.md                                # assembled draft exists
```

Part counts (`ls work/ru-parts/<ch> | wc -l`) are a PROGRESS metric only, never a DONE metric.

## Why

2026-08-19: chapter 14 had 28/28 parts and was reported closed at the previous pause; journal
recon showed its close agent never ran and 14-N00 was never judged. The three-check definition
caught it before publication.

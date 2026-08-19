---
id: resume-from-disk
title: Resume an interrupted translate-chapters run from disk state, never the journal cache
severity: critical
severity_reason: The journal-cache resume re-ran 7 finished chapters and burned ~55 min of weekly limit producing zero new content
created: "2026-08-19"
last_used: "2026-08-19"
status: active
# basecamp_* fields N/A — this is a book-repo skill, no platform dependency
---

## Problem

A `Workflow({resumeFromRunId})` resume of an interrupted parallel run matches almost nothing in
the prefix cache (parallel scheduling reorders calls), so it silently re-runs completed agents
live — re-translating and re-committing already-accepted chapters.

## Recipe

1. Truth = `work/ru-parts/<ch>/` (parts on disk) + `git log` (`ru(chapter_NN): draft accepted`)
   + `work/state.json` (`draft_accepted`). The workflow journal is NOT truth.
2. Reconstruct what was judged: for the dead run, parse
   `<transcriptDir>/journal.jsonl` (started/result per agentId) + each `agent-<id>.jsonl` first
   user prompt → classify translate/judge/revise/close per chunk batch. (Pattern script:
   journal_recon.py — regex the prompts for "Chunk ids:" / "Batch: chapter".)
3. Gate-check on-disk unjudged parts: `python3 work/tools/gates.py check <ch> <ids>`.
4. Build args per batch: fully judged → omit; on disk + unjudged → `{ids, translate: []}`;
   partial → `{ids, translate: [missing]}`; absent → full translate.
5. Launch a FRESH run (`scriptPath` only, no `resumeFromRunId`).
6. **Watch the first 2–3 agents** (sample their prompts from the transcript dir after ~2 min)
   and confirm they target the expected chunks before walking away.

## Why

Verified twice (2026-08-15 burn, 2026-08-19 clean resume). Step 6 is the cheap insurance the
first resume skipped — the misfire was visible in minute two, caught in minute fifty-five.

# PROJECT_KNOWLEDGE — farewell-to-westphalia-ru

Accumulated wisdom for this repo. Raw captures go to `work/retro-log.md`; this file is the
distilled output. Translation-quality lessons live separately in `work/lessons.md` (written by
the pipeline's chapter-close agents).

## Repo layout facts that bite

- **`docs/` is the published website** (GitHub Pages, farewelltowestphalia.net). Never put
  internal notes, skills, or logs there — they'd go public. Internal workspace is `work/`.
- The site builds from `translations/ru/`, NOT from `work/ru-draft/`. Publishing means:
  sync `work/ru-draft/*.md` → `translations/ru/` (with the HTML-comment attribution header),
  then `python3 build_site.py`, commit `docs/`.
- `build_site.yml` regenerates the site on push to main. It failed silently on every run until
  2026-08-19 (bot lacked `permissions: contents: write`); if the site looks stale, check that
  workflow's push step first.
- Branch protection on main: PRs required; owner pushes/merges use bypass (`gh pr merge --admin`).

## Translation pipeline (w2) operational truths

- **A chapter is "done" only when `work/state.json` says `draft_accepted` AND a
  `ru(chapter_NN): draft accepted` commit exists.** Parts on disk in `work/ru-parts/` prove
  nothing — translator agents write files before the judge/close phases run (learned the hard
  way: chapter 14 sat "complete on disk" with its close never run).
- **Resume from disk + git, never from the Workflow journal cache** — `resumeFromRunId` across
  an interrupted parallel run cache-misses and re-runs finished chapters (2026-08-15: ~55 min of
  weekly limit spent re-translating 7 accepted chapters). Rebuild args from
  `work/ru-parts/` + journal recon instead; see `work/skills/resume-from-disk.md`.
- The workflow script supports surgical batches: `{ids, translate: [subset]}` — `[]` = judge-only
  (parts on disk, unjudged), subset = partial fill-in. This is what makes resume cheap.
- Workflow "escalated" entries can be **agent deaths, not quality failures** — always read the
  `<failures>` list before believing escalation counts (session-limit deaths masqueraded as 158
  escalations on 2026-08-14).
- Gate false positives to expect: ch19 bibliography (verbatim EN citations break the RU sentence
  counter), RU sentence merges with char-ratio ≈1.0. Judges already ruled these clean.
- `git add work/` in chapter-close commits sweeps in-progress files from OTHER chapters into the
  commit. Harmless but noisy; scope staging if history cleanliness matters.

## Review mode / site features

- The pipeline's chunk artifacts (`work/chunks/*.json` ↔ `work/ru-parts/<ch>/<id>.md`) ARE the
  EN↔RU alignment — the split-view review pages paired 1417/1417 blocks with zero fallbacks
  because translators preserve block structure (the gate enforces it). Reuse this for any
  bilingual feature; don't build an aligner.
- Reader suggestions: selection → `docs/assets/suggest.js` → Vercel fn `api/suggest.js`
  (project `ftw-suggest`, needs `GITHUB_TOKEN` env: fine-grained PAT, Issues R/W, this repo only)
  → issue with `reader-suggestion` label + chunk id. GitHub-prefill redirect is the fallback path.
- X/Twitter caches share-cards per-URL up to ~a week with no refresh button — after changing
  og:image, test with a query-string variant or the bare domain URL.

## Audiobook

- Engine decision + full pilot notes (incl. the transformers==4.57.1 pin for coqui-tts and the
  Sneg llama-server stop/start dance): `work/audiobook-decision.md`. Winner: edge-tts
  ru-RU-DmitryNeural; generation not yet run.

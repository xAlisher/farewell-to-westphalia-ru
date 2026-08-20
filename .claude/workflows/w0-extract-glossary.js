export const meta = {
  name: 'w0-extract-glossary',
  description: 'W0: clean EN source per chapter, verify vs PDF, chunk, build glossary/nouns/style-guide',
  phases: [
    { title: 'Clean', detail: '20 cleanup agents, one per chapter' },
    { title: 'Verify', detail: 'deterministic checks + PDF spot-checks, repair loop' },
    { title: 'Chunk', detail: 'freeze chunk boundaries' },
    { title: 'Scan', detail: 'proper-noun + term fan-out, style guide draft' },
    { title: 'Merge', detail: 'freeze glossary.json and proper-nouns.json' },
  ],
}

const ROOT = '/home/alisher/farewell-to-westphalia-ru'
const CHAPTERS = [
  'chapter_00_front_matter',
  'chapter_01_introduction',
  'chapter_02_nation_states_are_obsolete_governance_technologies',
  'chapter_03_post_state_governance',
  'chapter_04_new_conceptual_foundations',
  'chapter_05_technical_foundations_for_decentralised_cooperation',
  'chapter_06_new_tools_for_human_governance',
  'chapter_07_why_centralisation_is_the_problem',
  'chapter_08_are_cyberstates_the_answer',
  'chapter_09_exit_exile_and_access',
  'chapter_10_rethinking_sovereignty',
  'chapter_11_rights_and_responsibilities_of_blockchain_communities',
  'chapter_12_how_blockchain_communities_will_collaborate',
  'chapter_13_when_blockchain_communities_are_in_conflict',
  'chapter_14_a_deeper_dive_into_the_technology',
  'chapter_15_conceptual_limits_of_blockchain_governance',
  'chapter_16_are_blockchain_communities_inevitable',
  'chapter_17_values_and_the_technology_stack',
  'chapter_18_about_the_authors',
  'chapter_19_bibliography',
]

const CLEAN_SCHEMA = {
  type: 'object',
  properties: {
    chapter_id: { type: 'string' },
    en_words: { type: 'number' },
    footnote_count: { type: 'number' },
    footnotes_continuous: { type: 'boolean' },
    issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['chapter_id', 'en_words', 'footnote_count', 'footnotes_continuous', 'issues'],
}

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    chapter_id: { type: 'string' },
    ok: { type: 'boolean' },
    word_ratio: { type: 'number' },
    issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['chapter_id', 'ok', 'issues'],
}

const cleanupPrompt = (ch) => `You are a document-restoration specialist. Read the spec at ${ROOT}/work/tools/cleanup-spec.md FIRST and follow it exactly. Then read ${ROOT}/work/en-raw/${ch}.txt (raw pdftotext extraction) and ${ROOT}/work/page-map.json (for the chapter/section title list), and produce the canonical clean English markdown at ${ROOT}/work/en/${ch}.md using the Write tool. Chapter: ${ch}. Every body sentence of the input must appear exactly once in the output — you reformat, never edit or summarize. Return the JSON report described in the spec.`

const verifyPrompt = (ch) => `You are an extraction auditor for chapter ${ch}. The clean file is ${ROOT}/work/en/${ch}.md; the raw dump is ${ROOT}/work/en-raw/${ch}.txt; the PDF page range is in ${ROOT}/work/page-map.json; the PDF is at ${ROOT}/"Farewell to Westphalia (Jarrad Hope and Peter Ludlow) - FOSS edition.pdf" (quote the filename in shell commands).
Checks to run (use Bash for word counts and pdftotext):
1. Word count of clean .md within -3%/+3% of the raw .txt (raw includes furniture already stripped mechanically, so clean may be slightly lower; front matter chapter_00 excludes TOC pages so a big drop is EXPECTED there — instead verify title/copyright/dedication/acknowledgements/epigraph are all present).
2. Footnote markers [^N] in body are continuous 1..N and each has a matching [^N]: entry in the ## Notes block. Count both.
3. Headings match the section list for this chapter in page-map.json / the book TOC.
4. Spot-check 3 PDF pages spread across the chapter's range (near start, middle, near end): run pdftotext -f P -l P for each, and verify every body sentence on that page appears (verbatim modulo de-hyphenation/ligature fixes) in the clean .md. Footnote text on those pages must appear in the Notes block.
5. No leftover furniture: grep the clean file for lines that are just numbers or 'Farewell to Westphalia' running heads.
If everything passes return ok=true. If anything fails, return ok=false with precise issues (missing sentence quotes, marker numbers, heading mismatches). Do NOT fix the file yourself. Return JSON only.`

const repairPrompt = (ch, issues) => `You are repairing the clean English source ${ROOT}/work/en/${ch}.md. An auditor found these specific problems:\n${issues.map((s, i) => `${i + 1}. ${s}`).join('\n')}\nRead the spec ${ROOT}/work/tools/cleanup-spec.md, the current clean file, and the raw source ${ROOT}/work/en-raw/${ch}.txt (and the PDF via pdftotext for the affected pages if needed — path in ${ROOT}/work/page-map.json). Fix ONLY the reported problems with Edit. Do not rewrite unaffected text. Return a one-line summary of each fix.`

// ---- Phase 1+2: clean then verify, pipelined per chapter ----
phase('Clean')
const results = await pipeline(
  CHAPTERS,
  (ch) => agent(cleanupPrompt(ch), { label: `clean:${ch.slice(0, 18)}`, phase: 'Clean', schema: CLEAN_SCHEMA }),
  async (cleanReport, ch) => {
    let verdict = await agent(verifyPrompt(ch), { label: `verify:${ch.slice(0, 18)}`, phase: 'Verify', schema: VERIFY_SCHEMA })
    let attempts = 0
    while (verdict && !verdict.ok && attempts < 2) {
      attempts++
      log(`${ch}: verify failed (attempt ${attempts}) — repairing: ${verdict.issues.slice(0, 2).join(' | ')}`)
      await agent(repairPrompt(ch, verdict.issues), { label: `repair:${ch.slice(0, 18)}`, phase: 'Verify' })
      verdict = await agent(verifyPrompt(ch), { label: `reverify:${ch.slice(0, 15)}`, phase: 'Verify', schema: VERIFY_SCHEMA })
    }
    return { ch, clean: cleanReport, verdict }
  },
)

const failed = results.filter(Boolean).filter((r) => !r.verdict || !r.verdict.ok)
if (failed.length > 0) {
  log(`EXTRACTION GATE FAILED for ${failed.length} chapters: ${failed.map((f) => f.ch).join(', ')} — stopping before chunking`)
  return { gate: 'extraction', ok: false, failed: failed.map((f) => ({ ch: f.ch, issues: f.verdict ? f.verdict.issues : ['agent died'] })) }
}

// ---- Phase 3: chunk (single agent runs the deterministic script) ----
phase('Chunk')
const chunkReport = await agent(
  `Run: cd ${ROOT} && python3 work/tools/chunk.py — then sanity-check the output: read one generated file (work/chunks/chapter_02_*.json), confirm chunks have 8-12 sentences mostly, none split mid-paragraph (spot check 2 chunks against work/en source), and report total chunk count. If the script errors, fix work/tools/chunk.py minimally and rerun. Return a short summary with total body and notes chunk counts.`,
  { label: 'chunk-freeze', phase: 'Chunk' },
)

// ---- Phase 4: scans (nouns, terms, style guide) in parallel ----
phase('Scan')
const GROUPS = [
  CHAPTERS.slice(0, 4), CHAPTERS.slice(4, 7), CHAPTERS.slice(7, 10),
  CHAPTERS.slice(10, 13), CHAPTERS.slice(13, 16), CHAPTERS.slice(16, 20),
]
const SCAN_SCHEMA = {
  type: 'object',
  properties: {
    entries: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          en: { type: 'string' },
          type: { type: 'string' },
          context: { type: 'string' },
        },
        required: ['en', 'type', 'context'],
      },
    },
  },
  required: ['entries'],
}

const nounScan = (grp, i) => agent(
  `Scan these English chapters of a political-philosophy book about crypto governance: ${grp.map((c) => `${ROOT}/work/en/${c}.md`).join(', ')}. Extract EVERY proper noun: persons, organizations, places, work titles (books/papers/films), historical events, and coined/branded terms (e.g. 'network state', 'Impact DAO', product names). For each: en (canonical English form), type (person|org|place|work|event|coined), context (<=10 words showing usage). Deduplicate within your set. Be exhaustive — a missed name becomes an inconsistent translation later. Return JSON.`,
  { label: `nouns:g${i}`, phase: 'Scan', schema: SCAN_SCHEMA },
)

const termScan = (grp, i) => agent(
  `Scan these English chapters of a political-philosophy book about crypto governance: ${grp.map((c) => `${ROOT}/work/en/${c}.md`).join(', ')}. Extract load-bearing DOMAIN TERMS whose Russian rendering must be consistent book-wide: governance/political-theory vocabulary (sovereignty, nation state, exit/voice, legitimacy, jurisdiction...), crypto/blockchain vocabulary (smart contract, sharding, trustless, oracle, DAO, zero-knowledge...), and the book's own recurring conceptual phrases (decentralised-yet-cooperative governance, blockchain community, cyberstate, governance technology...). For each: en, type (political|crypto|book-concept), context (<=10 words). Skip ordinary words; include a term only if mistranslating or varying it would damage the book. Return JSON.`,
  { label: `terms:g${i}`, phase: 'Scan', schema: SCAN_SCHEMA },
)

const styleGuidePromise = agent(
  `Write the Russian style guide for translating 'Farewell to Westphalia' (Hope & Ludlow) at ${ROOT}/work/style-guide.md. First read: ${ROOT}/work/en/chapter_01_introduction.md and chapter_02 (for voice), and ${ROOT}/REVIEWING.md (existing 12-term glossary seed + review norms). The book's register: умная публицистика — scholarly but polemical, addressed to an intelligent general reader; first-person plural authorial voice ('we propose').
The guide must contain, with book-specific examples:
1. Register & voice: how to render the authorial 'we', rhetorical questions, irony; forbid наукообразие and канцелярит.
2. Nora Gal rules operationalized: verb over verbal noun; no «является»-crutch (prefer тире-copula or recast); no calqued word order; break который-chains; drop redundant possessives; concrete over abstract. Each rule with one EN→bad-RU→good-RU example FROM THIS BOOK's actual sentences.
3. Typography (Milchin): «ёлочки» outer, „лапки" inner; тире (—) with correct spacing; ranges with en-dash; ё policy: use ё consistently everywhere (project decision); numbers/percent/dates in Russian editorial style; footnote marker placement (after punctuation).
4. Names & titles: практическая транскрипция for personal names; work titles — Russian translation in «...» followed by (*original*) on first mention if no canonical RU translation exists, canonical RU title if one exists (e.g. published Russian editions); organizations — established RU form if exists else keep Latin; blockchain project names stay Latin (Bitcoin, Ethereum, Logos).
5. Quotes from other works: translate freshly unless a canonical published Russian translation is standard (Bible, Marx, famous manifestos — use canonical wording where identifiable).
6. Footnotes: bibliographic citations stay in ENGLISH verbatim (academic practice); explanatory prose in footnotes IS translated; mixed notes: translate prose, keep citation part in EN.
7. What NOT to do: no translator additions/explanations beyond a rare marked [прим. пер.]; no summarizing; no softening of polemics.
8. End with '## Changelog' section, entry 'v1 — initial (W0)'.
Keep it under 250 lines, imperative, example-driven. Return 'written' plus a 5-line summary.`,
  { label: 'style-guide', phase: 'Scan' },
)

const [nounSets, termSets, styleResult] = await parallel([
  () => parallel(GROUPS.map((g, i) => () => nounScan(g, i))),
  () => parallel(GROUPS.map((g, i) => () => termScan(g, i))),
  () => styleGuidePromise,
])

// ---- Phase 5: mergers freeze the reference files ----
phase('Merge')
const nounEntries = (nounSets || []).filter(Boolean).flatMap((s) => s.entries)
const termEntries = (termSets || []).filter(Boolean).flatMap((s) => s.entries)
log(`scan yield: ${nounEntries.length} noun candidates, ${termEntries.length} term candidates`)

const [nounMerge, termMerge] = await parallel([
  () => agent(
    `You are the terminology lead for the RU translation of 'Farewell to Westphalia'. Below are proper-noun candidates from 6 scanners (duplicates expected). Deduplicate and produce the frozen name base at ${ROOT}/work/proper-nouns.json (Write tool): a JSON array of {en, type, strategy ('transcribe'|'translate'|'keep-latin'), ru (fixed Russian form, or the Latin form if keep-latin), gender ('m'|'f'|'n'|null), declension (short note: declinable? how?), first_use_gloss (optional: gloss for first occurrence, e.g. 'в журнале Aeon'), note}. Rules: personal names via практическая транскрипция (check established Russian renderings for known figures — Виталик Бутерин, Джулиан Ассанж, Иммакюле Илибагиза, Тимоти Мэй, Сатоши Накамото...); blockchain/software project names stay Latin; org names use established RU forms where they exist (ООН, Всемирный банк) else Latin with gloss; work titles: canonical published RU title if it exists, else your translation in «...». Read ${ROOT}/work/style-guide.md first for the naming policy. Consistency beats cleverness. Return JSON {count, examples: [5 representative entries]}.\n\nCANDIDATES:\n${JSON.stringify(nounEntries)}`,
    { label: 'merge:nouns', phase: 'Merge', schema: { type: 'object', properties: { count: { type: 'number' } }, required: ['count'] } },
  ),
  () => agent(
    `You are the terminology lead for the RU translation of 'Farewell to Westphalia'. Below are domain-term candidates from 6 scanners (duplicates expected). Read ${ROOT}/work/style-guide.md and the 12-term seed table in ${ROOT}/REVIEWING.md first. Deduplicate, then decide the canonical Russian rendering for each term and produce ${ROOT}/work/glossary.json (Write tool): a JSON array of {en, ru, pos, decline (declension/usage note), forbidden_variants (array of Russian renderings that must NOT appear — the likely wrong/rival translations), note (when to deviate, e.g. sg/pl nuances), example (one EN sentence fragment -> RU rendering)}. Think hard about the load-bearing choices: 'blockchain community' (canonical: блокчейн-сообщество), 'network state' (сетевое государство), 'cyberstate', 'nation state' (национальное государство), 'governance' (context-split: управление vs государственное управление vs система управления — document the split rule), 'trustless', 'exit/voice' (Hirschman: выход/голос), 'sovereignty' (суверенитет), 'sharding' (шардирование). Target 80-150 terms — merge near-duplicates, drop terms that don't recur. Return JSON {count, examples: [5 representative entries]}.\n\nCANDIDATES:\n${JSON.stringify(termEntries)}`,
    { label: 'merge:terms', phase: 'Merge', schema: { type: 'object', properties: { count: { type: 'number' } }, required: ['count'] } },
  ),
])

return {
  gate: 'extraction', ok: true,
  chapters: results.filter(Boolean).map((r) => ({ ch: r.ch, words: r.clean ? r.clean.en_words : null, footnotes: r.clean ? r.clean.footnote_count : null })),
  chunks: chunkReport,
  nouns: nounMerge, terms: termMerge,
  style: typeof styleResult === 'string' ? styleResult.slice(0, 300) : styleResult,
}
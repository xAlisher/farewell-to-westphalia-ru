export const meta = {
  name: 'translate-chapters',
  description: 'Translate chapters EN→RU: batch translate → gate → 3 MQM judges → targeted revision (≤3 passes) → escalation → chapter close',
  phases: [
    { title: 'Translate', detail: 'batches of ~4 chunks, sequential within chapter' },
    { title: 'Judge', detail: '3 MQM personas per batch' },
    { title: 'Revise', detail: 'targeted fixes, ≤3 passes, escalation on failure' },
    { title: 'Close', detail: 'assemble chapter, lessons, commit' },
  ],
}

// args: { chapters: [{ id, batches: [[chunkId,...], ...] }] }
const ROOT = '/home/alisher/farewell-to-westphalia-ru'
const W = `${ROOT}/work`

const TRANS_SCHEMA = {
  type: 'object',
  properties: {
    chunks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          gate_ok: { type: 'boolean' },
          gate_note: { type: 'string' },
        },
        required: ['id', 'gate_ok'],
      },
    },
    summary_delta: { type: 'string' },
    notes: { type: 'array', items: { type: 'string' } },
  },
  required: ['chunks'],
}

const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    errors: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          chunk_id: { type: 'string' },
          cat: { type: 'string', enum: ['accuracy', 'omission', 'addition', 'terminology', 'register', 'naturalness', 'mechanics'] },
          sev: { type: 'string', enum: ['critical', 'major', 'minor'] },
          src_span: { type: 'string' },
          tgt_span: { type: 'string' },
          note: { type: 'string' },
          fix_hint: { type: 'string' },
        },
        required: ['chunk_id', 'cat', 'sev', 'note'],
      },
    },
    batch_note: { type: 'string' },
  },
  required: ['errors'],
}

const REV_SCHEMA = {
  type: 'object',
  properties: {
    fixed: { type: 'array', items: { type: 'string' } },
    gate_ok: { type: 'boolean' },
    notes: { type: 'array', items: { type: 'string' } },
  },
  required: ['fixed', 'gate_ok'],
}

const translatorPrompt = (ch, ids, extra) => `Translate a batch of «Farewell to Westphalia» EN→RU.
Chapter: ${ch}. Chunk ids: ${ids.join(', ')}.
Read and follow ${W}/tools/translator-prompt.md EXACTLY (it lists the required reading order: style guide, lessons, glossary slice via slice.py, chapter summary, preceding RU parts).
The EN text for each chunk id is in ${W}/chunks/${ch}.json (field "text"; find your ids there).
Write each chunk's Russian markdown to ${W}/ru-parts/${ch}/<chunk_id>.md, run the gate script, self-fix until the gate is clean or you can justify a false positive, append the summary delta to ${W}/summaries/${ch}.md.${extra || ''}
Return the JSON described in the instructions.`

const judgePersonas = [
  {
    key: 'adequacy',
    brief: 'You are the ADEQUACY judge: a bilingual auditor obsessed with completeness and precision. Compare EN and RU sentence by sentence. Your lane: accuracy, omission, addition. Every number, name, qualifier, and clause must survive. You do NOT nitpick style — free restructuring is fine when meaning is intact.',
  },
  {
    key: 'stylist',
    brief: 'You are the RUSSIAN STYLIST judge: a Nora-Gal-school literary editor. FIRST read the Russian alone as a Russian text — flag everything that reads as translationese: calques, anglicized syntax, канцелярит, «является»-crutches, который-chains, dead verbal nouns, lost irony or polemic energy. THEN glance at the EN only to confirm a flagged spot is the translator\'s fault. Your lane: naturalness, register. You do NOT re-litigate meaning if it reads well.',
  },
  {
    key: 'termmech',
    brief: 'You are the TERMINOLOGY & MECHANICS judge. Check every glossary term and proper noun in this batch against work/glossary.json and work/proper-nouns.json (canonical forms and forbidden_variants), and all mechanics: «ёлочки»/„лапки", тире, ё-policy, number formatting, footnote markers [^N] placement and Notes entries, markdown structure vs the EN chunk. Your lane: terminology, mechanics.',
  },
]

const judgePrompt = (persona, ch, ids) => `${persona.brief}
Read the spec ${W}/tools/judge-spec.md and follow its error taxonomy and JSON format exactly.
Batch: chapter ${ch}, chunk ids ${ids.join(', ')}.
EN: ${W}/chunks/${ch}.json (match ids). RU: ${W}/ru-parts/${ch}/<chunk_id>.md.
Reference: ${W}/glossary.json, ${W}/proper-nouns.json, ${W}/style-guide.md.
Return JSON only.`

const revisionPrompt = (ch, ids, actionable, minors, pass) => `You are the revision editor for chapter ${ch}, chunks ${ids.join(', ')} (pass ${pass} of max 3).
RU files: ${W}/ru-parts/${ch}/<chunk_id>.md. EN source: ${W}/chunks/${ch}.json. Style guide: ${W}/style-guide.md.
Fix EXACTLY these confirmed errors (Edit tool; do not rewrite unaffected text):
${JSON.stringify(actionable, null, 1)}
${minors.length ? `Optional minor polish (apply only where the fix is unambiguous and safe):\n${JSON.stringify(minors, null, 1)}` : ''}
After editing, re-run: python3 ${W}/tools/gates.py check ${ch} ${ids.join(' ')} — and fix any regression.
Return JSON {fixed: [one line per error], gate_ok, notes}.`

const escalatePrompt = (ch, cid, history) => `FRESH RE-TRANSLATION of a problem chunk. Chapter ${ch}, chunk ${cid}.
Previous attempts failed review. Error history (avoid ALL of these failure patterns):
${JSON.stringify(history, null, 1)}
Read ${W}/tools/translator-prompt.md and follow it fully (style guide, lessons, slice.py for terms, summary, adjacent RU parts for voice). EN text: ${W}/chunks/${ch}.json id ${cid}. Translate from scratch — do NOT read the existing RU part first; overwrite ${W}/ru-parts/${ch}/${cid}.md with your version, run the gate, self-fix.
Return the standard translator JSON.`

function actionableErrors(judgeResults) {
  const all = []
  judgeResults.filter(Boolean).forEach((jr, ji) =>
    (jr.errors || []).forEach((e) => all.push({ ...e, judge: ji })))
  const judgeCount = {}
  for (const e of all) {
    const k = `${e.chunk_id}|${e.cat}`
    judgeCount[k] = judgeCount[k] || new Set()
    judgeCount[k].add(e.judge)
  }
  const act = all.filter((e) =>
    e.sev === 'critical' ||
    (e.sev === 'major' && judgeCount[`${e.chunk_id}|${e.cat}`].size >= 2))
  const minors = all.filter((e) => !act.includes(e) && e.sev !== 'minor')
    .concat(all.filter((e) => e.sev === 'minor').slice(0, 10))
  return { act, minors, all }
}

async function runChapter(chapter) {
  const ch = chapter.id
  const short = ch.split('_').slice(0, 2).join('_')
  const chapterErrors = []
  const escalated = []
  const batchStats = []

  for (let bi = 0; bi < chapter.batches.length; bi++) {
    const ids = chapter.batches[bi]
    // Pass 1: translate (translator self-runs the deterministic gate)
    let trans = await agent(translatorPrompt(ch, ids),
      { label: `tr:${short}:b${bi}`, phase: 'Translate', schema: TRANS_SCHEMA })
    if (!trans) { escalated.push(...ids.map((c) => ({ chunk: c, reason: 'translator agent died' }))); continue }

    // Retry chunks whose gate failed without a credible justification
    const gateFails = (trans.chunks || []).filter((c) => !c.gate_ok && !(c.gate_note && c.gate_note.length > 20))
    for (const gf of gateFails) {
      await agent(translatorPrompt(ch, [gf.id], '\nNOTE: previous attempt failed the alignment gate — check for dropped sentences/footnote markers.'),
        { label: `tr-retry:${short}:${gf.id}`, phase: 'Translate', schema: TRANS_SCHEMA })
    }

    // Judge: 3 personas in parallel
    let judges = await parallel(judgePersonas.map((p) => () =>
      agent(judgePrompt(p, ch, ids), { label: `j-${p.key}:${short}:b${bi}`, phase: 'Judge', schema: JUDGE_SCHEMA })))
    let { act, minors, all } = actionableErrors(judges)
    chapterErrors.push(...all)

    // Revision loop: passes 2 and 3
    let pass = 1
    while (act.length > 0 && pass < 3) {
      pass++
      log(`${short} b${bi}: pass ${pass} — ${act.length} actionable errors (${act.map((e) => e.cat).join(',')})`)
      await agent(revisionPrompt(ch, ids, act, minors, pass),
        { label: `rev:${short}:b${bi}:p${pass}`, phase: 'Revise', schema: REV_SCHEMA })
      const confirm = await agent(
        `${judgePersonas[0].brief}\nRE-CHECK after revision. Verify the previously flagged errors are fixed and no new critical/major defects appeared. Read ${W}/tools/judge-spec.md for format. Previously actionable:\n${JSON.stringify(act, null, 1)}\nBatch: chapter ${ch}, chunks ${ids.join(', ')}. EN ${W}/chunks/${ch}.json, RU ${W}/ru-parts/${ch}/. Return remaining errors as JSON (empty errors array if clean).`,
        { label: `confirm:${short}:b${bi}:p${pass}`, phase: 'Judge', schema: JUDGE_SCHEMA })
      const re = actionableErrors([confirm])
      act = re.act; minors = re.minors
    }

    // Escalation: fresh retranslate per still-failing chunk, then full judge round
    if (act.length > 0) {
      const failChunks = [...new Set(act.map((e) => e.chunk_id))]
      for (const cid of failChunks) {
        const history = chapterErrors.filter((e) => e.chunk_id === cid)
        await agent(escalatePrompt(ch, cid, history),
          { label: `esc:${short}:${cid}`, phase: 'Revise', schema: TRANS_SCHEMA })
        const rejudge = await parallel(judgePersonas.map((p) => () =>
          agent(judgePrompt(p, ch, [cid]), { label: `esc-j:${short}:${cid}`, phase: 'Judge', schema: JUDGE_SCHEMA })))
        const fin = actionableErrors(rejudge)
        if (fin.act.length > 0) {
          escalated.push({ chunk: cid, reason: 'failed after fresh retranslation', errors: fin.act })
          log(`${short}: ESCALATED ${cid} — ${fin.act.length} unresolved`)
        }
      }
    }
    batchStats.push({ batch: bi, chunks: ids.length, passes: pass, errors_seen: all.length })
  }

  // Chapter close
  const errDigest = {
    total: chapterErrors.length,
    by_cat: chapterErrors.reduce((m, e) => { m[e.cat] = (m[e.cat] || 0) + 1; return m }, {}),
    by_sev: chapterErrors.reduce((m, e) => { m[e.sev] = (m[e.sev] || 0) + 1; return m }, {}),
    samples: chapterErrors.filter((e) => e.sev !== 'minor').slice(0, 12),
    escalated,
  }
  const close = await agent(
    `You are the chapter closer for ${ch}.
1. Assemble the final chapter: read chunk order from ${W}/chunks/${ch}.json, concatenate the RU parts from ${W}/ru-parts/${ch}/ in that order (body chunks as body, notes chunks under a final '## Примечания' heading), write ${W}/ru-draft/${ch}.md.
2. Verify: every chunk id has a part; footnote markers in body are continuous 1..N and each has a note entry; headings hierarchy intact; no duplicated or missing text at chunk seams (read 3 seams to check flow).
3. QA record: write ${W}/qa/${ch}/summary.json with this error digest plus your assembly checks: ${JSON.stringify(errDigest)}
4. Lessons: if the digest shows RECURRING patterns (same cat 3+ times), append concise bullet(s) to ${W}/lessons.md under a '## ${ch}' heading — pattern, example, rule to prevent it. Skip one-offs.
5. Update ${W}/state.json: set chapters['${ch}'].status = '${escalated.length > 0 ? 'draft_with_escalations' : 'draft_accepted'}'.
6. Commit: cd ${ROOT} && git add work/ && git commit -m 'ru(${short}): draft ${escalated.length > 0 ? 'with ' + escalated.length + ' escalations' : 'accepted'}'
Return JSON {assembled: true/false, footnotes_ok: true/false, seams_ok: true/false, issues: []}.`,
    { label: `close:${short}`, phase: 'Close', schema: { type: 'object', properties: { assembled: { type: 'boolean' }, footnotes_ok: { type: 'boolean' }, seams_ok: { type: 'boolean' }, issues: { type: 'array', items: { type: 'string' } } }, required: ['assembled', 'footnotes_ok', 'issues'] } })

  return { chapter: ch, batches: batchStats, errors: errDigest.by_sev, escalated: escalated.length, close }
}

const input = typeof args === 'string' ? JSON.parse(args) : args
if (!input || !input.chapters) throw new Error('args.chapters missing — pass {chapters:[{id,batches}]}')
const chapterResults = await parallel(input.chapters.map((c) => () => runChapter(c)))
return { chapters: chapterResults.filter(Boolean) }

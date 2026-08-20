#!/usr/bin/env python3
"""
Synonym Rotation Pass — Context-Aware Russian Editorial
--------------------------------------------------------
Runs AFTER translate_to_russian.py, BEFORE audiobook_pass.py.

Unlike mechanical find-and-replace, this script:
  - Sends each paragraph to Claude WITH surrounding context (prev + next paragraph)
  - Asks Claude to make ONE editorial decision per target word occurrence
  - Only rotates when rotation genuinely improves the text
  - Tracks what synonym was used in the preceding N paragraphs to avoid
    replacing one repetition with another
  - Preserves meaning above all — if no synonym fits, keeps the original

Target patterns (the ones that wear the ear down):
  - "управление" / governance  (315 occurrences)
  - "децентрализован*"          (161 occurrences)
  - "Предварительные замечания" / Preliminaries (32 × subsection openers)
  - "как мы увидим" / as we will see  (16 occurrences)
  - "мы рассмотрим/обсудим"    (66 "we will" constructs)
  - "в этой главе"              (36 "this chapter" references)
  - "национальное государство"  (high frequency)

Usage:
    python synonym_rotation.py \
        --input-dir  /repo/translations/ru \
        --output-dir /repo/translations/ru_rotated \
        --push-repo  /repo \
        --push-subdir translations/ru_rotated \
        --push

Requires:  pip install anthropic gitpython
"""

import os
import re
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from collections import deque

try:
    import anthropic
except ImportError:
    sys.exit("pip install anthropic")

try:
    import git
except ImportError:
    sys.exit("pip install gitpython")


# ─── Model ────────────────────────────────────────────────────────────────────

MODEL      = "claude-opus-4-5"
MAX_TOKENS = 1024   # rotation decisions are short
CONTEXT_WINDOW = 4  # paragraphs of context fed to model (prev + current + next)
MEMORY_WINDOW  = 6  # remember last N synonyms used per target, avoid repeating

# ─── Rotation targets ─────────────────────────────────────────────────────────
#
# Each entry defines:
#   pattern   — regex that fires in Russian text
#   anchor    — the canonical form shown to the editor prompt
#   pool      — ordered synonym pool (rich → lean, formal → neutral)
#   note      — editorial guidance passed to the model

ROTATION_TARGETS = [
    {
        "id": "governance",
        "pattern": re.compile(
            r'\b(управлени[еяию]|управлением|систем[аы]\s+управлени[яе])\b',
            re.IGNORECASE
        ),
        "anchor": "управление",
        "pool": [
            "государственное устройство",
            "форма правления",
            "политический порядок",
            "регулирование",
            "властные структуры",
            "политическое управление",
            "система власти",
            "общественный порядок",
        ],
        "note": (
            "Choose the synonym that best fits the EXACT meaning in this sentence. "
            "'Управление' can mean governance-as-institution, governance-as-process, "
            "or governance-as-quality — pick the Russian word that captures which one. "
            "If the sentence discusses technical blockchain governance, 'регулирование' "
            "or 'политический порядок' may work. If it discusses state legitimacy, "
            "'государственное устройство' fits better. "
            "If no synonym fits without shifting the meaning, return the original."
        ),
    },
    {
        "id": "decentralised",
        "pattern": re.compile(
            r'\bдецентрализован\w+\b',
            re.IGNORECASE
        ),
        "anchor": "децентрализованный",
        "pool": [
            "распределённый",
            "горизонтальный",
            "немонополизированный",
            "самоорганизующийся",
            "сетевой",
            "негосударственный",
            "автономный",
        ],
        "note": (
            "Only rotate if the synonym preserves the TECHNICAL meaning. "
            "'Распределённый' fits distributed-systems contexts. "
            "'Горизонтальный' fits organisational/governance contexts. "
            "'Самоорганизующийся' fits emergent/organic governance. "
            "'Автономный' fits cases where independence from central authority is the point. "
            "NEVER use 'негосударственный' if the sentence contrasts blockchain with governments — "
            "it would be circular. When in doubt, keep the original."
        ),
    },
    {
        "id": "preliminaries",
        "pattern": re.compile(
            r'\bПредварительные\s+замечания\b|\bПрелиминарии\b',
            re.IGNORECASE
        ),
        "anchor": "Предварительные замечания",
        "pool": [
            "Вводные положения",
            "К постановке вопроса",
            "Прежде всего",
            "Исходные понятия",
            "Отправная точка",
            "О чём пойдёт речь",
            "Контекст и предпосылки",
            "Несколько слов для начала",
        ],
        "note": (
            "This is a subsection heading that appears 32 times. "
            "Each chapter's x.1 section introduces the chapter's main question. "
            "Choose a heading that REFLECTS what this specific chapter is about — "
            "read the first paragraph below the heading to understand the chapter's topic, "
            "then pick the variant that best frames it. "
            "Avoid generic-sounding variants if a more specific one fits. "
            "Vary across chapters — check the recent_synonyms list and don't repeat."
        ),
    },
    {
        "id": "as_we_will_see",
        "pattern": re.compile(
            r'\bкак\s+мы\s+(увидим|покажем|установим|выясним)\b'
            r'|\bкак\s+будет\s+показано\b'
            r'|\bкак\s+станет\s+ясно\b',
            re.IGNORECASE
        ),
        "anchor": "как мы увидим",
        "pool": [
            "анализ покажет",
            "далее станет очевидно",
            "это выяснится ниже",
            "как будет показано в следующих главах",
            "последующее изложение покажет",
            "к этому мы ещё вернёмся",
            "дальнейший разбор прояснит",
        ],
        "note": (
            "This forward-reference phrase is heavily overused (16 times). "
            "Choose based on WHAT is being anticipated: "
            "if the payoff is in the next paragraph, use 'далее станет очевидно'; "
            "if it's chapters away, use 'как будет показано в следующих главах'; "
            "if it's an argument being built, use 'анализ покажет'; "
            "if the authors will revisit the point, use 'к этому мы ещё вернёмся'. "
            "The substitution must read naturally in the sentence."
        ),
    },
    {
        "id": "we_will_discuss",
        "pattern": re.compile(
            r'\bмы\s+(рассмотрим|обсудим|изучим|проанализируем|остановимся\s+на)\b',
            re.IGNORECASE
        ),
        "anchor": "мы рассмотрим",
        "pool": [
            "речь пойдёт о",
            "предметом анализа станет",
            "обратимся к",
            "в центре внимания окажется",
            "нас будет интересовать",
            "следующий раздел посвящён",
            "подробнее об этом — в",
        ],
        "note": (
            "These are authorial signposting phrases. "
            "Rotate toward more impersonal/editorial constructions when the sentence "
            "is announcing a chapter or section topic. "
            "Keep 'мы' constructions when the authors are expressing a PERSONAL stance "
            "or making a claim, not just signposting. "
            "The substitution must be grammatically correct in the sentence."
        ),
    },
    {
        "id": "this_chapter",
        "pattern": re.compile(
            r'\b(в\s+этой\s+главе|в\s+данной\s+главе|настоящая\s+глава)\b',
            re.IGNORECASE
        ),
        "anchor": "в этой главе",
        "pool": [
            "в этом разделе",
            "здесь",
            "на этих страницах",
            "в рамках настоящего исследования",
            "в данном контексте",
        ],
        "note": (
            "Only rotate when the phrase is purely structural/signposting. "
            "If the sentence contrasts THIS chapter with ANOTHER chapter, "
            "keep the original — the contrast depends on the word 'глава'. "
            "'Здесь' works for brief references. "
            "'На этих страницах' works for longer thematic statements."
        ),
    },
    {
        "id": "nation_state",
        "pattern": re.compile(
            r'\b(национальн\w+\s+государств\w+|государств\w+-наци\w+)\b',
            re.IGNORECASE
        ),
        "anchor": "национальное государство",
        "pool": [
            "суверенное государство",
            "государственное образование",
            "политическое образование",
            "традиционное государство",
            "современное государство",
        ],
        "note": (
            "Be conservative. 'Национальное государство' is a precise political-theory term. "
            "Only rotate when the sentence is using it loosely (referring to states in general). "
            "When the Westphalian sovereignty concept is explicitly being discussed, "
            "keep the original term — it's the precise term of art. "
            "'Суверенное государство' is the closest safe synonym."
        ),
    },
]


# ─── System prompt ─────────────────────────────────────────────────────────────

def make_system_prompt(target: dict, recent_synonyms: list[str]) -> str:
    pool_str = "\n".join(f"  — {s}" for s in target["pool"])
    recent_str = (
        "Synonyms used in recent paragraphs (avoid repeating these): "
        + ", ".join(f'«{s}»' for s in recent_synonyms)
        if recent_synonyms else "No recent synonyms yet."
    )
    return f"""You are a senior Russian literary editor working on a translation of an academic book on political philosophy and blockchain governance for an audiobook recording.

Your task: examine ONE paragraph and decide whether to replace the marked word/phrase «{target["anchor"]}» with a better synonym — or keep the original.

AVAILABLE SYNONYMS:
{pool_str}

EDITORIAL GUIDANCE:
{target["note"]}

{recent_str}

RESPONSE FORMAT — return ONLY a JSON object, nothing else:
{{
  "decision": "replace" | "keep",
  "replacement": "the exact synonym chosen (only if decision=replace)",
  "reason": "one sentence explaining why"
}}

Rules:
- If replacing, output the FULL replacement phrase as it should appear grammatically in Russian
- Adjust case/declension so the replacement is grammatically correct in context
- If the original is better, say "keep" — do not rotate for the sake of rotating
- Never invent synonyms outside the provided pool
- Never change meaning, never add content, never summarise"""


# ─── Paragraph processing ─────────────────────────────────────────────────────

def split_paragraphs(text: str) -> list[str]:
    """Split on double newlines, preserve them for reconstruction."""
    return re.split(r'(\n\n+)', text)


def find_target_in_paragraph(para: str, target: dict) -> bool:
    return bool(target["pattern"].search(para))


def call_rotation(client, system: str, prev_para: str,
                  current_para: str, next_para: str) -> dict:
    context = ""
    if prev_para.strip():
        context += f"[PRECEDING PARAGRAPH FOR CONTEXT]\n{prev_para.strip()}\n\n"
    context += f"[PARAGRAPH TO EDIT — contains the target word]\n{current_para.strip()}"
    if next_para.strip():
        context += f"\n\n[FOLLOWING PARAGRAPH FOR CONTEXT]\n{next_para.strip()}"

    for attempt in range(4):
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": context}],
            )
            raw = msg.content[0].text.strip()
            # Strip any markdown fences if model added them
            raw = re.sub(r'^```json\s*|\s*```', '', raw, flags=re.MULTILINE).strip()
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"    JSON parse error (attempt {attempt+1}): {e} — raw: {raw[:200]}")
            time.sleep(2)
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"    Rate limited — waiting {wait}s…")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503):
                wait = 30 * (attempt + 1)
                print(f"    Overloaded — waiting {wait}s…")
                time.sleep(wait)
            else:
                raise
    return {"decision": "keep", "reason": "API failure — kept original"}


def apply_rotation(paragraph: str, target: dict, replacement: str) -> str:
    """Replace first match of the pattern with the chosen replacement."""
    def _replace(m):
        # Match the case of the original (capitalised if sentence-start)
        orig = m.group(0)
        if orig[0].isupper():
            return replacement[0].upper() + replacement[1:]
        return replacement
    return target["pattern"].sub(_replace, paragraph, count=1)


def process_chapter(client, text: str, chapter_name: str) -> tuple[str, dict]:
    """
    Run all rotation targets over the chapter text.
    Returns (modified_text, stats).
    """
    stats = {t["id"]: {"seen": 0, "rotated": 0, "kept": 0} for t in ROTATION_TARGETS}
    parts = split_paragraphs(text)

    # Work on actual paragraph indices (skip separator tokens)
    para_indices = [i for i, p in enumerate(parts) if not re.fullmatch(r'\n+', p)]

    for target in ROTATION_TARGETS:
        recent_synonyms: deque = deque(maxlen=MEMORY_WINDOW)
        rotations_this_target = 0

        for idx, pi in enumerate(para_indices):
            para = parts[pi]
            if not find_target_in_paragraph(para, target):
                continue

            stats[target["id"]]["seen"] += 1

            # Gather context paragraphs
            prev_para = parts[para_indices[idx - 1]] if idx > 0 else ""
            next_para = parts[para_indices[idx + 1]] if idx < len(para_indices) - 1 else ""

            system = make_system_prompt(target, list(recent_synonyms))

            result = call_rotation(client, system, prev_para, para, next_para)
            time.sleep(0.3)

            if result.get("decision") == "replace" and result.get("replacement"):
                replacement = result["replacement"]
                parts[pi] = apply_rotation(para, target, replacement)
                recent_synonyms.append(replacement)
                stats[target["id"]]["rotated"] += 1
                rotations_this_target += 1
                print(f"    ✓ [{target['id']}] «{target['anchor']}» → «{replacement}»")
                print(f"      reason: {result.get('reason', '')[:80]}")
            else:
                stats[target["id"]]["kept"] += 1
                print(f"    · [{target['id']}] kept — {result.get('reason', '')[:60]}")

        if rotations_this_target:
            print(f"  [{target['id']}] {rotations_this_target} rotations in {chapter_name}")

    return "".join(parts), stats


# ─── GitHub ────────────────────────────────────────────────────────────────────

def commit_chapter(repo_path: str, subdir: str, filename: str,
                   content: str, chapter_num: int, do_push: bool):
    repo = git.Repo(repo_path)
    target_dir = Path(repo_path) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    fpath = target_dir / filename
    fpath.write_text(content, encoding="utf-8")
    rel = str(fpath.relative_to(repo_path))
    repo.index.add([rel])
    msg = (
        f"translation(ru): synonym rotation chapter {chapter_num:02d}\n\n"
        f"Context-aware synonym variation pass.\n"
        f"Date: {datetime.now().strftime('%Y-%m-%d')}"
    )
    repo.index.commit(msg)
    print(f"  Committed: {rel}")
    if do_push:
        repo.remote("origin").push()
        print("  Pushed.")


def write_rotation_report(output_dir: Path, all_stats: dict):
    lines = ["# Synonym Rotation Report\n"]
    for chapter, stats in all_stats.items():
        lines.append(f"\n## {chapter}\n")
        for target_id, s in stats.items():
            pct = round(s["rotated"] / s["seen"] * 100) if s["seen"] else 0
            lines.append(
                f"- **{target_id}**: {s['seen']} occurrences — "
                f"{s['rotated']} rotated ({pct}%), {s['kept']} kept as-is\n"
            )
    report_path = output_dir / "rotation_report.md"
    report_path.write_text("".join(lines), encoding="utf-8")
    print(f"\nRotation report written to {report_path}")


# ─── Progress ─────────────────────────────────────────────────────────────────

def load_progress(path: str) -> dict:
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return {"completed": []}


def save_progress(path: str, state: dict):
    with open(path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Context-aware synonym rotation for Russian translation")
    parser.add_argument("--input-dir",  required=True,
                        help="Dir with translated chapter_*.md files")
    parser.add_argument("--output-dir", required=True,
                        help="Where to write rotated chapter files")
    parser.add_argument("--push-repo",  default=None)
    parser.add_argument("--push-subdir", default="translations/ru_rotated")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        api_key = input("Anthropic API key: ").strip()
    client = anthropic.Anthropic(api_key=api_key)

    input_dir  = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    progress_file = output_dir / ".rotation_progress.json"
    state = load_progress(str(progress_file))

    chapter_files = sorted(
        input_dir.glob("chapter_*.md"),
        key=lambda p: int(re.search(r"chapter_(\d+)", p.stem).group(1))
    )
    if not chapter_files:
        sys.exit(f"No chapter_*.md files in {input_dir}")

    print(f"Found {len(chapter_files)} chapters. Starting rotation pass…\n")
    all_stats = {}

    for md_path in chapter_files:
        if md_path.name in state["completed"]:
            print(f"Skipping {md_path.name} (done).")
            continue

        m = re.search(r"chapter_(\d+)", md_path.stem)
        chapter_num = int(m.group(1)) if m else 0
        print(f"\n── Chapter {chapter_num}: {md_path.stem}")

        text = md_path.read_text(encoding="utf-8")

        try:
            rotated_text, stats = process_chapter(client, text, md_path.name)
        except Exception as e:
            print(f"ERROR: {e}")
            save_progress(str(progress_file), state)
            sys.exit(1)

        out_path = output_dir / md_path.name
        out_path.write_text(rotated_text, encoding="utf-8")
        all_stats[md_path.name] = stats

        if args.push_repo:
            commit_chapter(args.push_repo, args.push_subdir, md_path.name,
                           rotated_text, chapter_num, args.push)

        state["completed"].append(md_path.name)
        save_progress(str(progress_file), state)

    write_rotation_report(output_dir, all_stats)
    print(f"\nDone. Rotated chapters written to {output_dir}")


if __name__ == "__main__":
    main()

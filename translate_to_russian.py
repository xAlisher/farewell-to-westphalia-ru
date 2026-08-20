#!/usr/bin/env python3
"""
Farewell to Westphalia — Russian Translation Pipeline
------------------------------------------------------
Usage:
  python translate_to_russian.py \
    --input "Farewell_to_Westphalia__Jarrad_Hope_and_Peter_Ludlow__-_FOSS_edition.pdf" \
    --repo-path /path/to/your/repo \
    --repo-subdir translations/ru          # optional subfolder inside repo

Requires:
  pip install anthropic gitpython

The script will ask for your Anthropic API key on first run (or set ANTHROPIC_API_KEY env var).
It saves a progress.json file so you can stop and resume at any time.
"""

import os
import re
import sys
import json
import time
import argparse
import textwrap
from pathlib import Path
from datetime import datetime

try:
    import anthropic
except ImportError:
    sys.exit("Run: pip install anthropic")

try:
    import git
except ImportError:
    sys.exit("Run: pip install gitpython")


# ─── Configuration ────────────────────────────────────────────────────────────

CHUNK_WORDS      = 2500          # words per translation chunk
MODEL            = "claude-opus-4-5"
MAX_TOKENS       = 4096
RETRY_WAIT       = 30            # seconds to wait on rate limit / overload
MAX_RETRIES      = 5

BOOK_TITLE_EN    = "Farewell to Westphalia"
BOOK_TITLE_RU    = "Прощай, Вестфалия"
BOOK_SUBTITLE_RU = "Криптосуверенитет и управление в постнациональную эпоху"
AUTHORS          = "Джаррад Хоуп и Питер Лудлоу"

# Chapter heading patterns (matches "1.", "2.1", "Appendix", "Bibliography", etc.)
CHAPTER_RE = re.compile(
    r'^(?:(\d+)\.\s+[A-Z]|Appendix|Bibliography|References|Index|Conclusion|Preface|Introduction)',
    re.MULTILINE
)

# ─── Prompts ──────────────────────────────────────────────────────────────────

GLOSSARY_SYSTEM = """\
You are a professional Russian translator specialising in political philosophy,
governance theory, and cryptocurrency/blockchain topics.

Extract a master terminology glossary from this book excerpt.
Output ONLY lines in this exact format, one per line, no preamble:
  English term → русский перевод

Include 50–70 entries covering: crypto/blockchain jargon, governance concepts,
philosophical terms, and recurring domain vocabulary.
Proper nouns and acronyms (DAO, DeFi, P2P) stay as-is unless a standard Russian
equivalent is universally accepted."""

TRANSLATE_SYSTEM = """\
You are a professional Russian translator specialising in political philosophy,
governance theory, and cryptocurrency/blockchain topics.

STYLE: Academic, precise (книжный стиль). Preserve the authors' analytical voice,
paragraph structure, and argumentative flow exactly.

GLOSSARY — use these translations consistently throughout:
{glossary}

RULES:
- Preserve every paragraph break
- Keep proper names and acronyms (DAO, DeFi, P2P, etc.) as in the original
- Do not add translator notes or explanations
- Output ONLY the Russian translation, nothing else
- Markdown headings (#, ##, ###) must be preserved exactly as given"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def log(msg: str, tag: str = ""):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"ok": "✓", "err": "✗", "info": "→", "warn": "⚠"}.get(tag, " ")
    print(f"[{ts}] {prefix}  {msg}")


def load_book(path: str) -> str:
    """Load book — works for the plain-text-inside-.pdf file."""
    raw = Path(path).read_bytes()
    # Try UTF-8, fall back to latin-1
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def split_into_chapters(text: str) -> list[dict]:
    """
    Split the book into logical chapters based on numbered headings.
    Returns list of {"num": int, "title": str, "content": str}
    """
    # Find all heading positions
    splits = []
    for m in CHAPTER_RE.finditer(text):
        splits.append(m.start())

    if len(splits) < 2:
        log("Could not detect chapters — treating whole book as one chapter.", "warn")
        return [{"num": 0, "title": "Full Book", "content": text}]

    chapters = []
    for i, start in enumerate(splits):
        end = splits[i + 1] if i + 1 < len(splits) else len(text)
        chunk = text[start:end].strip()
        # Extract heading from first line
        first_line = chunk.split("\n")[0].strip()
        chapters.append({
            "num": i + 1,
            "title": first_line[:80],
            "content": chunk,
        })
        log(f"  Chapter {i+1}: {first_line[:60]}")
    return chapters


def split_chapter_into_chunks(content: str, words_per_chunk: int) -> list[str]:
    """Split a long chapter into API-sized chunks, breaking on paragraphs."""
    paragraphs = re.split(r"\n\n+", content)
    chunks, current, count = [], [], 0
    for para in paragraphs:
        w = len(para.split())
        if count + w > words_per_chunk and current:
            chunks.append("\n\n".join(current))
            current, count = [para], w
        else:
            current.append(para)
            count += w
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def call_claude(client, system: str, user: str, retries: int = MAX_RETRIES) -> str:
    for attempt in range(retries):
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return msg.content[0].text.strip()
        except anthropic.RateLimitError:
            wait = RETRY_WAIT * (attempt + 1)
            log(f"Rate limited. Waiting {wait}s… (attempt {attempt+1}/{retries})", "warn")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503):
                wait = RETRY_WAIT * (attempt + 1)
                log(f"API overloaded ({e.status_code}). Waiting {wait}s…", "warn")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Failed after {retries} retries")


def build_glossary(client, chapters: list[dict]) -> str:
    log("Building terminology glossary…", "info")
    # Use first 5 chapters as representative sample
    sample = "\n\n".join(c["content"] for c in chapters[:5])[:14000]
    result = call_claude(client, GLOSSARY_SYSTEM, f"Book excerpt:\n\n{sample}")
    lines = [l for l in result.splitlines() if "→" in l]
    log(f"Glossary built: {len(lines)} terms.", "ok")
    return "\n".join(lines)


def translate_chapter(client, chapter: dict, glossary: str,
                       prev_tail: str = "") -> str:
    """Translate one chapter, chunking internally if needed."""
    chunks = split_chapter_into_chunks(chapter["content"], CHUNK_WORDS)
    translated_parts = []
    system = TRANSLATE_SYSTEM.format(glossary=glossary)

    for idx, chunk in enumerate(chunks):
        context = f"[Previous passage ended: …{prev_tail[-300:]}]\n\n" if prev_tail else ""
        user_msg = f"{context}Translate this passage:\n\n{chunk}"

        log(f"  Chunk {idx+1}/{len(chunks)} ({len(chunk.split())} words)…")
        result = call_claude(client, system, user_msg)
        translated_parts.append(result)
        prev_tail = result
        time.sleep(0.5)  # polite pause between calls

    return "\n\n".join(translated_parts)


def chapter_to_markdown(chapter: dict, ru_content: str, chapter_num: int) -> str:
    header = textwrap.dedent(f"""\
        <!--
          {BOOK_TITLE_RU} — {BOOK_SUBTITLE_RU}
          {AUTHORS}
          Переведено с помощью автоматизированного конвейера (Claude AI)
          Лицензия: CC BY-SA 4.0
        -->

    """)

    # Separate inline footnote definitions from body text and reattach
    # as a clean "Примечания" section at the very end of the chapter.
    # Inline [^N] markers in the body are preserved for the reader.
    fn_defs = re.findall(r'^\[\^(\w+)\]:\s*(.+)', ru_content, re.MULTILINE)
    if fn_defs:
        # Strip footnote definitions from body (they'll be in the section)
        body = re.sub(r'^\[\^\w+\]:.+$\n?', '', ru_content, flags=re.MULTILINE)
        body = body.rstrip()
        notes_section = "\n\n---\n\n**Примечания**\n\n"
        for key, text in fn_defs:
            notes_section += f"[^{key}]: {text}\n\n"
        return header + body + notes_section
    else:
        return header + ru_content


def chapter_filename(num: int, title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "_", slug).strip("_")[:50]
    return f"chapter_{num:02d}_{slug}.md"


def commit_chapter(repo_path: str, subdir: str, filename: str,
                   content: str, chapter_title: str, chapter_num: int):
    repo = git.Repo(repo_path)
    target_dir = Path(repo_path) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    filepath = target_dir / filename
    filepath.write_text(content, encoding="utf-8")

    # Stage and commit
    rel = str(filepath.relative_to(repo_path))
    repo.index.add([rel])
    commit_msg = (
        f"translation(ru): chapter {chapter_num} — {chapter_title[:60]}\n\n"
        f"Automated translation of '{BOOK_TITLE_EN}' to Russian.\n"
        f"Model: {MODEL} | {datetime.now().strftime('%Y-%m-%d')}"
    )
    repo.index.commit(commit_msg)
    log(f"Committed: {rel}", "ok")


def write_readme(repo_path: str, subdir: str, chapters: list[dict],
                 translated_files: list[str]):
    readme = textwrap.dedent(f"""\
        # {BOOK_TITLE_RU}
        ### {BOOK_SUBTITLE_RU}

        **{AUTHORS}**

        > Русский перевод книги *{BOOK_TITLE_EN}*
        > Jarrad Hope & Peter Ludlow (2025)
        > Лицензия: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

        Перевод выполнен автоматически с использованием Claude AI с последующей
        редакторской вычиткой терминологического глоссария.

        ---

        ## Содержание

    """)
    for i, fname in enumerate(translated_files):
        title = chapters[i]["title"] if i < len(chapters) else f"Глава {i+1}"
        readme += f"- [{title}]({fname})\n"

    readme += textwrap.dedent(f"""

        ---
        *Переведено: {datetime.now().strftime('%B %Y')}*
    """)

    target = Path(repo_path) / subdir / "README.md"
    target.write_text(readme, encoding="utf-8")

    repo = git.Repo(repo_path)
    rel = str(target.relative_to(repo_path))
    repo.index.add([rel])
    repo.index.commit(f"translation(ru): add README index\n\nFull translation of '{BOOK_TITLE_EN}' complete.")
    log("README committed.", "ok")


# ─── Progress persistence ─────────────────────────────────────────────────────

def load_progress(progress_file: str) -> dict:
    if Path(progress_file).exists():
        with open(progress_file) as f:
            return json.load(f)
    return {"glossary": None, "completed_chapters": [], "translated_files": []}


def save_progress(progress_file: str, state: dict):
    with open(progress_file, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Translate book to Russian and push to GitHub.")
    parser.add_argument("--input", required=True, help="Path to the book file")
    parser.add_argument("--repo-path", required=True, help="Path to local git repo")
    parser.add_argument("--repo-subdir", default="translations/ru",
                        help="Subfolder inside the repo (default: translations/ru)")
    parser.add_argument("--push", action="store_true",
                        help="git push after each commit (requires remote access)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        api_key = input("Enter your Anthropic API key: ").strip()
    client = anthropic.Anthropic(api_key=api_key)

    progress_file = Path(args.repo_path) / args.repo_subdir / ".translation_progress.json"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    state = load_progress(str(progress_file))

    # ── Load & parse book
    log(f"Loading book: {args.input}", "info")
    text = load_book(args.input)
    log(f"Loaded {len(text.split()):,} words.", "ok")

    log("Detecting chapters…", "info")
    chapters = split_into_chapters(text)
    log(f"Found {len(chapters)} chapters.", "ok")

    # ── Build glossary (once)
    if not state["glossary"]:
        state["glossary"] = build_glossary(client, chapters)
        save_progress(str(progress_file), state)
    else:
        log(f"Resuming — glossary already built ({len(state['glossary'].splitlines())} terms).", "ok")

    # ── Translate chapter by chapter
    repo = git.Repo(args.repo_path)

    for chapter in chapters:
        num = chapter["num"]
        if num in state["completed_chapters"]:
            log(f"Skipping chapter {num} (already translated).", "info")
            continue

        log(f"\n── Chapter {num}: {chapter['title'][:60]}", "info")

        # Previous chapter tail for continuity
        prev_tail = ""
        if state["translated_files"]:
            last_file = Path(args.repo_path) / args.repo_subdir / state["translated_files"][-1]
            if last_file.exists():
                prev_tail = last_file.read_text(encoding="utf-8")[-400:]

        try:
            ru_content = translate_chapter(client, chapter, state["glossary"], prev_tail)
        except Exception as e:
            log(f"Chapter {num} failed: {e}", "err")
            log("Saving progress and exiting. Re-run to resume.", "warn")
            save_progress(str(progress_file), state)
            sys.exit(1)

        # Save as markdown and commit
        fname = chapter_filename(num, chapter["title"])
        md_content = chapter_to_markdown(chapter, ru_content, num)
        commit_chapter(args.repo_path, args.repo_subdir, fname,
                       md_content, chapter["title"], num)

        if args.push:
            origin = repo.remote("origin")
            origin.push()
            log("Pushed to origin.", "ok")

        state["completed_chapters"].append(num)
        state["translated_files"].append(fname)
        save_progress(str(progress_file), state)

    # ── Final README
    log("\nWriting README index…", "info")
    write_readme(args.repo_path, args.repo_subdir, chapters, state["translated_files"])

    if args.push:
        repo.remote("origin").push()
        log("Final push done.", "ok")

    log(f"\nDone! {len(chapters)} chapters translated and committed.", "ok")
    log(f"Repo subfolder: {args.repo_subdir}", "ok")


if __name__ == "__main__":
    main()

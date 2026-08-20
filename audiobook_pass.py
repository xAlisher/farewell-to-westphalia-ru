#!/usr/bin/env python3
"""
Audiobook Normalization Pass — Russian Human Narrator
------------------------------------------------------
Runs AFTER translate_to_russian.py. Takes the translated .md chapter files
and produces clean narrator scripts with:

  1.  Stress marks (ударе́ния) on ambiguous / hard Russian words
  2.  Abbreviations expanded on first use  (DAO → «ДАО (дао)»)
  3.  Numbers written out in words         (2025 → две тысячи двадцать пятый)
  4.  Ordinals written out                 (1-й → первый)
  5.  Footnotes moved to end-of-chapter    [^1] → «(Примечание: …)»
  6.  Citations removed or flattened       (Smith, 2019) → spoken phrase
  7.  Section headings turned into spoken  ## Heading → «Раздел: Heading.»
  8.  Chapter transitions announced        «Глава три. Название.»
  9.  Parenthetical asides reformatted     (i.e. …) → «то есть …»
  10. Dashes/ellipses for natural pauses   — and … preserved; --- removed
  11. URLs / emails converted to spoken    https://… → «по адресу …»
  12. All Markdown stripped                **, __, ` removed
  13. Pronunciation guide appended         for foreign names / unusual words

Usage:
    python audiobook_pass.py \
        --input-dir /path/to/repo/translations/ru \
        --output-dir /path/to/audiobook_scripts \
        --push-repo /path/to/repo \
        --push-subdir audiobook/ru

Requires:
    pip install anthropic gitpython pymorphy3
"""

import os
import re
import sys
import json
import time
import argparse
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


# ─── Config ───────────────────────────────────────────────────────────────────

MODEL      = "claude-opus-4-5"
MAX_TOKENS = 4096
CHUNK_CHARS = 6000  # chars per API call for stress-marking

# Known tech abbreviations — first-use expansion
# Format: ABBREV: (expansion_ru, pronunciation_hint)
ABBREV_TABLE = {
    "DAO":    ("децентрализованная автономная организация", "дао"),
    "DAOs":   ("децентрализованные автономные организации", "дао"),
    "DeFi":   ("децентрализованные финансы", "де-фай"),
    "P2P":    ("одноранговая сеть", "пи-ту-пи"),
    "NFT":    ("невзаимозаменяемый токен", "эн-эф-ти"),
    "NFTs":   ("невзаимозаменяемые токены", "эн-эф-ти"),
    "PoW":    ("доказательство работы", "пи-о-дабл-ю"),
    "PoS":    ("доказательство доли владения", "пи-о-эс"),
    "API":    ("интерфейс прикладного программирования", "эй-пи-ай"),
    "TCP/IP": ("протокол управления передачей данных", "ти-си-пи / ай-пи"),
    "VPN":    ("виртуальная частная сеть", "ви-пи-эн"),
    "UI":     ("пользовательский интерфейс", "ю-ай"),
    "UX":     ("пользовательский опыт", "ю-экс"),
    "dApp":   ("децентрализованное приложение", "ди-эпп"),
    "dApps":  ("децентрализованные приложения", "ди-эппс"),
    "EVM":    ("виртуальная машина Ethereum", "и-ви-эм"),
    "IPFS":   ("межпланетная файловая система", "ай-пи-эф-эс"),
    "ZK":     ("доказательство с нулевым разглашением", "зет-кей"),
}

# Latin phrases that appear in philosophy texts → Russian equivalents
LATIN_TABLE = {
    "i.e.":    "то есть",
    "e.g.":    "например",
    "et al.":  "и другие",
    "viz.":    "а именно",
    "cf.":     "сравни",
    "ibid.":   "там же",
    "op. cit.":"цит. соч.",
    "inter alia": "в частности",
    "de facto": "де-факто",
    "de jure":  "де-юре",
    "per se":   "как таковой",
    "sine qua non": "непременное условие",
    "status quo": "статус-кво",
    "modus operandi": "образ действий",
    "ad hoc":   "специально для этого случая",
    "sui generis": "уникальный по своему роду",
}


# ─── Regex helpers ─────────────────────────────────────────────────────────────

# Markdown noise
RE_BOLD       = re.compile(r'\*\*(.+?)\*\*|__(.+?)__')
RE_ITALIC     = re.compile(r'\*(.+?)\*|_(.+?)_')
RE_CODE_BLOCK = re.compile(r'```[\s\S]*?```', re.MULTILINE)
RE_INLINE_CODE= re.compile(r'`([^`]+)`')
RE_COMMENT    = re.compile(r'<!--[\s\S]*?-->', re.MULTILINE)

# Structure
RE_H1         = re.compile(r'^#\s+(.+)', re.MULTILINE)
RE_H2         = re.compile(r'^##\s+(.+)', re.MULTILINE)
RE_H3         = re.compile(r'^###\s+(.+)', re.MULTILINE)
RE_FOOTNOTE_DEF  = re.compile(r'^\[\^(\w+)\]:\s*(.+)', re.MULTILINE)
RE_FOOTNOTE_REF  = re.compile(r'\[\^(\w+)\]')
RE_CITATION   = re.compile(r'\(([A-ZА-Яа-яёa-z][^()]{2,60},\s*\d{4}[a-z]?(?:,\s*pp?\.\s*\d+(?:–\d+)?)?)\)')
RE_URL        = re.compile(r'https?://[^\s)>\]"\']+')
RE_EMAIL      = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
RE_NUMBER     = re.compile(r'\b(\d{1,4})\b')        # 1–9999 → spell out
RE_YEAR       = re.compile(r'\b(1[5-9]\d\d|20\d\d)\b')   # years stay as digits
RE_TRIPLE_DASH= re.compile(r'---+')
RE_ORDINAL_RU = re.compile(r'\b(\d+)-[йяго]\b')     # 1-й, 2-го etc.

# Block lists (for removing them from final narration flow)
RE_BULLET     = re.compile(r'^[\*\-•]\s+', re.MULTILINE)


# ─── Russian number-to-words (simplified, good enough for 1–3999) ─────────────

_ONES = ['','один','два','три','четыре','пять','шесть','семь','восемь','девять',
         'десять','одиннадцать','двенадцать','тринадцать','четырнадцать','пятнадцать',
         'шестнадцать','семнадцать','восемнадцать','девятнадцать']
_TENS = ['','','двадцать','тридцать','сорок','пятьдесят','шестьдесят','семьдесят',
         'восемьдесят','девяносто']
_HUND = ['','сто','двести','триста','четыреста','пятьсот','шестьсот','семьсот',
         'восемьсот','девятьсот']
_THOU = ['тысяча','тысячи','тысяч']

def _thou_form(n):
    if 11 <= n % 100 <= 19: return _THOU[2]
    r = n % 10
    if r == 1: return _THOU[0]
    if 2 <= r <= 4: return _THOU[1]
    return _THOU[2]

def num_to_ru(n: int) -> str:
    if n == 0: return 'ноль'
    parts = []
    if n >= 1000:
        t = n // 1000
        # feminine forms for тысяча
        ones_f = ['','одна','две','три','четыре','пять','шесть','семь','восемь','девять']
        t_word = (ones_f[t] if t < 10 else _ONES[t]) + ' ' + _thou_form(t)
        parts.append(t_word.strip())
        n %= 1000
    if n >= 100:
        parts.append(_HUND[n // 100])
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10])
        n %= 10
    if n > 0:
        parts.append(_ONES[n])
    return ' '.join(p for p in parts if p)


# ─── Text transformation (regex layer, no API) ─────────────────────────────────

def strip_markdown(text: str) -> str:
    text = RE_COMMENT.sub('', text)
    text = RE_CODE_BLOCK.sub(' [фрагмент кода опущен] ', text)
    text = RE_INLINE_CODE.sub(r'\1', text)
    text = RE_BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    text = RE_ITALIC.sub(lambda m: m.group(1) or m.group(2), text)
    return text

def expand_latin(text: str) -> str:
    for lat, ru in LATIN_TABLE.items():
        text = re.sub(re.escape(lat), ru, text, flags=re.IGNORECASE)
    return text

def convert_urls(text: str) -> str:
    def _url(m):
        url = m.group(0)
        domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0]
        return f'по адресу {domain}'
    text = RE_URL.sub(_url, text)
    text = RE_EMAIL.sub(lambda m: f'электронная почта {m.group(0)}', text)
    return text

def convert_numbers(text: str) -> str:
    # Protect years first
    years = {}
    def save_year(m):
        key = f'__YEAR{len(years)}__'
        years[key] = m.group(0)
        return key
    text = RE_YEAR.sub(save_year, text)

    # Convert ordinals: 1-й → первый (simplified, covers most cases)
    ordinal_map = {'1':'первый','2':'второй','3':'третий','4':'четвёртый',
                   '5':'пятый','6':'шестой','7':'седьмой','8':'восьмой',
                   '9':'девятый','10':'десятый'}
    def _ord(m):
        return ordinal_map.get(m.group(1), num_to_ru(int(m.group(1))))
    text = RE_ORDINAL_RU.sub(_ord, text)

    # Convert plain numbers
    def _num(m):
        n = int(m.group(1))
        if n == 0: return 'ноль'
        return num_to_ru(n)
    text = RE_NUMBER.sub(_num, text)

    # Restore years
    for key, val in years.items():
        text = text.replace(key, val)
    return text

def handle_abbreviations(text: str, seen: set) -> str:
    for abbr, (expansion, hint) in ABBREV_TABLE.items():
        pattern = re.compile(r'\b' + re.escape(abbr) + r'\b')
        if pattern.search(text):
            if abbr not in seen:
                seen.add(abbr)
                text = pattern.sub(f'{abbr} ({expansion}; произносится: {hint})', text, count=1)
            # subsequent uses: just keep abbr as-is (narrator will know by now)
    return text

def extract_footnotes(text: str) -> tuple[str, list]:
    """Remove footnote refs from body, return (clean_text, footnotes_list)."""
    footnotes = {}
    for m in RE_FOOTNOTE_DEF.finditer(text):
        footnotes[m.group(1)] = m.group(2).strip()
    text = RE_FOOTNOTE_DEF.sub('', text)

    notes_out = []
    def _ref(m):
        key = m.group(1)
        if key in footnotes:
            notes_out.append(footnotes[key])
            return ''  # remove inline ref mark
        return ''
    text = RE_FOOTNOTE_REF.sub(_ref, text)
    return text, notes_out

def flatten_citations(text: str) -> str:
    """Remove parenthetical citations so narrator doesn't read them."""
    return RE_CITATION.sub('', text)

def convert_headings(text: str, chapter_num: int, chapter_title: str) -> str:
    """Turn markdown headings into natural spoken cues."""
    # H1 → chapter announcement (usually only one per file)
    text = RE_H1.sub(
        lambda m: f'\n\n[ГЛАВА {chapter_num}. {m.group(1).upper()}]\n\n',
        text
    )
    # H2 → section break with spoken label
    text = RE_H2.sub(
        lambda m: f'\n\n[РАЗДЕЛ: {m.group(1)}]\n\n',
        text
    )
    # H3 → subsection, lighter announcement
    text = RE_H3.sub(
        lambda m: f'\n\n[Подраздел: {m.group(1)}]\n\n',
        text
    )
    return text

def fix_punctuation(text: str) -> str:
    text = RE_TRIPLE_DASH.sub('—', text)
    # Ensure em-dashes have spaces
    text = re.sub(r'(?<!\s)—(?!\s)', ' — ', text)
    # Bullet points → "Первое: / Второе: " style would need context;
    # instead just convert to dashes for narrator
    text = RE_BULLET.sub('— ', text)
    return text

def append_footnotes_reading(text: str, notes: list) -> str:
    """Reading version: full footnotes printed at chapter end."""
    if not notes:
        return text
    section = '\n\n---\n\n**Примечания**\n\n'
    for i, note in enumerate(notes, 1):
        section += f'{i}. {note}\n\n'
    return text + section


def append_footnotes_audio(text: str, notes: list,
                            chapter_num: int = 1,
                            book_url: str = "") -> str:
    """Audio version: mention footnotes ONCE at end of chapter 1, drop silently elsewhere."""
    if not notes:
        return text

    # All chapters except the first — discard footnotes, say nothing
    if chapter_num != 1:
        return text

    # Chapter 1 only — single, quiet editorial note, never repeated
    download_hint = (
        f"по адресу {book_url}" if book_url else
        "в электронной версии книги"
    )
    announcement = (
        f"\n\n[ДИКТОР — спокойно, как редакционное замечание]\n"
        f"Книга содержит примечания и ссылки. "
        f"В аудиоверсии они не читаются — найдите их {download_hint}.\n"
    )
    return text + announcement


# ─── API layer: stress marks ──────────────────────────────────────────────────

STRESS_SYSTEM = """\
You are a Russian language expert preparing a narrator script for a professional studio audiobook recording.

Your task: add stress marks (ударения) to Russian words in the text where the stress placement is:
- Non-obvious or could be misread
- On a word with common alternates (замо́к vs за́мок, пи́ла vs пила́, etc.)
- On a long word (5+ syllables) where stress aids phrasing
- On domain terminology (философ — фило́соф, управление — управле́ние)

Use the acute accent ´ placed directly after the stressed vowel, like so:
  децентрализа́ция, суверените́т, управле́ние, блокче́йн

Rules:
- DO NOT mark stress on every single word — only where helpful
- DO NOT change any words, punctuation, formatting, or annotations in [BRACKETS]
- DO NOT add translator notes
- Output ONLY the text with stress marks added, nothing else"""


def add_stress_marks(client, text: str) -> str:
    """Call Claude to add stress marks. Processes in chunks."""
    chunks = []
    pos = 0
    while pos < len(text):
        end = min(pos + CHUNK_CHARS, len(text))
        # Try to break at paragraph boundary
        pb = text.rfind('\n\n', pos, end)
        if pb > pos + 1000:
            end = pb
        chunks.append(text[pos:end])
        pos = end

    marked_parts = []
    for i, chunk in enumerate(chunks):
        print(f"  Stress marks: chunk {i+1}/{len(chunks)}…")
        try:
            result = call_claude(client, STRESS_SYSTEM,
                                 f'Add stress marks to this text:\n\n{chunk}')
            marked_parts.append(result)
        except Exception as e:
            print(f"  Warning: stress pass failed for chunk {i+1}: {e}")
            marked_parts.append(chunk)  # keep original on failure
        time.sleep(0.5)

    return ''.join(marked_parts)


def call_claude(client, system: str, user: str, retries: int = 4) -> str:
    for attempt in range(retries):
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}]
            )
            return msg.content[0].text.strip()
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"  Rate limited — waiting {wait}s…")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503):
                wait = 30 * (attempt + 1)
                print(f"  API overloaded — waiting {wait}s…")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Claude API failed after {retries} retries")


# ─── Full pipeline per chapter ────────────────────────────────────────────────

def process_chapter(client, md_path: Path, chapter_num: int,
                    seen_abbrevs: set, book_url: str = "") -> str:
    text = md_path.read_text(encoding='utf-8')
    title = md_path.stem.replace('_', ' ')

    print(f"\n── Processing: {md_path.name}")

    # 1. Strip HTML comments / frontmatter
    text = strip_markdown(text)

    # 2. Extract footnotes before any further processing
    text, footnotes = extract_footnotes(text)
    if footnotes:
        print(f"  Footnotes extracted: {len(footnotes)} (will announce, not read)")

    # 3. Convert headings to spoken cues
    text = convert_headings(text, chapter_num, title)

    # 4. Flatten academic citations
    text = flatten_citations(text)

    # 5. Latin phrases → Russian
    text = expand_latin(text)

    # 6. URLs / emails → spoken
    text = convert_urls(text)

    # 7. Abbreviations — first-use expansion
    text = handle_abbreviations(text, seen_abbrevs)

    # 8. Numbers → words (skip years)
    text = convert_numbers(text)

    # 9. Punctuation cleanup
    text = fix_punctuation(text)

    # 10. Footnotes — audio: mention once in ch.1 intro, drop silently everywhere else
    text = append_footnotes_audio(text, footnotes, chapter_num, book_url)

    # 11. Stress marks (API call — most valuable step for human narrator)
    print("  Adding stress marks (API)…")
    text = add_stress_marks(client, text)

    # 12. Final cleanup: remove excess blank lines
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    return text


def build_narrator_header(chapter_num: int, title: str) -> str:
    return f"""╔══════════════════════════════════════════════════════════════╗
║  НАРРАТОРСКИЙ СЦЕНАРИЙ — ДЛЯ СТУДИЙНОЙ ЗАПИСИ              ║
║  Глава {chapter_num:02d}: {title[:48]:<48} ║
║  Книга: «Прощай, Вестфалия»                                 ║
║  Правила: [СКОБКИ] = режиссёрские ремарки, не читать вслух  ║
╚══════════════════════════════════════════════════════════════╝

"""


def build_pronunciation_appendix() -> str:
    lines = [
        "\n\n══════════════════════════════════════════════",
        "ПРИЛОЖЕНИЕ: ПРОИЗНОШЕНИЕ ИНОСТРАННЫХ СЛОВ",
        "══════════════════════════════════════════════\n",
    ]
    pronunciation_guide = {
        "Westphalia":   "Вестфа́лия",
        "Satoshi":      "Сато́си (японское имя, ударение на второй слог)",
        "Ethereum":     "Эфи́риум",
        "Bitcoin":      "Би́ткоин",
        "Vitalik":      "Вита́лик",
        "Buterin":      "Бу́терин",
        "Cypherpunk":   "Са́йферпанк",
        "Ludlow":       "Ла́длоу (английская фамилия)",
        "Jarrad Hope":  "Джа́ррад Хоуп",
        "Westphalian":  "вестфа́льский",
        "Byzantine":    "Византи́йский (в контексте: задача византийских генера́лов)",
        "Nakamoto":     "Накамо́то (японское имя)",
        "Assange":      "Асса́нж",
        "Finney":       "Фи́нни",
    }
    for word, guide in pronunciation_guide.items():
        lines.append(f"  {word:<20} → {guide}")
    return '\n'.join(lines)


# ─── Progress + GitHub ─────────────────────────────────────────────────────────

def load_progress(path: str) -> dict:
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return {"completed": [], "output_files": []}


def save_progress(path: str, state: dict):
    with open(path, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def commit_and_push(repo_path: str, subdir: str, filename: str,
                    content: str, chapter_num: int, do_push: bool):
    repo = git.Repo(repo_path)
    target = Path(repo_path) / subdir
    target.mkdir(parents=True, exist_ok=True)
    fpath = target / filename
    fpath.write_text(content, encoding='utf-8')

    rel = str(fpath.relative_to(repo_path))
    repo.index.add([rel])
    msg = (
        f"audiobook(ru): narrator script chapter {chapter_num:02d}\n\n"
        f"Stress marks, abbreviation expansion, footnote extraction,\n"
        f"number-to-words conversion — ready for studio recording.\n"
        f"Date: {datetime.now().strftime('%Y-%m-%d')}"
    )
    repo.index.commit(msg)
    print(f"  Committed: {rel}")

    if do_push:
        repo.remote('origin').push()
        print("  Pushed to origin.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Audiobook normalization pass — Russian human narrator")
    parser.add_argument('--input-dir', required=True,
                        help="Dir containing translated .md files")
    parser.add_argument('--output-dir', required=True,
                        help="Where to write narrator scripts")
    parser.add_argument('--book-url', default="",
                        help="URL where listeners can download the full book (for footnote announcements)")
    parser.add_argument('--push-repo', default=None,
                        help="Path to git repo (optional, for committing output)")
    parser.add_argument('--push-subdir', default='audiobook/ru',
                        help="Subfolder in repo for narrator scripts")
    parser.add_argument('--push', action='store_true',
                        help="git push after each commit")
    args = parser.parse_args()

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        api_key = input('Anthropic API key: ').strip()
    client = anthropic.Anthropic(api_key=api_key)

    input_dir  = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    progress_file = output_dir / '.audiobook_progress.json'
    state = load_progress(str(progress_file))

    # Collect chapter files in order
    chapter_files = sorted(
        input_dir.glob('chapter_*.md'),
        key=lambda p: int(re.search(r'chapter_(\d+)', p.stem).group(1))
    )
    if not chapter_files:
        sys.exit(f"No chapter_*.md files found in {input_dir}")

    print(f"Found {len(chapter_files)} chapters.")
    if args.book_url:
        print(f"Footnote announcements will point to: {args.book_url}")

    seen_abbrevs: set = set(state.get("seen_abbrevs", []))

    for md_path in chapter_files:
        m = re.search(r'chapter_(\d+)', md_path.stem)
        chapter_num = int(m.group(1)) if m else 0
        out_name = f"narrator_{md_path.stem}.md"

        if out_name in state["completed"]:
            print(f"Skipping chapter {chapter_num} (done).")
            continue

        try:
            narrator_text = process_chapter(client, md_path, chapter_num,
                                            seen_abbrevs, args.book_url)
        except Exception as e:
            print(f"ERROR on chapter {chapter_num}: {e}")
            save_progress(str(progress_file), state)
            sys.exit(1)

        # Add narrator header + pronunciation appendix on last chapter
        header = build_narrator_header(chapter_num, md_path.stem)
        full_script = header + narrator_text

        if chapter_num == len(chapter_files):
            full_script += build_pronunciation_appendix()

        # Write output
        out_path = output_dir / out_name
        out_path.write_text(full_script, encoding='utf-8')
        print(f"  Written: {out_path}")

        # Optionally commit
        if args.push_repo:
            commit_and_push(args.push_repo, args.push_subdir, out_name,
                            full_script, chapter_num, args.push)

        state["completed"].append(out_name)
        state["output_files"].append(str(out_path))
        state["seen_abbrevs"] = list(seen_abbrevs)
        save_progress(str(progress_file), state)

    print(f"\nDone. {len(state['completed'])} narrator scripts written to {output_dir}")
    print("Each file contains:")
    print("  — Stress marks on ambiguous words")
    print("  — Numbers as Russian words")
    print("  — Abbreviations expanded on first use")
    print("  — Footnotes at chapter end")
    print("  — [DIRECTOR NOTES] in brackets")
    print("  — Pronunciation appendix (last chapter)")


if __name__ == '__main__':
    main()

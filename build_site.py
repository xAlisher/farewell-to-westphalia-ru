#!/usr/bin/env python3
"""
Build static site for Прощай, Вестфалия (Russian translation).
Reads chapter markdown files and generates HTML pages in docs/.
"""

import os
import re
import json
import math
import glob
import subprocess
from datetime import datetime
from pathlib import Path
from html import escape

ROOT = Path(__file__).parent
TRANSLATIONS_DIR = ROOT / "translations" / "ru"
DOCS_DIR = ROOT / "docs"
CHAPTERS_DIR = DOCS_DIR / "chapters"
ASSETS_DIR = DOCS_DIR / "assets"

SITE_TITLE = "Прощай, Вестфалия"
SITE_SUBTITLE = "Криптосуверенитет и управление в постнациональную эпоху"
SITE_AUTHORS = "Джаррад Хоуп и Питер Лудлоу"
SITE_URL = "https://farewelltowestphalia.net"
ENGLISH_URL = "https://logos.co"

WORDS_PER_MINUTE = 200  # Average reading speed in Russian


def get_chapter_files():
    """Find all chapter markdown files, sorted by chapter number."""
    files = sorted(glob.glob(str(TRANSLATIONS_DIR / "chapter_*.md")))
    return files


def parse_chapter(filepath):
    """Parse a chapter markdown file into structured data."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove HTML comment header
    content = re.sub(r"^<!--.*?-->\s*", "", content, flags=re.DOTALL)

    # Extract title from first # heading
    title_match = re.match(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else "Без названия"

    # Remove the title line from body
    body = content[title_match.end():].strip() if title_match else content

    # Split body and footnotes
    footnotes_raw = []
    body_lines = []
    footnote_pattern = re.compile(r"^\[\^(\d+)\]:\s*(.+)$")

    in_footnotes = False
    current_footnote = None

    for line in body.split("\n"):
        fn_match = footnote_pattern.match(line)
        if fn_match:
            in_footnotes = True
            if current_footnote:
                footnotes_raw.append(current_footnote)
            current_footnote = {
                "num": int(fn_match.group(1)),
                "text": fn_match.group(2),
            }
        elif in_footnotes and current_footnote and line.startswith("  "):
            # Continuation of footnote
            current_footnote["text"] += " " + line.strip()
        elif in_footnotes and line.strip() == "":
            # Empty line in footnotes section, continue
            pass
        else:
            if current_footnote:
                footnotes_raw.append(current_footnote)
                current_footnote = None
            if not in_footnotes:
                body_lines.append(line)
            else:
                # Non-footnote line after footnotes started, might be more body
                fn2 = footnote_pattern.match(line)
                if fn2:
                    current_footnote = {
                        "num": int(fn2.group(1)),
                        "text": fn2.group(2),
                    }
                else:
                    body_lines.append(line)

    if current_footnote:
        footnotes_raw.append(current_footnote)

    body_text = "\n".join(body_lines).strip()

    # Extract ## headings for TOC
    headings = []
    for m in re.finditer(r"^##\s+(.+)$", body_text, re.MULTILINE):
        heading_text = m.group(1)
        heading_id = make_id(heading_text)
        headings.append({"text": heading_text, "id": heading_id})

    # Extract chapter number from title, fall back to filename number
    ch_num_match = re.match(r"Глава\s+(\d+)", title)
    if ch_num_match:
        chapter_num = int(ch_num_match.group(1))
    else:
        file_num_match = re.search(r"chapter_(\d+)", os.path.basename(filepath))
        chapter_num = int(file_num_match.group(1)) if file_num_match else 0

    # Calculate word count and reading time
    word_count = len(body_text.split())
    reading_time = max(1, math.ceil(word_count / WORDS_PER_MINUTE))

    # First paragraph for meta description
    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    first_para = paragraphs[0] if paragraphs else ""
    # Clean markdown from description
    meta_desc = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", first_para)
    meta_desc = re.sub(r"\[\^\d+\]", "", meta_desc)
    meta_desc = re.sub(r"[*_`]", "", meta_desc)
    meta_desc = meta_desc[:200].strip()

    return {
        "filepath": filepath,
        "title": title,
        "chapter_num": chapter_num,
        "body": body_text,
        "footnotes": footnotes_raw,
        "headings": headings,
        "word_count": word_count,
        "reading_time": reading_time,
        "meta_desc": meta_desc,
    }


def make_id(text):
    """Create an HTML id from heading text."""
    # Transliterate basic Cyrillic for IDs
    text = text.lower().strip()
    text = re.sub(r"[\d.]+\s*", "", text, count=1)  # Remove leading numbers like "2.1"
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    text = text.strip("-")
    return text or "section"


def md_to_html(text, footnotes=None):
    """Convert markdown text to HTML. Minimal parser for our needs."""
    footnote_nums = {fn["num"] for fn in footnotes} if footnotes else set()

    lines = text.split("\n")
    html_parts = []
    in_blockquote = False
    blockquote_lines = []
    in_list = False
    list_type = None
    list_lines = []

    def flush_blockquote():
        nonlocal in_blockquote, blockquote_lines
        if blockquote_lines:
            inner = process_paragraphs("\n".join(blockquote_lines))
            html_parts.append(f"<blockquote>{inner}</blockquote>")
            blockquote_lines = []
        in_blockquote = False

    def flush_list():
        nonlocal in_list, list_lines, list_type
        if list_lines:
            tag = "ol" if list_type == "ol" else "ul"
            items = "".join(f"<li>{inline_md(li)}</li>" for li in list_lines)
            html_parts.append(f"<{tag}>{items}</{tag}>")
            list_lines = []
        in_list = False
        list_type = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # Headings
        h3_match = re.match(r"^###\s+(.+)$", line)
        h2_match = re.match(r"^##\s+(.+)$", line)

        if h2_match:
            flush_blockquote()
            flush_list()
            heading = h2_match.group(1)
            hid = make_id(heading)
            html_parts.append(f'<h2 id="{hid}">{inline_md(heading)}</h2>')
            i += 1
            continue

        if h3_match:
            flush_blockquote()
            flush_list()
            heading = h3_match.group(1)
            hid = make_id(heading)
            html_parts.append(f'<h3 id="{hid}">{inline_md(heading)}</h3>')
            i += 1
            continue

        # Blockquote
        if line.startswith("> ") or line == ">":
            flush_list()
            in_blockquote = True
            blockquote_lines.append(line[2:] if line.startswith("> ") else "")
            i += 1
            continue

        if in_blockquote and line.strip() == "":
            # Could be continuation
            if i + 1 < len(lines) and lines[i + 1].startswith(">"):
                blockquote_lines.append("")
                i += 1
                continue
            else:
                flush_blockquote()
                i += 1
                continue

        if in_blockquote:
            flush_blockquote()

        # Unordered list
        ul_match = re.match(r"^[-*]\s+(.+)$", line)
        if ul_match:
            flush_blockquote()
            if in_list and list_type != "ul":
                flush_list()
            in_list = True
            list_type = "ul"
            list_lines.append(ul_match.group(1))
            i += 1
            continue

        # Ordered list
        ol_match = re.match(r"^\d+\.\s+(.+)$", line)
        if ol_match:
            flush_blockquote()
            if in_list and list_type != "ol":
                flush_list()
            in_list = True
            list_type = "ol"
            list_lines.append(ol_match.group(1))
            i += 1
            continue

        if in_list and line.strip() == "":
            flush_list()
            i += 1
            continue

        if in_list:
            flush_list()

        # Empty line
        if line.strip() == "":
            i += 1
            continue

        # Paragraph: collect consecutive non-empty lines
        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() != "" and not lines[i].startswith("#") and not lines[i].startswith(">") and not re.match(r"^[-*]\s+", lines[i]) and not re.match(r"^\d+\.\s+", lines[i]):
            para_lines.append(lines[i])
            i += 1

        para_text = " ".join(para_lines)
        html_parts.append(f"<p>{inline_md(para_text)}</p>")

    flush_blockquote()
    flush_list()

    return "\n".join(html_parts)


def process_paragraphs(text):
    """Convert text with blank-line-separated paragraphs to <p> tags."""
    paragraphs = text.split("\n\n")
    parts = []
    for p in paragraphs:
        p = p.strip()
        if p:
            parts.append(f"<p>{inline_md(p)}</p>")
    return "\n".join(parts) if parts else f"<p>{inline_md(text)}</p>"


def inline_md(text):
    """Convert inline markdown: bold, italic, links, footnote refs."""
    # Escape HTML first (but preserve our tags later)
    text = escape(text)

    # Bold + italic
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic with *
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)

    # Links [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    # Footnote references [^N]
    text = re.sub(
        r"\[\^(\d+)\]",
        r'<a href="#fn-\1" id="fnref-\1" class="footnote-ref" role="doc-noteref"><sup>\1</sup></a>',
        text,
    )

    return text


def render_footnotes(footnotes):
    """Render footnotes as HTML."""
    if not footnotes:
        return ""

    # Sort by number
    footnotes = sorted(footnotes, key=lambda x: x["num"])

    items = []
    for fn in footnotes:
        text = inline_md(fn["text"])
        backref = f' <a href="#fnref-{fn["num"]}" class="footnote-backref" role="doc-backlink">↩</a>'
        items.append(f'<li id="fn-{fn["num"]}">{text}{backref}</li>')

    return f"""<section class="footnotes" role="doc-endnotes">
<div class="footnotes-label">Примечания</div>
<ol>
{"".join(items)}
</ol>
</section>"""


def html_head(title, description, url="", extra=""):
    """Generate <head> content."""
    return f"""<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:type" content="book">
<meta property="og:locale" content="ru_RU">
<link rel="alternate" hreflang="en" href="{ENGLISH_URL}">
<link rel="canonical" href="{url}">
<link rel="preload" href="https://fonts.googleapis.com/css2?family=Literata:ital,wght@0,400;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500&display=swap" as="style">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Literata:ital,wght@0,400;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="{assets_path(url)}style.css">
{extra}
</head>"""


def assets_path(url):
    """Return relative path to assets based on page depth."""
    if "/chapters/" in url or url.endswith(("search.html", "about.html", "audiobook.html")):
        return "../assets/" if "/chapters/" in url else "assets/"
    return "assets/"


def site_header(depth=0):
    """Generate site header navigation."""
    prefix = "../" if depth > 0 else ""
    return f"""<header class="site-header">
<div class="wide-container">
<a href="{prefix}index.html" class="site-logo">↳ Прощай, Вестфалия</a>
<nav class="site-nav">
<a href="{prefix}index.html">Главная</a>
<a href="{prefix}search.html">Поиск</a>
<a href="{prefix}about.html">О книге</a>
<a href="{prefix}audiobook.html">Аудиокнига</a>
</nav>
</div>
</header>"""


def site_footer(depth=0):
    """Generate site footer."""
    return f"""<footer class="site-footer">
<div class="wide-container">
<div class="footer-content">
<span>CC BY-SA 4.0 · {SITE_AUTHORS}</span>
<div class="footer-links">
<a href="{ENGLISH_URL}">English original</a>
<a href="https://github.com/nickspaargaren/farewell-to-westphalia-ru">GitHub</a>
</div>
</div>
</div>
</footer>"""


def build_index(chapters):
    """Generate index.html landing page."""
    chapter_items = []
    for ch in chapters:
        num = f"{ch['chapter_num']:02d}"
        filename = f"chapter-{num}.html"
        # Strip "Глава N. " prefix for index listing since we show the number separately
        display_title = re.sub(r"^Глава\s+\d+\.\s*", "", ch["title"])
        chapter_items.append(
            f'<li><a href="chapters/{filename}">'
            f'<span class="chapter-num">{num}</span>'
            f'<span class="chapter-title">{escape(display_title)}</span>'
            f'<span class="chapter-arrow">→</span>'
            f"</a></li>"
        )

    book_schema = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Book",
            "name": SITE_TITLE,
            "alternateName": "Farewell to Westphalia",
            "author": [
                {"@type": "Person", "name": "Jarrad Hope"},
                {"@type": "Person", "name": "Peter Ludlow"},
            ],
            "inLanguage": "ru",
            "license": "https://creativecommons.org/licenses/by-sa/4.0/",
            "about": SITE_SUBTITLE,
        },
        ensure_ascii=False,
        indent=2,
    )

    description = f"{SITE_TITLE} — {SITE_SUBTITLE}. {SITE_AUTHORS}."

    html = f"""<!DOCTYPE html>
<html lang="ru">
{html_head(SITE_TITLE, description, SITE_URL + "/index.html",
    f'<script type="application/ld+json">{book_schema}</script>')}
<body>
{site_header()}
<main>
<section class="hero">
<div class="container">
<div class="hero-label">↳ Русский перевод</div>
<h1>{SITE_TITLE}</h1>
<p class="hero-subtitle">{SITE_SUBTITLE}</p>
<p class="hero-authors">{SITE_AUTHORS}</p>
<a href="chapters/chapter-01.html" class="hero-cta">
Читать книгу <span class="arrow">→</span>
</a>
</div>
</section>

<section class="chapter-list-section">
<div class="container">
<div class="section-label">↳ Содержание</div>
<ul class="chapter-list">
{"".join(chapter_items)}
</ul>
</div>
</section>

<section class="about-section">
<div class="container">
<div class="section-label">↳ О книге</div>
<p>«Прощай, Вестфалия» исследует, как технологии блокчейна и децентрализованное управление могут заменить устаревшие модели национальных государств, унаследованные от Вестфальского мира 1648 года.</p>
<p>Книга написана Джаррадом Хоупом и Питером Лудлоу и переведена на русский язык с помощью автоматизированного конвейера.</p>
<div class="license-badge">CC BY-SA 4.0 · Свободная лицензия</div>
</div>
</section>
</main>
{site_footer()}
</body>
</html>"""

    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def build_chapter(ch, chapters, idx):
    """Generate a chapter HTML page."""
    num = f"{ch['chapter_num']:02d}"
    total = len(chapters)
    filename = f"chapter-{num}.html"
    url = f"{SITE_URL}/chapters/{filename}"

    # Navigation
    prev_link = ""
    next_link = ""
    if idx > 0:
        prev_num = f"{chapters[idx - 1]['chapter_num']:02d}"
        prev_link = f'<a href="chapter-{prev_num}.html" class="prev">← Предыдущая</a>'
    if idx < total - 1:
        next_num = f"{chapters[idx + 1]['chapter_num']:02d}"
        next_link = f'<a href="chapter-{next_num}.html" class="next">Следующая →</a>'

    nav_html = f'<nav class="chapter-nav">{prev_link}{next_link}</nav>'

    # TOC sidebar
    toc_items = []
    for h in ch["headings"]:
        toc_items.append(f'<li><a href="#{h["id"]}">{escape(h["text"])}</a></li>')
    toc_html = ""
    if toc_items:
        toc_html = f"""<aside class="toc-sidebar">
<div class="toc-label">Содержание</div>
<ul>
{"".join(toc_items)}
</ul>
</aside>"""

    # Body HTML
    body_html = md_to_html(ch["body"], ch["footnotes"])
    footnotes_html = render_footnotes(ch["footnotes"])

    # Chapter schema
    chapter_schema = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Chapter",
            "name": ch["title"],
            "isPartOf": {"@type": "Book", "name": SITE_TITLE},
            "position": ch["chapter_num"],
            "inLanguage": "ru",
            "wordCount": ch["word_count"],
        },
        ensure_ascii=False,
    )

    page_title = f'{ch["title"]} — {SITE_TITLE}'
    description = ch["meta_desc"]

    html = f"""<!DOCTYPE html>
<html lang="ru">
{html_head(page_title, description, url,
    f'<script type="application/ld+json">{chapter_schema}</script>')}
<body>
{site_header(depth=1)}
<main>
<div class="chapter-layout">
<div class="chapter-main container">
<div class="chapter-header">
<div class="chapter-meta">
<span>Глава {ch["chapter_num"]} из {total}</span>
<span>{ch["reading_time"]} мин. чтения</span>
</div>
<h1>{escape(ch["title"])}</h1>
<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
<button class="share-btn">Поделиться ↗</button>
<a href="{ENGLISH_URL}" class="english-link">Читать по-английски →</a>
</div>
</div>
{nav_html}
<div class="chapter-content">
{body_html}
</div>
{footnotes_html}
{nav_html}
</div>
{toc_html}
</div>
</main>

<a href="#" class="back-to-top" aria-label="Наверх">↑</a>
{site_footer(depth=1)}
<script src="../assets/main.js"></script>
</body>
</html>"""

    (CHAPTERS_DIR / filename).write_text(html, encoding="utf-8")


def build_search(chapters):
    """Generate search.html and search-index.json."""
    # Build search index
    index = []
    for ch in chapters:
        num = f"{ch['chapter_num']:02d}"
        sections = []
        # Split body into sections by ## headings
        parts = re.split(r"(?=^## )", ch["body"], flags=re.MULTILINE)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            heading_match = re.match(r"^##\s+(.+)$", part, re.MULTILINE)
            heading = heading_match.group(1) if heading_match else ch["title"]
            # Clean text for indexing
            text = re.sub(r"\[\^\d+\]", "", part)
            text = re.sub(r"^##?\s+.+$", "", text, flags=re.MULTILINE)
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            text = re.sub(r"[*_`>]", "", text)
            text = " ".join(text.split())
            if text:
                sections.append({"heading": heading, "text": text})

        index.append({
            "chapter": f"Глава {ch['chapter_num']}",
            "title": ch["title"],
            "url": f"chapters/chapter-{num}.html",
            "sections": sections,
        })

    (ASSETS_DIR / "search-index.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8"
    )

    description = f"Поиск по книге «{SITE_TITLE}»"
    html = f"""<!DOCTYPE html>
<html lang="ru">
{html_head(f"Поиск — {SITE_TITLE}", description, SITE_URL + "/search.html")}
<body>
{site_header()}
<main class="search-page">
<div class="container">
<div class="section-label">↳ Поиск</div>
<div class="search-input-wrap">
<input type="search" id="search-input" class="search-input"
  placeholder="Введите запрос…" autocomplete="off" autofocus>
<div class="search-hint">↑↓ навигация · Enter — перейти</div>
</div>
<ul id="search-results" class="search-results"></ul>
</div>
</main>
{site_footer()}
<script src="assets/main.js"></script>
</body>
</html>"""

    (DOCS_DIR / "search.html").write_text(html, encoding="utf-8")


def build_about():
    """Generate about.html."""
    description = f"О книге «{SITE_TITLE}» — авторы, перевод, лицензия"
    html = f"""<!DOCTYPE html>
<html lang="ru">
{html_head(f"О книге — {SITE_TITLE}", description, SITE_URL + "/about.html")}
<body>
{site_header()}
<main class="page-content">
<div class="container">
<h1>О книге</h1>

<h2>«Прощай, Вестфалия»</h2>
<p>«Прощай, Вестфалия: криптосуверенитет и управление в постнациональную эпоху» — книга, исследующая потенциал технологий блокчейна как инструмента нового, децентрализованного управления человеческим обществом. Авторы анализируют, почему национальные государства, возникшие после Вестфальского мира 1648 года, являются устаревшими технологиями управления и какие альтернативы предлагают современные распределённые системы.</p>

<h2>Авторы</h2>
<p><strong>Джаррад Хоуп</strong> — сооснователь Status Network, разработчик и исследователь децентрализованных технологий. Активный участник экосистемы Ethereum и сторонник криптосуверенитета.</p>
<p><strong>Питер Лудлоу</strong> — философ, специализирующийся на вопросах кибер-права, онлайн-управления и виртуальных сообществ. Автор множества работ о пересечении технологий и политической философии.</p>

<h2>О переводе</h2>
<p>Русский перевод выполнен с помощью автоматизированного конвейера на основе Claude AI с последующей человеческой вычиткой. Процесс включает несколько этапов: автоматический перевод, контекстно-зависимую ротацию синонимов для устранения повторов и подготовку аудиоверсии.</p>
<p>Исходный код конвейера перевода и все материалы доступны в <a href="https://github.com/nickspaargaren/farewell-to-westphalia-ru">репозитории на GitHub</a>.</p>

<h2>Лицензия</h2>
<p>Книга распространяется по лицензии <a href="https://creativecommons.org/licenses/by-sa/4.0/">Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)</a>. Вы можете свободно копировать, распространять и адаптировать материал при условии указания авторства и сохранения той же лицензии.</p>

<h2>Оригинал</h2>
<p>Оригинальное англоязычное издание доступно на сайте <a href="{ENGLISH_URL}">logos.co</a>.</p>
</div>
</main>
{site_footer()}
</body>
</html>"""

    (DOCS_DIR / "about.html").write_text(html, encoding="utf-8")


def build_audiobook(chapters):
    """Generate audiobook.html placeholder."""
    items = []
    for ch in chapters:
        num = f"{ch['chapter_num']:02d}"
        items.append(
            f'<li class="audiobook-item">'
            f'<span class="audiobook-num">{num}</span>'
            f'<span class="audiobook-title">{escape(ch["title"])}</span>'
            f'<span class="badge-soon">скоро</span>'
            f"</li>"
        )

    description = f"Аудиокнига «{SITE_TITLE}» — скоро"
    html = f"""<!DOCTYPE html>
<html lang="ru">
{html_head(f"Аудиокнига — {SITE_TITLE}", description, SITE_URL + "/audiobook.html")}
<body>
{site_header()}
<main class="page-content">
<div class="container">
<h1>Аудиокнига</h1>
<p>Аудиоверсия книги «Прощай, Вестфалия» на русском языке находится в разработке. Каждая глава будет доступна для прослушивания прямо на этой странице.</p>

<div class="section-label" style="margin-top:48px">↳ Главы</div>
<ul class="audiobook-list">
{"".join(items)}
</ul>
</div>
</main>
{site_footer()}
</body>
</html>"""

    (DOCS_DIR / "audiobook.html").write_text(html, encoding="utf-8")


def build_sitemap(chapters):
    """Generate sitemap.xml."""
    def get_lastmod(filepath):
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%aI", "--", filepath],
                capture_output=True, text=True, cwd=ROOT
            )
            if result.stdout.strip():
                return result.stdout.strip()[:10]
        except Exception:
            pass
        return datetime.now().strftime("%Y-%m-%d")

    urls = [
        f"<url><loc>{SITE_URL}/index.html</loc><lastmod>{datetime.now().strftime('%Y-%m-%d')}</lastmod><priority>1.0</priority></url>"
    ]

    for ch in chapters:
        num = f"{ch['chapter_num']:02d}"
        lastmod = get_lastmod(ch["filepath"])
        urls.append(
            f'<url><loc>{SITE_URL}/chapters/chapter-{num}.html</loc>'
            f"<lastmod>{lastmod}</lastmod><priority>0.8</priority></url>"
        )

    for page in ["search.html", "about.html", "audiobook.html"]:
        urls.append(
            f'<url><loc>{SITE_URL}/{page}</loc>'
            f'<lastmod>{datetime.now().strftime("%Y-%m-%d")}</lastmod><priority>0.5</priority></url>'
        )

    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{"".join(urls)}
</urlset>"""

    (DOCS_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")


def build_robots():
    """Generate robots.txt."""
    robots = f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""
    (DOCS_DIR / "robots.txt").write_text(robots, encoding="utf-8")


def main():
    # Ensure directories
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Parse chapters
    chapter_files = get_chapter_files()
    if not chapter_files:
        print("No chapter files found in", TRANSLATIONS_DIR)
        return

    chapters = [parse_chapter(f) for f in chapter_files]
    chapters.sort(key=lambda c: c["chapter_num"])

    print(f"Found {len(chapters)} chapters")

    # Build all pages
    build_index(chapters)
    print("  ✓ index.html")

    for i, ch in enumerate(chapters):
        build_chapter(ch, chapters, i)
        num = f"{ch['chapter_num']:02d}"
        print(f"  ✓ chapters/chapter-{num}.html")

    build_search(chapters)
    print("  ✓ search.html + search-index.json")

    build_about()
    print("  ✓ about.html")

    build_audiobook(chapters)
    print("  ✓ audiobook.html")

    build_sitemap(chapters)
    print("  ✓ sitemap.xml")

    build_robots()
    print("  ✓ robots.txt")

    print("Done!")


if __name__ == "__main__":
    main()

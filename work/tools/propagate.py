#!/usr/bin/env python3
"""Propagate ru-parts edits downstream: assemble -> sync translations/ru -> rebuild site.

Usage: python3 propagate.py <chapter_id> [...]        (or: --all)
Single source of truth is work/ru-parts/ (see PROJECT_KNOWLEDGE.md). This script makes
every downstream copy (work/ru-draft, translations/ru, docs/) a derivation of it.
"""
import subprocess
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]
ROOT = WORK.parent

HEADER = """<!--
  Прощай, Вестфалия — Криптосуверенитет и управление в постнациональную эпоху
  Джаррад Хоуп и Питер Лудлоу
  Переведено с помощью автоматизированного конвейера (Claude AI)
  Лицензия: CC BY-SA 4.0
-->

"""


def main(chapters):
    if chapters == ["--all"]:
        chapters = sorted(p.stem for p in (WORK / "chunks").glob("chapter_*.json"))
    subprocess.run([sys.executable, WORK / "tools" / "assemble.py", *chapters], check=True)
    for ch in chapters:
        draft = (WORK / "ru-draft" / f"{ch}.md").read_text()
        (ROOT / "translations" / "ru" / f"{ch}.md").write_text(HEADER + draft)
        print(f"synced translations/ru/{ch}.md")
    subprocess.run([sys.executable, ROOT / "build_site.py"],
                   check=True, stdout=subprocess.DEVNULL)
    print("site rebuilt (docs/)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])

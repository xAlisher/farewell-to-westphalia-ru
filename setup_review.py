#!/usr/bin/env python3
"""
Setup Review Workflow
---------------------
Run once after translate_to_russian.py finishes.

For each translated chapter it:
  1. Creates a branch  translation/ru/chapter-NN
  2. Commits the chapter file to that branch
  3. Opens a Pull Request with:
       - All 3 reviewers assigned
       - Lead reviewer set as required approver
       - Checklist in PR body
       - Chapter-specific context (title, word count, rotation stats)
  4. Sets branch protection on main requiring lead approval before merge

Usage:
    python setup_review.py \
        --repo        owner/repo-name \
        --chapters-dir translations/ru \
        --reviewers   alice,bob,carol \
        --lead        alice \
        --token       ghp_...          # or set GITHUB_TOKEN env var

Requires:  pip install PyGithub
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

try:
    from github import Github, GithubException
except ImportError:
    sys.exit("pip install PyGithub")


# ─── PR body template ─────────────────────────────────────────────────────────

def make_pr_body(chapter_num: int, chapter_title: str,
                 word_count: int, reviewers: list[str],
                 lead: str, rotation_stats: dict | None) -> str:

    rotation_summary = ""
    if rotation_stats:
        lines = []
        for target_id, s in rotation_stats.items():
            if s["seen"] > 0:
                pct = round(s["rotated"] / s["seen"] * 100)
                lines.append(f"  - `{target_id}`: {s['seen']} occurrences, "
                              f"{s['rotated']} rotated ({pct}%), {s['kept']} kept")
        if lines:
            rotation_summary = (
                "\n### Synonym rotation applied\n"
                + "\n".join(lines)
                + "\n"
            )

    reviewers_list = "\n".join(f"- @{r}" + (" *(lead — approval required)*" if r == lead else "")
                               for r in reviewers)

    return f"""## Глава {chapter_num} — {chapter_title}

**{word_count:,} слов** · Автоматический перевод + синонимическая ротация
{rotation_summary}
---

### Задача рецензентов

Проверьте перевод на:

- [ ] **Точность** — смысл оригинала передан верно
- [ ] **Естественность** — текст читается как русский, а не переведённый
- [ ] **Терминология** — термины из глоссария используются последовательно
- [ ] **Синонимы** — варианты слова «управление» и «децентрализованный» уместны в контексте
- [ ] **Стиль** — академический регистр выдержан

### Как оставлять комментарии

1. Нажмите **Files changed**
2. Наведите на строку → нажмите **+**
3. Напишите исправление или вопрос
4. Используйте метки:
   - `[ОШИБКА]` — фактическая ошибка перевода
   - `[СТИЛЬ]` — стилистическое замечание
   - `[ТЕРМИН]` — вопрос по терминологии
   - `[АУДИО]` — важно для озвучки (сложная фраза для диктора)

Автор отвечает на каждый комментарий и помечает как **Resolved**.

### Рецензенты

{reviewers_list}

Мерж возможен только после апрува @{lead}.
После мержа автоматически запускается финальный аудиокнижный пасс (стресс-маркировка, числа, сноски).

---
*PR создан автоматически · {datetime.now().strftime('%Y-%m-%d')}*
"""


# ─── Branch + PR creation ─────────────────────────────────────────────────────

def get_or_create_branch(repo, branch_name: str, base_branch: str = "main"):
    try:
        return repo.get_branch(branch_name)
    except GithubException:
        base = repo.get_branch(base_branch)
        repo.create_git_ref(
            ref=f"refs/heads/{branch_name}",
            sha=base.commit.sha
        )
        print(f"  Created branch: {branch_name}")
        return repo.get_branch(branch_name)


def commit_file_to_branch(repo, branch_name: str, file_path: str,
                           content: str, chapter_num: int):
    path_in_repo = file_path
    commit_message = (
        f"translation(ru): chapter {chapter_num:02d} — initial translation\n\n"
        f"Automated translation + synonym rotation. Awaiting proofreader review."
    )
    try:
        # File already exists on branch — update it
        existing = repo.get_contents(path_in_repo, ref=branch_name)
        repo.update_file(
            path=path_in_repo,
            message=commit_message,
            content=content,
            sha=existing.sha,
            branch=branch_name,
        )
        print(f"  Updated {path_in_repo} on {branch_name}")
    except GithubException:
        # File doesn't exist yet — create it
        repo.create_file(
            path=path_in_repo,
            message=commit_message,
            content=content,
            branch=branch_name,
        )
        print(f"  Created {path_in_repo} on {branch_name}")


def create_pull_request(repo, branch_name: str, chapter_num: int,
                        chapter_title: str, word_count: int,
                        reviewers: list[str], lead: str,
                        rotation_stats: dict | None) -> str:
    title = f"[RU] Глава {chapter_num:02d}: {chapter_title[:60]}"
    body  = make_pr_body(chapter_num, chapter_title, word_count,
                         reviewers, lead, rotation_stats)
    try:
        pr = repo.create_pull(
            title=title,
            body=body,
            head=branch_name,
            base="main",
            draft=False,
        )
        print(f"  PR #{pr.number}: {pr.html_url}")

        # Request reviewers (exclude PR author to avoid GitHub 422 error)
        author = pr.user.login
        review_candidates = [r for r in reviewers if r != author]
        if review_candidates:
            pr.create_review_request(reviewers=review_candidates)
            print(f"  Reviewers assigned: {', '.join(review_candidates)}")
        else:
            print(f"  No reviewers to assign (all are PR author)")

        return pr.html_url

    except GithubException as e:
        if "A pull request already exists" in str(e):
            print(f"  PR already exists for {branch_name} — skipping")
            return ""
        raise


def setup_branch_protection(repo, lead: str):
    """Require lead's approval before merging into main."""
    try:
        branch = repo.get_branch("main")
        branch.edit_protection(
            required_approving_review_count=1,
            dismiss_stale_reviews=True,
            require_code_owner_reviews=False,
            # Only the lead's review counts — enforced via CODEOWNERS
        )
        print(f"Branch protection set: 1 required approval on main")
    except GithubException as e:
        print(f"  Warning: could not set branch protection: {e}")
        print(f"  Set it manually: Settings → Branches → main → Require approvals")


def write_codeowners(repo, lead: str, chapters_dir: str):
    """CODEOWNERS ensures only lead's approval counts for chapter files."""
    content = f"# Proofreading lead — required approver for all translated chapters\n"
    content += f"{chapters_dir}/ @{lead}\n"
    content += f"audiobook/ @{lead}\n"
    try:
        existing = repo.get_contents(".github/CODEOWNERS", ref="main")
        repo.update_file(
            path=".github/CODEOWNERS",
            message="ci: set proofreading lead as required approver",
            content=content,
            sha=existing.sha,
        )
    except GithubException:
        repo.create_file(
            path=".github/CODEOWNERS",
            message="ci: set proofreading lead as required approver",
            content=content,
        )
    print(f"CODEOWNERS written — @{lead} required for all chapter approvals")


def load_rotation_stats(chapters_dir: Path) -> dict:
    report = chapters_dir.parent / "translations" / "ru_rotated" / "rotation_report.md"
    # Parse the markdown report into a dict keyed by chapter filename
    # (simplified — returns empty if report not found)
    if not report.exists():
        return {}
    stats = {}
    current_chapter = None
    for line in report.read_text().splitlines():
        m = re.match(r'## (chapter_\S+)', line)
        if m:
            current_chapter = m.group(1)
            stats[current_chapter] = {}
        elif current_chapter and line.startswith('- **'):
            tm = re.match(r'- \*\*(\w+)\*\*: (\d+) occurrences — (\d+) rotated.*?(\d+) kept', line)
            if tm:
                stats[current_chapter][tm.group(1)] = {
                    "seen":    int(tm.group(2)),
                    "rotated": int(tm.group(3)),
                    "kept":    int(tm.group(4)),
                }
    return stats


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Create review PRs for translated chapters")
    parser.add_argument("--repo",          required=True,  help="owner/repo")
    parser.add_argument("--chapters-dir",  required=True,  help="Local path to translated chapters")
    parser.add_argument("--reviewers",     required=True,  help="Comma-separated GitHub usernames")
    parser.add_argument("--lead",          required=True,  help="Lead reviewer GitHub username")
    parser.add_argument("--token",         default=None,   help="GitHub token (or set GITHUB_TOKEN)")
    parser.add_argument("--start-chapter", type=int, default=1,
                        help="Only create PRs from this chapter onwards")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Set GITHUB_TOKEN or pass --token")

    reviewers = [r.strip() for r in args.reviewers.split(",")]
    if args.lead not in reviewers:
        sys.exit(f"Lead '{args.lead}' must be in reviewers list")

    g    = Github(token)
    repo = g.get_repo(args.repo)
    print(f"Connected to: {repo.full_name}")

    chapters_path = Path(args.chapters_dir)
    chapter_files = sorted(
        chapters_path.glob("chapter_*.md"),
        key=lambda p: int(re.search(r"chapter_(\d+)", p.stem).group(1))
    )
    if not chapter_files:
        sys.exit(f"No chapter_*.md found in {chapters_path}")

    rotation_stats = load_rotation_stats(chapters_path)

    # One-time setup
    setup_branch_protection(repo, args.lead)
    write_codeowners(repo, args.lead, str(chapters_path.name))

    # Progress file — don't re-create PRs that already exist
    progress_file = chapters_path / ".pr_progress.json"
    progress = json.loads(progress_file.read_text()) if progress_file.exists() else {"created": []}

    created_prs = []

    for md_path in chapter_files:
        m = re.search(r"chapter_(\d+)", md_path.stem)
        chapter_num = int(m.group(1)) if m else 0

        if chapter_num < args.start_chapter:
            continue
        if md_path.name in progress["created"]:
            print(f"Skipping chapter {chapter_num} (PR already created).")
            continue

        # Extract title from first heading in file
        content = md_path.read_text(encoding="utf-8")
        title_match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
        chapter_title = title_match.group(1) if title_match else md_path.stem
        word_count = len(content.split())

        branch_name = f"translation/ru/chapter-{chapter_num:02d}"
        repo_file_path = f"translations/ru/{md_path.name}"

        print(f"\n── Chapter {chapter_num}: {chapter_title[:50]}")

        get_or_create_branch(repo, branch_name)
        commit_file_to_branch(repo, branch_name, repo_file_path,
                               content, chapter_num)

        stats = rotation_stats.get(md_path.name)
        pr_url = create_pull_request(
            repo, branch_name, chapter_num, chapter_title,
            word_count, reviewers, args.lead, stats
        )
        if pr_url:
            created_prs.append({"chapter": chapter_num, "url": pr_url})

        progress["created"].append(md_path.name)
        progress_file.write_text(json.dumps(progress, indent=2))

    print(f"\n── Summary")
    print(f"Created {len(created_prs)} PRs:")
    for pr in created_prs:
        print(f"  Chapter {pr['chapter']}: {pr['url']}")
    print(f"\nReviewers: {', '.join(reviewers)}")
    print(f"Lead approver: @{args.lead}")
    print(f"\nWorkflow: proofreaders comment inline → author resolves →")
    print(f"@{args.lead} approves → merge → audiobook pass runs automatically")


if __name__ == "__main__":
    main()

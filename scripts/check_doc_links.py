#!/usr/bin/env python3
"""Fail if relative Markdown links in docs entrypoints point nowhere.

Pinned behavior is covered by scripts/test_check_doc_links.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_FILE_NAMES = (
    "README.md",
    "AGENTS.md",
    "client/README.md",
)

LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def markdown_files(root: Path) -> list[Path]:
    files = [p for name in ROOT_FILE_NAMES if (p := root / name).is_file()]
    docs = root / "docs"
    if docs.is_dir():
        files.extend(sorted(docs.rglob("*.md")))
    return files


def link_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw in LINK_RE.findall(text):
        target = raw.strip().split()[0].strip("<>")
        if not target or target.startswith(("#", "mailto:", "http://", "https://")):
            continue
        targets.append(target.split("#", 1)[0])
    return [t for t in targets if t]


def find_broken_links(root: Path) -> tuple[list[str], int, int]:
    """Return (errors, link_count, file_count)."""
    root = root.resolve()
    errors: list[str] = []
    checked = 0
    files = markdown_files(root)
    for path in files:
        text = path.read_text(encoding="utf-8")
        for target in link_targets(text):
            checked += 1
            dest = (path.parent / target).resolve()
            try:
                dest.relative_to(root)
            except ValueError:
                errors.append(f"{path.relative_to(root)}: escapes repo → {target}")
                continue
            if not dest.exists():
                errors.append(f"{path.relative_to(root)}: missing {target}")
    return errors, checked, len(files)


def main(root: Path | None = None) -> int:
    errors, checked, file_count = find_broken_links(root or ROOT)
    if errors:
        print("Broken relative Markdown links:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    print(f"ok: {checked} relative links in {file_count} markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

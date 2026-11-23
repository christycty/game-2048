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
    "observability/README.md",
    "site/assets/README.md",
)

LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
_FENCE_OPEN_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(`+)(?!`)((?:(?!\n\s*\n).)+?)(?<!`)\1(?!`)", re.DOTALL)


def _blank_preserving_newlines(segment: str) -> str:
    return re.sub(r"[^\r\n]", " ", segment)


def mask_code(text: str) -> str:
    """Replace fenced code blocks and inline code spans with spaces, keeping line numbers."""
    out_lines: list[str] = []
    fence_char = ""
    fence_len = 0
    for line in text.splitlines(keepends=True):
        if not fence_char:
            match = _FENCE_OPEN_RE.match(line)
            if match:
                marker = match.group(1)
                rest = line[match.end() :]
                # CommonMark: a backtick fence info string cannot contain backticks.
                if marker[0] == "~" or "`" not in rest:
                    fence_char = marker[0]
                    fence_len = len(marker)
                    out_lines.append(_blank_preserving_newlines(line))
                    continue
            out_lines.append(line)
        else:
            stripped = line.lstrip(" \t")
            close_re = re.compile(rf"^{re.escape(fence_char)}{{{fence_len},}}[ \t]*\r?\n?$")
            out_lines.append(_blank_preserving_newlines(line))
            if close_re.match(stripped):
                fence_char = ""
                fence_len = 0
    masked = "".join(out_lines)
    return INLINE_CODE_RE.sub(lambda m: _blank_preserving_newlines(m.group(0)), masked)


def markdown_files(root: Path) -> list[Path]:
    files = [p for name in ROOT_FILE_NAMES if (p := root / name).is_file()]
    docs = root / "docs"
    if docs.is_dir():
        files.extend(sorted(docs.rglob("*.md")))
    return files


def iter_link_targets(text: str) -> list[tuple[int, str]]:
    masked = mask_code(text)
    targets: list[tuple[int, str]] = []
    for lineno, line in enumerate(masked.splitlines(), start=1):
        for raw in LINK_RE.findall(line):
            target = raw.strip().split()[0].strip("<>")
            if not target or target.startswith(("#", "mailto:", "http://", "https://")):
                continue
            clean = target.split("#", 1)[0]
            if clean:
                targets.append((lineno, clean))
    return targets


def link_targets(text: str) -> list[str]:
    return [target for _, target in iter_link_targets(text)]


def find_broken_links(root: Path) -> tuple[list[str], int, int]:
    """Return (errors, link_count, file_count)."""
    root = root.resolve()
    errors: list[str] = []
    checked = 0
    files = markdown_files(root)
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, target in iter_link_targets(text):
            checked += 1
            dest = (path.parent / target).resolve()
            try:
                dest.relative_to(root)
            except ValueError:
                errors.append(f"{path.relative_to(root)}:{lineno}: escapes repo → {target}")
                continue
            if not dest.exists():
                errors.append(f"{path.relative_to(root)}:{lineno}: missing {target}")
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

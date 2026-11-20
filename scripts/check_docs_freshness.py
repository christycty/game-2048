#!/usr/bin/env python3
"""Warn when code/runtime files change without docs/agents (or AGENTS.md).

Exits 0 always so this stays a nudge, not a hard gate. Emits GitHub
Actions ::warning:: annotations when a nudge is warranted.

Pinned behavior is covered by scripts/test_check_docs_freshness.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CODE_PREFIXES = (
    "client/",
    "server/",
    "docker-compose.yml",
    ".env.example",
    ".github/workflows/",
)

DOC_PREFIXES = (
    "docs/agents/",
    "AGENTS.md",
)


def matches(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p) for p in prefixes)


def evaluate_freshness(files: list[str]) -> tuple[str, str]:
    """Return (kind, message).

    kind is one of: empty, no_code, ok, warn.
    """
    if not files:
        return "empty", "ok: no changed files to check"

    code_hits = [f for f in files if matches(f, CODE_PREFIXES)]
    doc_hits = [f for f in files if matches(f, DOC_PREFIXES)]

    if not code_hits:
        return "no_code", "ok: no code/runtime paths changed"

    if doc_hits:
        return (
            "ok",
            f"ok: code changed ({len(code_hits)}) and agent docs updated ({len(doc_hits)})",
        )

    message = (
        "Code or runtime files changed without docs/agents/ or AGENTS.md. "
        "Update the canonical agent page in the same PR, or mark Docs N/A in the PR template. "
        f"Code paths: {', '.join(code_hits[:12])}{'…' if len(code_hits) > 12 else ''}"
    )
    return "warn", message


def changed_files(root: Path, base_ref: str | None) -> list[str]:
    if base_ref:
        subprocess.run(
            ["git", "fetch", "--no-tags", "--depth=1", "origin", base_ref],
            cwd=root,
            check=False,
            capture_output=True,
        )
        spec = f"origin/{base_ref}...HEAD"
        proc = subprocess.run(
            ["git", "diff", "--name-only", spec],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    proc = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    staged = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    names.extend(line.strip() for line in staged.stdout.splitlines() if line.strip())
    if names:
        return sorted(set(names))

    proc = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1...HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main(root: Path | None = None) -> int:
    root = root or ROOT
    base_ref = os.environ.get("DOCS_BASE_REF") or os.environ.get("GITHUB_BASE_REF") or ""
    files = changed_files(root, base_ref or None)
    kind, message = evaluate_freshness(files)
    if kind == "warn":
        print(f"::warning title=Docs freshness::{message}")
        print(message, file=sys.stderr)
    else:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Pinned tests for scripts/check_docs_freshness.py."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from check_docs_freshness import (
    CODE_PREFIXES,
    DOC_PREFIXES,
    changed_files,
    evaluate_freshness,
    main,
    matches,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )


def _init_repo_with_origin(tmp: str) -> tuple[Path, Path]:
    base = Path(tmp)
    origin = base / "origin.git"
    work = base / "work"
    # --separate-git-dir keeps git metadata outside a literal `.git/` directory so the
    # suite runs identically in CI and inside sandboxed environments that guard `.git/`.
    _git(base, "init", "--bare", "--initial-branch=main", str(origin))
    _git(
        base,
        "init",
        f"--separate-git-dir={base / 'work.gitdir'}",
        "--initial-branch=main",
        str(work),
    )
    _git(work, "remote", "add", "origin", str(origin))
    (work / "README.md").write_text("# 2048\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "initial")
    _git(work, "push", "-u", "origin", "main")
    return origin, work


class MatchesTests(unittest.TestCase):
    def test_code_prefixes(self) -> None:
        self.assertTrue(matches("client/src/App.jsx", CODE_PREFIXES))
        self.assertTrue(matches("server/app/main.py", CODE_PREFIXES))
        self.assertTrue(matches("observability/grafana/dashboards/genai.json", CODE_PREFIXES))
        self.assertTrue(matches("observability/prometheus.yml", CODE_PREFIXES))
        self.assertTrue(matches("docker-compose.yml", CODE_PREFIXES))
        self.assertTrue(matches(".env.example", CODE_PREFIXES))
        self.assertTrue(matches(".github/workflows/ci.yml", CODE_PREFIXES))
        self.assertFalse(matches("docs/overview.md", CODE_PREFIXES))
        self.assertFalse(matches("README.md", CODE_PREFIXES))

    def test_doc_prefixes(self) -> None:
        self.assertTrue(matches("docs/agents/runtime.md", DOC_PREFIXES))
        self.assertTrue(matches("AGENTS.md", DOC_PREFIXES))
        self.assertFalse(matches("docs/overview.md", DOC_PREFIXES))
        self.assertFalse(matches("docs/getting-started.md", DOC_PREFIXES))


class EvaluateFreshnessTests(unittest.TestCase):
    def test_empty(self) -> None:
        kind, msg = evaluate_freshness([])
        self.assertEqual(kind, "empty")
        self.assertTrue(msg.startswith("ok:"))

    def test_docs_only_is_no_code(self) -> None:
        kind, msg = evaluate_freshness(["docs/overview.md", "README.md"])
        self.assertEqual(kind, "no_code")
        self.assertIn("no code/runtime", msg)

    def test_code_with_agent_docs_ok(self) -> None:
        kind, msg = evaluate_freshness(
            ["server/app/main.py", "docs/agents/server.md", "docs/overview.md"]
        )
        self.assertEqual(kind, "ok")
        self.assertIn("agent docs updated", msg)

    def test_code_with_only_agents_md_ok(self) -> None:
        kind, _ = evaluate_freshness(["client/src/suggest/api.js", "AGENTS.md"])
        self.assertEqual(kind, "ok")

    def test_code_without_agent_docs_warns(self) -> None:
        kind, msg = evaluate_freshness(["server/app/config.py", "docs/overview.md"])
        self.assertEqual(kind, "warn")
        self.assertIn("without docs/agents", msg)
        self.assertIn("server/app/config.py", msg)

    def test_workflow_change_counts_as_code(self) -> None:
        kind, _ = evaluate_freshness([".github/workflows/ci.yml"])
        self.assertEqual(kind, "warn")

    def test_observability_change_without_agent_docs_warns(self) -> None:
        kind, msg = evaluate_freshness(["observability/grafana/dashboards/genai.json"])
        self.assertEqual(kind, "warn")
        self.assertIn("without docs/agents", msg)
        self.assertIn("observability/grafana/dashboards/genai.json", msg)

    def test_more_than_twelve_code_paths_truncates_with_ellipsis(self) -> None:
        twelve = [f"server/app/f{i}.py" for i in range(12)]
        kind_twelve, msg_twelve = evaluate_freshness(twelve)
        self.assertEqual(kind_twelve, "warn")
        self.assertNotIn("…", msg_twelve)

        thirteen = [f"server/app/f{i}.py" for i in range(13)]
        kind, msg = evaluate_freshness(thirteen)
        self.assertEqual(kind, "warn")
        self.assertTrue(msg.endswith("…"))
        self.assertIn("server/app/f11.py", msg)
        self.assertNotIn("server/app/f12.py", msg)


class ChangedFilesAndMainTests(unittest.TestCase):
    def test_multi_commit_pr_against_origin_main_warns_even_when_main_advanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin, work = _init_repo_with_origin(tmp)
            # Advance origin/main via a separate clone so shallow --depth=1 fetch would lose merge-base.
            upstream = base / "upstream"
            _git(
                base,
                "clone",
                f"--separate-git-dir={base / 'upstream.gitdir'}",
                str(origin),
                str(upstream),
            )
            (upstream / "README.md").write_text("# 2048 updated\n", encoding="utf-8")
            _git(upstream, "add", "README.md")
            _git(upstream, "commit", "-m", "advance main")
            _git(upstream, "push", "origin", "main")

            _git(work, "checkout", "-b", "feature")
            (work / "server" / "app").mkdir(parents=True)
            (work / "server" / "app" / "x.py").write_text("X = 1\n", encoding="utf-8")
            _git(work, "add", "server/app/x.py")
            _git(work, "commit", "-m", "commit 1: code change")

            (work / "docs").mkdir(parents=True)
            (work / "docs" / "overview.md").write_text("# Overview\n", encoding="utf-8")
            _git(work, "add", "docs/overview.md")
            _git(work, "commit", "-m", "commit 2: human doc only")

            self.assertEqual(
                sorted(changed_files(work, "main")),
                ["docs/overview.md", "server/app/x.py"],
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DOCS_BASE_REF": "main", "GITHUB_BASE_REF": ""}, clear=False),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                rc = main(work)

            self.assertEqual(rc, 0)
            self.assertIn("::warning title=Docs freshness::", stdout.getvalue())
            self.assertIn("server/app/x.py", stderr.getvalue())

    def test_net_zero_reverted_branch_against_origin_main_is_empty_and_does_not_fall_back(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, work = _init_repo_with_origin(tmp)
            _git(work, "checkout", "-b", "reverted")
            (work / "server" / "app").mkdir(parents=True)
            code_file = work / "server" / "app" / "x.py"
            code_file.write_text("X = 1\n", encoding="utf-8")
            _git(work, "add", "server/app/x.py")
            _git(work, "commit", "-m", "add code")

            code_file.unlink()
            _git(work, "add", "-A")
            _git(work, "commit", "-m", "revert code")

            # HEAD~1...HEAD still touches server/app/x.py, so falling through would warn.
            self.assertEqual(changed_files(work, "main"), [])

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DOCS_BASE_REF": "main", "GITHUB_BASE_REF": ""}, clear=False),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                rc = main(work)

            self.assertEqual(rc, 0)
            self.assertTrue(stdout.getvalue().startswith("ok:"))
            self.assertNotIn("::warning", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")

    def test_dirty_staged_and_unstaged_working_tree_without_base_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, work = _init_repo_with_origin(tmp)
            (work / "client" / "src").mkdir(parents=True)
            tracked = work / "client" / "src" / "App.jsx"
            tracked.write_text("export default 1;\n", encoding="utf-8")
            _git(work, "add", "client/src/App.jsx")
            _git(work, "commit", "-m", "seed tracked client file")

            # Unstaged edit to tracked file + staged new server file.
            tracked.write_text("export default 2;\n", encoding="utf-8")
            (work / "server" / "app").mkdir(parents=True)
            (work / "server" / "app" / "x.py").write_text("X = 1\n", encoding="utf-8")
            _git(work, "add", "server/app/x.py")

            self.assertEqual(
                changed_files(work, None),
                ["client/src/App.jsx", "server/app/x.py"],
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DOCS_BASE_REF": "", "GITHUB_BASE_REF": ""}, clear=False),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                rc = main(work)

            self.assertEqual(rc, 0)
            self.assertIn("::warning title=Docs freshness::", stdout.getvalue())
            self.assertIn("client/src/App.jsx", stderr.getvalue())
            self.assertIn("server/app/x.py", stderr.getvalue())

    def test_shallow_clone_unshallows_to_compute_merge_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin, work = _init_repo_with_origin(tmp)
            # Push a second commit on main so origin/main has history deeper than 1.
            (work / "README.md").write_text("# 2048 v2\n", encoding="utf-8")
            _git(work, "add", "README.md")
            _git(work, "commit", "-m", "v2")
            _git(work, "push", "origin", "main")

            shallow = base / "shallow"
            _git(
                base,
                "clone",
                "--depth=1",
                f"--separate-git-dir={base / 'shallow.gitdir'}",
                f"file://{origin}",
                str(shallow),
            )
            _git(shallow, "checkout", "-b", "shallow-pr")
            (shallow / "server" / "app").mkdir(parents=True)
            (shallow / "server" / "app" / "x.py").write_text("X = 1\n", encoding="utf-8")
            _git(shallow, "add", "server/app/x.py")
            _git(shallow, "commit", "-m", "commit 1: code")
            (shallow / "docs").mkdir(parents=True)
            (shallow / "docs" / "overview.md").write_text("# Overview\n", encoding="utf-8")
            _git(shallow, "add", "docs/overview.md")
            _git(shallow, "commit", "-m", "commit 2: human doc")

            self.assertEqual(
                sorted(changed_files(shallow, "main")),
                ["docs/overview.md", "server/app/x.py"],
            )


if __name__ == "__main__":
    unittest.main()

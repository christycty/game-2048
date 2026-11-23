"""Pinned tests for scripts/check_docs_freshness.py."""

from __future__ import annotations

import unittest

from check_docs_freshness import CODE_PREFIXES, DOC_PREFIXES, evaluate_freshness, matches


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


if __name__ == "__main__":
    unittest.main()

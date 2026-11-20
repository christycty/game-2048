"""Pinned tests for scripts/check_doc_links.py."""

from __future__ import annotations

import unittest
from pathlib import Path

from check_doc_links import find_broken_links, link_targets, main, markdown_files

REPO_ROOT = Path(__file__).resolve().parents[1]


class LinkTargetsTests(unittest.TestCase):
    def test_skips_external_anchors_and_images(self) -> None:
        text = "\n".join(
            [
                "[ok](../docs/overview.md)",
                "[hash](#section)",
                "[web](https://example.com/x)",
                "[mail](mailto:a@b.c)",
                "![img](./shot.png)",
                "[titled](./a.md \"title\")",
                "[anchored](./b.md#frag)",
            ]
        )
        self.assertEqual(
            link_targets(text),
            ["../docs/overview.md", "./a.md", "./b.md"],
        )

    def test_repo_docs_have_no_broken_relative_links(self) -> None:
        errors, checked, file_count = find_broken_links(REPO_ROOT)
        self.assertGreater(checked, 0)
        self.assertGreater(file_count, 0)
        self.assertEqual(errors, [], msg="\n".join(errors))

    def test_detects_missing_link(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("[x](docs/missing.md)\n", encoding="utf-8")
            (root / "docs").mkdir()
            errors, checked, _ = find_broken_links(root)
            self.assertEqual(checked, 1)
            self.assertTrue(any("missing" in e for e in errors))

    def test_main_ok_on_repo(self) -> None:
        self.assertEqual(main(REPO_ROOT), 0)

    def test_markdown_files_includes_agents_tree(self) -> None:
        names = {str(p.relative_to(REPO_ROOT)) for p in markdown_files(REPO_ROOT)}
        self.assertIn("docs/agents/writing-docs.md", names)
        self.assertIn("AGENTS.md", names)


if __name__ == "__main__":
    unittest.main()

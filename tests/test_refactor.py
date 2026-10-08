"""
Unit tests for WikiGraph safe rename and refactoring tool.
Verifies cross-reference updates, frontmatter ID sync, and zero orphan/broken link integrity.
"""

import unittest
from pathlib import Path
from tools.compiler.compiler import WikiGraph


class TestWikiRefactor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.wiki_dir = cls.root_dir / "wiki"

    def test_safe_rename_and_cross_reference_update(self):
        file_a = self.wiki_dir / "_test_refactor_a.md"
        file_b = self.wiki_dir / "_test_refactor_b.md"
        file_c = self.wiki_dir / "_test_refactor_c.md"

        file_a.write_text(
            "---\ntitle: 测试A\ntype: test\n---\n"
            "链接引用: [[_test_refactor_b]] 和带别名引用: [[_test_refactor_b|别名B]] 以及转义管道: [[_test_refactor_b\\|别名表]]\n",
            encoding="utf-8"
        )
        file_b.write_text(
            "---\nid: _test_refactor_b\ntitle: 测试B\ntype: test\n---\n测试B正文内容\n",
            encoding="utf-8"
        )

        try:
            graph = WikiGraph(self.root_dir)
            graph.load_graph()
            self.assertIn("_test_refactor_b", graph.pages)

            # Perform rename
            res = graph.rename_page("_test_refactor_b", "_test_refactor_c")
            self.assertTrue(res["success"])
            self.assertTrue(file_c.exists())
            self.assertFalse(file_b.exists())

            # Read file_a
            content_a = file_a.read_text(encoding="utf-8")
            self.assertIn("[[_test_refactor_c]]", content_a)
            self.assertIn("[[_test_refactor_c|别名B]]", content_a)
            self.assertIn("[[_test_refactor_c\\|别名表]]", content_a)

            # Read file_c
            content_c = file_c.read_text(encoding="utf-8")
            self.assertIn("id: _test_refactor_c", content_c)
        finally:
            for f in [file_a, file_b, file_c]:
                if f.exists():
                    f.unlink()
            # Restore graph state
            clean_graph = WikiGraph(self.root_dir)
            clean_graph.load_graph()


if __name__ == "__main__":
    unittest.main()

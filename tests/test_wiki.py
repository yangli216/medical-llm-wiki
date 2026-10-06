import json
import unittest
from pathlib import Path
from tools.collector.collector import SourceCollector
from tools.compiler.compiler import WikiGraph
from tools.linter.linter import WikiLinter
from tools.search.searcher import WikiSearcher, extract_search_terms


class TestMedicalWiki(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent

    def test_collector_validates_sources(self):
        collector = SourceCollector(self.root_dir)
        report = collector.validate_sources()
        self.assertGreaterEqual(report["total_registered"], 16)
        self.assertEqual(report["valid_count"], report["total_registered"])
        self.assertEqual(len(report["missing_files"]), 0)
        self.assertEqual(len(report["empty_files"]), 0)

    def test_compiler_graph_connectivity(self):
        graph = WikiGraph(self.root_dir)
        graph.load_graph()
        stats = graph.get_stats()
        self.assertGreaterEqual(stats["total_pages"], 40)
        self.assertGreaterEqual(stats["total_links"], 300)
        self.assertEqual(stats["orphan_count"], 0)
        self.assertIn("原发性高血压", graph.pages)
        self.assertIn("二甲双胍", graph.pages)

    def test_linter_health_check(self):
        linter = WikiLinter(self.root_dir)
        res = linter.run_all_checks()
        self.assertTrue(res["is_healthy"], f"Linter issues: {res['broken_links']}, {res['orphans']}")
        self.assertEqual(res["broken_link_count"], 0)
        self.assertEqual(res["orphan_count"], 0)
        self.assertEqual(res["invalid_source_count"], 0)

    def test_search_and_synthesis(self):
        searcher = WikiSearcher(self.root_dir)
        count = searcher.index_wiki()
        self.assertGreaterEqual(count, 40)

        # Test term extraction
        terms = extract_search_terms("高血压合并心力衰竭如何选药？")
        self.assertIn("高血压", terms)
        self.assertIn("心力衰竭", terms)

        # Test search query
        hits = searcher.search("原发性高血压", limit=5)
        self.assertGreater(len(hits), 0)
        titles = [h["title"] for h in hits]
        self.assertTrue(any("高血压" in t for t in titles))

        # Test synthesis
        qa = searcher.synthesize_answer("二甲双胍的适应证与禁忌证")
        self.assertIn("二甲双胍", qa["answer"])
        self.assertGreater(len(qa["references"]), 0)

    def test_web_server_graph_api(self):
        import os, urllib.request, threading, time
        os.environ['no_proxy'] = '*'
        from tools.server.app import run_server
        server_thread = threading.Thread(target=run_server, kwargs={'port': 8788}, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        with urllib.request.urlopen('http://127.0.0.1:8788/api/graph') as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read())
            self.assertIn('nodes', data)
            self.assertIn('links', data)


if __name__ == "__main__":
    unittest.main()

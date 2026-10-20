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
        server_thread = threading.Thread(target=run_server, kwargs={'port': 8792}, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        with urllib.request.urlopen('http://127.0.0.1:8792/api/graph') as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read())
            self.assertIn('nodes', data)
            self.assertIn('links', data)

    def test_order_items_resolution_and_doc_api(self):
        graph = WikiGraph(self.root_dir)
        self.assertEqual(graph.resolve_link("血常规"), "全血细胞分析(血常规)")
        self.assertEqual(graph.resolve_link("CBC"), "全血细胞分析(血常规)")
        self.assertEqual(graph.resolve_link("C反应蛋白测定"), "C反应蛋白测定")
        self.assertEqual(graph.resolve_link("CRP"), "C反应蛋白测定")
        self.assertEqual(graph.resolve_link("胸部X线摄片"), "胸部X线摄片")
        self.assertEqual(graph.resolve_link("胸片"), "胸部X线摄片")
        self.assertEqual(graph.resolve_link("胸部正侧位X线平片"), "胸部X线摄片")

        # Test WikiHTTPHandler doc retrieval
        from tools.server.app import WikiHTTPHandler
        class MockHandler(WikiHTTPHandler):
            def __init__(self):
                self._sent = None
            def _send_json(self, data, status=200):
                self._sent = (status, data)
            def _markdown_to_html(self, text):
                return text

        WikiHTTPHandler.graph = WikiGraph(self.root_dir)
        handler = MockHandler.__new__(MockHandler)

        # 1. 血常规
        handler._sent = None
        handler._handle_wiki_doc({"name": ["血常规"]})
        self.assertEqual(handler._sent[0], 200)
        self.assertEqual(handler._sent[1]["title"], "全血细胞分析(血常规)")
        self.assertEqual(handler._sent[1]["type"], "test")

        # 2. C反应蛋白测定
        handler._sent = None
        handler._handle_wiki_doc({"name": ["C反应蛋白测定"]})
        self.assertEqual(handler._sent[0], 200)
        self.assertEqual(handler._sent[1]["title"], "C反应蛋白测定")
        self.assertEqual(handler._sent[1]["type"], "test")

        # 3. 胸部X线摄片
        handler._sent = None
        handler._handle_wiki_doc({"name": ["胸部X线摄片"]})
        self.assertEqual(handler._sent[0], 200)
        self.assertEqual(handler._sent[1]["title"], "胸部X线摄片")
        self.assertEqual(handler._sent[1]["type"], "examination")

        # 4. Stage 2 Tests (FOBT, PCT, SUA, TSH, CK, D-Dimer, INR)
        stage2_checks = [
            ("便常规", "粪便常规检验加隐血试验(FOBT)", "test"),
            ("FOBT", "粪便常规检验加隐血试验(FOBT)", "test"),
            ("降钙素原", "降钙素原测定(PCT)", "test"),
            ("PCT", "降钙素原测定(PCT)", "test"),
            ("血尿酸", "血清尿酸测定(SUA)", "test"),
            ("SUA", "血清尿酸测定(SUA)", "test"),
            ("甲功三项", "血清甲状腺功能测定(TSH与FT3与FT4)", "test"),
            ("TSH", "血清甲状腺功能测定(TSH与FT3与FT4)", "test"),
            ("肌酸激酶", "血清肌酸激酶测定(CK)", "test"),
            ("CK", "血清肌酸激酶测定(CK)", "test"),
            ("D-二聚体", "血浆D-二聚体测定(D-Dimer)", "test"),
            ("D-Dimer", "血浆D-二聚体测定(D-Dimer)", "test"),
            ("凝血四项", "凝血四项(PT与APTT与INR与FIB)", "test"),
            ("INR", "凝血四项(PT与APTT与INR与FIB)", "test"),
            ("腹部彩超", "腹部超声检查(肝胆胰脾)", "examination"),
            ("颈动脉彩超", "颈动脉彩色多普勒超声检查", "examination"),
            ("肺功能", "肺功能检查(含支气管舒张试验)", "examination"),
            ("支气管舒张试验", "肺功能检查(含支气管舒张试验)", "examination"),
            ("动态心电图", "24小时动态心电图(Holter)", "examination"),
            ("Holter", "24小时动态心电图(Holter)", "examination"),
            ("泌尿系彩超", "泌尿系统超声检查(双肾输尿管膀胱)", "examination"),
            ("双肾B超", "泌尿系统超声检查(双肾输尿管膀胱)", "examination"),
        ]

        for query_name, expected_title, expected_type in stage2_checks:
            handler._sent = None
            handler._handle_wiki_doc({"name": [query_name]})
            self.assertEqual(handler._sent[0], 200, f"Query {query_name} returned status {handler._sent[0]}")
            self.assertEqual(handler._sent[1]["title"], expected_title)
            self.assertEqual(handler._sent[1]["type"], expected_type)

        # 5. Drug insert resolution: 氯苯那敏片 and clinical variants
        drug_checks = [
            {"name": ["氯苯那敏片"], "type": ["medication"]},
            {"name": ["马来酸氯苯那敏片"], "type": ["medication"]},
            {"name": ["扑尔敏"], "type": ["medication"]},
            {"name": ["扑尔敏片 4mg"], "type": ["medication"]},
            {"name": ["[基]氯苯那敏片 4mg*100片/瓶"], "type": ["medication"]},
            {"id": ["氯苯那敏片"], "type": ["medication"]},
            {"id": ["ORDER-9999"], "name": ["氯苯那敏片"], "type": ["medication"]},
            {"name": ["氯苯那敏片[4mg]"], "type": ["prescription"]},
        ]
        for payload in drug_checks:
            handler._sent = None
            handler._handle_wiki_doc(payload)
            self.assertEqual(handler._sent[0], 200, f"Query {payload} returned status {handler._sent[0]}")
            self.assertEqual(handler._sent[1]["title"], "马来酸氯苯那敏片")
            self.assertEqual(handler._sent[1]["type"], "MEDICATION")
            self.assertIn("R06AB04", handler._sent[1]["atcCode"])

        # 6. Drug insert resolution: 右美沙芬糖浆
        dextro_checks = [
            {"name": ["右美沙芬糖浆"], "type": ["medication"]},
            {"name": ["右美沙芬"], "type": ["medication"]},
            {"name": ["氢溴酸右美沙芬糖浆"], "type": ["medication"]},
            {"name": ["右美沙芬糖浆 100ml:150mg"], "type": ["medication"]},
        ]
        for payload in dextro_checks:
            handler._sent = None
            handler._handle_wiki_doc(payload)
            self.assertEqual(handler._sent[0], 200, f"Query {payload} returned status {handler._sent[0]}")
            self.assertEqual(handler._sent[1]["title"], "氢溴酸右美沙芬糖浆")
            self.assertEqual(handler._sent[1]["type"], "MEDICATION")
            self.assertIn("R05DA09", handler._sent[1]["atcCode"])

        # 7. Examination and Lab aliases resolution (胸部数字化X线摄影, 血常规（五分类）)
        exam_checks = [
            ({"name": ["胸部数字化X线摄影"], "type": ["examination"]}, "胸部X线摄片", "examination"),
            ({"name": ["血常规（五分类）"], "type": ["laboratory"]}, "全血细胞分析(血常规)", "test"),
        ]
        for payload, expected_title, expected_type in exam_checks:
            handler._sent = None
            handler._handle_wiki_doc(payload)
            self.assertEqual(handler._sent[0], 200, f"Query {payload} returned status {handler._sent[0]}")
            self.assertEqual(handler._sent[1]["title"], expected_title)
            self.assertEqual(handler._sent[1]["type"], expected_type)


if __name__ == "__main__":
    unittest.main()

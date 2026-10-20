"""
Unit and Integration Tests for Precision Clinical Diagnosis Matching,
Entity Normalization, and Strict Fallback Rejection Guardrails.
"""

import unittest
from pathlib import Path

from tools.cdss.diagnosis_normalizer import ClinicalDiagnosisNormalizer
from tools.cdss.engine import CdssEngine
from tools.compiler.compiler import WikiGraph
from tools.search.searcher import WikiSearcher
from tools.server.app import WikiHTTPHandler


class TestDiagnosisMatchingAndPrecisionGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.graph = WikiGraph(cls.root_dir)
        cls.graph.load_graph()
        cls.searcher = WikiSearcher(cls.root_dir)
        cls.cdss = CdssEngine(cls.root_dir)

    def test_normalizer_administrative_noise_stripping(self):
        """Tests stripping of ICD-10 administrative noise suffixes."""
        cases = [
            ("急性阑尾炎，其他和未特指 K35.8", "急性阑尾炎", "K35.8", ["阑尾炎", "阑尾"]),
            ("2型糖尿病伴周围神经病变，未特指 [E11.4]", "2型糖尿病伴周围神经病变", "E11.4", ["2型糖尿病伴周围神经病变"]),
            ("原发性高血压，其他 (I10)", "原发性高血压", "I10", ["高血压"]),
            ("输尿管结石伴急性绞痛 N23", "输尿管结石伴急性绞痛", "N23", ["输尿管结石伴绞痛", "输尿管结石"]),
        ]
        for raw, expected_canonical, expected_icd, expected_stems_substr in cases:
            norm = ClinicalDiagnosisNormalizer.normalize(raw)
            self.assertEqual(norm.canonical_name, expected_canonical)
            self.assertEqual(norm.icd_code, expected_icd)
            for stem in expected_stems_substr:
                self.assertTrue(
                    any(stem in s or s in stem for s in norm.core_stems),
                    f"Expected stem {stem} in {norm.core_stems} for {raw}",
                )

    def test_rejection_guard_between_acute_diseases(self):
        """
        Verify that an acute appendicitis diagnosis CANNOT match an acute diarrhea protocol,
        preventing the false-positive mismatch shown in the user's screenshot.
        """
        norm_app = ClinicalDiagnosisNormalizer.normalize("急性阑尾炎，其他和未特指 K35.8")

        diarrhea_prot = self.cdss.repo.get("PROT-DIARRHEA-010")
        self.assertIsNotNone(diarrhea_prot)

        # Direct compatibility check
        is_compat = norm_app.is_compatible_with(
            diarrhea_prot.title,
            diarrhea_prot.aliases,
            diarrhea_prot.icd10,
            [it.name for it in diarrhea_prot.items if it.kind == "DIAGNOSIS"],
        )
        self.assertFalse(is_compat, "Acute appendicitis MUST NOT be compatible with acute diarrhea!")

        # CDSS protocol search check
        matches = self.cdss.search_protocols("急性阑尾炎，其他和未特指 K35.8", limit=5)
        self.assertTrue(len(matches) > 0)
        # Top match MUST be appendicitis protocol PROT-APP-043
        self.assertEqual(matches[0]["protocolId"], "PROT-APP-043")
        # Diarrhea MUST NOT appear in the candidate list
        matched_pids = [m["protocolId"] for m in matches]
        self.assertNotIn("PROT-DIARRHEA-010", matched_pids)

    def test_unindexed_disease_prefers_not_found_over_hallucination(self):
        """
        Tests that an unindexed disease (e.g. '急性肠系膜动脉栓塞' or '主动脉夹层')
        returns an empty list or 404 rather than matching an unrelated disease like diarrhea.
        """
        unindexed_q = "急性肠系膜动脉栓塞，未特指 K55.0"
        matches = self.cdss.search_protocols(unindexed_q, limit=5)
        self.assertEqual(len(matches), 0, "Unindexed disease should return 0 protocol matches")

        res_plan = self.cdss.compile_rhn_plan(unindexed_q)
        self.assertFalse(res_plan["success"])
        self.assertTrue(res_plan.get("not_found"))

    def test_endpoint_mock_user_screenshot_resolution(self):
        """
        Simulates the exact HTTP call from the doctor's workstation in the user's screenshot:
        GET /api/knowledge/doc?name=急性阑尾炎，其他和未特指&type=guideline
        """
        class MockHandler:
            def __init__(self, root_dir, graph, searcher, cdss):
                self.root_dir = root_dir
                self.graph = graph
                self.searcher = searcher
                self.cdss = cdss
                self.sent_json = None
                self.sent_status = None

            def _markdown_to_html(self, text):
                return "<p>" + text[:50] + "</p>"

            def _send_json(self, data, status=200):
                self.sent_json = data
                self.sent_status = status

        MockHandler._handle_wiki_doc = WikiHTTPHandler._handle_wiki_doc
        h = MockHandler(self.root_dir, self.graph, self.searcher, self.cdss)

        # 1. Screenshot call: Must return appendicitis guideline/protocol
        h._handle_wiki_doc({"name": ["急性阑尾炎，其他和未特指"], "type": ["guideline"]})
        self.assertEqual(h.sent_status, 200)
        self.assertIn("阑尾炎", h.sent_json.get("title", ""))
        self.assertNotIn("腹泻", h.sent_json.get("title", ""))

        # 2. Unindexed call: Must return 404 with not_found=True
        h._handle_wiki_doc({"name": ["急性坏死性筋膜炎"], "type": ["guideline"]})
        self.assertEqual(h.sent_status, 404)
        self.assertTrue(h.sent_json.get("not_found"))
        self.assertIn("暂未收录", h.sent_json.get("error", ""))

    def test_newly_added_common_diseases_matching(self):
        """Verifies that all 8 newly added common clinical conditions match accurately."""
        test_queries = [
            ("急性阑尾炎，其他和未特指", "PROT-APP-043", "阑尾炎"),
            ("急性胆囊炎与胆石症", "PROT-CHOLE-044", "胆囊炎"),
            ("急性胰腺炎", "PROT-PANCR-045", "胰腺炎"),
            ("消化性溃疡伴上腹痛", "PROT-PU-046", "溃疡"),
            ("泌尿系统结石伴急性肾绞痛", "PROT-RENALCOLIC-047", "肾绞痛"),
            ("特发性面神经麻痹", "PROT-BELL-048", "面神经麻痹"),
            ("短暂性脑缺血发作", "PROT-TIA-049", "短暂性脑缺血发作"),
            ("神经根型颈椎病", "PROT-CERV-050", "颈椎病"),
        ]
        for query, expected_pid, keyword in test_queries:
            matches = self.cdss.search_protocols(query, limit=1)
            self.assertTrue(len(matches) > 0, f"Expected match for query: {query}")
            self.assertEqual(matches[0]["protocolId"], expected_pid)
            self.assertIn(keyword, matches[0]["title"])

    def test_icd10_prioritized_mapping_and_crosswalk(self):
        """
        Verifies that ICD-10 codes take priority, support 6-digit hierarchy reduction,
        and support clinical crosswalk mappings (e.g. J39.900 -> J06.9, K35.900 -> K35.8).
        """
        from tools.cdss.icd_mapper import ICDMapper
        mapper = ICDMapper.get_instance()

        # 1. Candidate resolution
        cands_uri = mapper.resolve_candidates("J39.900")
        self.assertIn("J06.9", cands_uri)
        self.assertIn("J06", cands_uri)

        cands_app = mapper.resolve_candidates("K35.900")
        self.assertIn("K35.8", cands_app)

        # 2. WikiGraph ICD-10 resolution
        page_dis = self.graph.resolve_by_icd("J39.900", type_hint="disease")
        self.assertIsNotNone(page_dis)
        self.assertEqual(page_dis.file_path.stem, "急性上呼吸道感染")

        page_prot = self.graph.resolve_by_icd("J39.900", type_hint="protocol")
        self.assertIsNotNone(page_prot)
        self.assertIn("急性上呼吸道感染", page_prot.title)

        page_app = self.graph.resolve_by_icd("K35.900", type_hint="disease")
        self.assertIsNotNone(page_app)
        self.assertEqual(page_app.file_path.stem, "急性阑尾炎")

        # 3. ProtocolRepository ICD-10 resolution
        prot_uri = self.cdss.repo.get_by_icd("J39.900")
        self.assertIsNotNone(prot_uri)
        self.assertEqual(prot_uri.protocol_id, "PROT-URI-005")

        prot_app = self.cdss.repo.get_by_icd("K35.900")
        self.assertIsNotNone(prot_app)
        self.assertEqual(prot_app.protocol_id, "PROT-APP-043")

        # 4. Mock HTTP Handler with explicit icd10 and mixed string
        class MockHandler:
            def __init__(self, root_dir, graph, searcher, cdss):
                self.root_dir = root_dir
                self.graph = graph
                self.searcher = searcher
                self.cdss = cdss
                self.sent_json = None
                self.sent_status = None

            def _markdown_to_html(self, text):
                return "<p>" + text[:50] + "</p>"

            def _send_json(self, data, status=200):
                self.sent_json = data
                self.sent_status = status

        MockHandler._handle_wiki_doc = WikiHTTPHandler._handle_wiki_doc
        h = MockHandler(self.root_dir, self.graph, self.searcher, self.cdss)

        # Guideline lookup with icd10 parameter
        h._handle_wiki_doc({"icd10": ["J39.900"], "type": ["guideline"]})
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(h.sent_json.get("id"), "PROT-URI-005")
        self.assertEqual(h.sent_json.get("type"), "protocol")

        # Disease wiki doc lookup with icd10 parameter
        h._handle_wiki_doc({"icd10": ["J39.900"]})
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(h.sent_json.get("id"), "急性上呼吸道感染")
        self.assertEqual(h.sent_json.get("type"), "disease")

        # Mixed name + bracketed icd10
        h._handle_wiki_doc({"name": ["上呼吸道疾病 (J39.900)"], "type": ["guideline"]})
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(h.sent_json.get("id"), "PROT-URI-005")


if __name__ == "__main__":
    unittest.main()

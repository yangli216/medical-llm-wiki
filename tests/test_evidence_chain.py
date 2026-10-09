"""
Unit tests for EvidenceChainEngine and Wiki Document API in medical-llm-wiki.
"""

import unittest
from pathlib import Path
from tools.cdss.evidence_chain import EvidenceChainEngine


class TestEvidenceChainEngine(unittest.TestCase):
    def setUp(self):
        self.root_dir = Path(__file__).resolve().parent.parent
        self.engine = EvidenceChainEngine(self.root_dir)

    def test_hypertension_evidence_chain(self):
        """Tests that hypertension 2级 derives expected checklist, gap orders, and guidelines."""
        patient = {
            "age": 56,
            "gender": "男",
            "chiefComplaint": "头晕、颈项胀痛2周，测血压升高3天",
            "presentIllness": "伴晨起头晕，后枕部胀痛，活动后明显",
            "medicalHistory": "吸烟30年，每日1包；否认慢病史",
            "vitals": {
                "systolicBp": 168,
                "diastolicBp": 102,
                "heartRate": 82,
            },
        }

        res = self.engine.evaluate("原发性高血压 2级", "I10", patient)
        self.assertTrue(res["success"])
        self.assertEqual(res["protocolId"], "PROT-HTN-001")
        self.assertEqual(res["diagnosis"]["code"], "I10")

        checkpoints = res["checkpoints"]
        self.assertGreaterEqual(len(checkpoints), 3)

        # 1. Vital checkpoint (≥ 160/100)
        vital_cp = next((c for c in checkpoints if c["type"] == "VITAL"), None)
        self.assertIsNotNone(vital_cp)
        self.assertEqual(vital_cp["status"], "MET")
        self.assertIn("168/102", vital_cp["label"])
        self.assertIn("160/100", vital_cp["label"])

        # 2. Symptom checkpoint
        symptom_cp = next((c for c in checkpoints if c["type"] == "SYMPTOM"), None)
        self.assertIsNotNone(symptom_cp)
        self.assertEqual(symptom_cp["status"], "MET")
        self.assertTrue("头晕" in symptom_cp["label"] or "胀痛" in symptom_cp["label"])

        # 3. Risk factor checkpoint (Smoking + Male > 50)
        risk_cp = next((c for c in checkpoints if c["type"] == "RISK_FACTOR"), None)
        self.assertIsNotNone(risk_cp)
        self.assertEqual(risk_cp["status"], "MET")
        self.assertIn("吸烟", risk_cp["label"])
        self.assertIn("男性", risk_cp["label"])

        # 4. Suggested gap checkpoint
        gap_cp = next((c for c in checkpoints if c["status"] == "SUGGESTED"), None)
        self.assertIsNotNone(gap_cp)
        self.assertIn("心电图", gap_cp["label"])
        self.assertIn("血生化", gap_cp["label"])

        # 5. Gap orders
        gap_orders = res["gapOrders"]
        self.assertGreaterEqual(len(gap_orders), 2)
        names = [o["name"] for o in gap_orders]
        self.assertTrue(any("心电图" in n for n in names))
        self.assertTrue(any("生化" in n for n in names))

        # 6. Guidelines
        guidelines = res["guidelines"]
        self.assertGreaterEqual(len(guidelines), 1)
        first_guide = guidelines[0]
        self.assertIn("中国高血压防治指南", first_guide["title"])
        self.assertEqual(first_guide["authority"], "中华医学会心血管病学分会 / 中国高血压联盟 / 国家心血管病中心")

    def test_type2_diabetes_evidence_chain(self):
        """Tests that T2DM derives metabolic checklist and gap orders."""
        patient = {
            "age": 48,
            "gender": "女",
            "chiefComplaint": "口干、多饮多尿伴消瘦3月",
            "vitals": {
                "bloodGlucose": 8.9,
            },
        }

        res = self.engine.evaluate("2型糖尿病", "E11", patient)
        self.assertTrue(res["success"])
        checkpoints = res["checkpoints"]
        self.assertTrue(any(c["type"] == "VITAL" and "7.0" in c["label"] for c in checkpoints))
        self.assertTrue(any("多饮" in c["label"] or "多尿" in c["label"] for c in checkpoints))
        self.assertTrue(any(c["status"] == "SUGGESTED" and "HbA1c" in c["label"] for c in checkpoints))

    def test_uri_pharyngitis_evidence_chain(self):
        """Tests that acute upper respiratory tract infection derives grounded checkpoints and correct ENT guidelines."""
        patient = {
            "chiefComplaint": "咽痛伴咳嗽3天",
            "presentIllness": "患者3天前出现咳嗽，伴咽痛，吞咽时疼痛加剧。病程中无发热、咳痰、气促等描述。",
            "physicalExam": "扁桃体红肿。",
            "medicalHistory": "既往体健",
        }
        res = self.engine.evaluate("急性上呼吸道感染，未特指", "J06.9", patient)
        self.assertTrue(res["success"])
        self.assertEqual(res["protocolId"], "PROT-URI-005")
        self.assertIn("咽痛", res["summary"])
        self.assertIn("扁桃体红肿", res["summary"])

        checkpoints = res["checkpoints"]
        # 1. Symptom checkpoint
        symptom_cp = next((c for c in checkpoints if c["type"] == "SYMPTOM"), None)
        self.assertIsNotNone(symptom_cp)
        self.assertIn("咽痛（吞咽时疼痛加剧）", symptom_cp["label"])
        self.assertIn("3天", symptom_cp["label"])

        # 2. Physical exam checkpoint
        exam_cp = next((c for c in checkpoints if c["type"] == "EXAMINATION"), None)
        self.assertIsNotNone(exam_cp)
        self.assertIn("扁桃体红肿", exam_cp["label"])

        # 3. Differential checkpoint
        diff_cp = next((c for c in checkpoints if c["type"] == "DIFFERENTIAL"), None)
        self.assertIsNotNone(diff_cp)
        self.assertIn("无发热", diff_cp["label"])

        # 4. Gap orders
        gap_orders = res["gapOrders"]
        self.assertTrue(any("血细胞" in o["name"] or "CRP" in o["name"] for o in gap_orders))
        crp_order = next((o for o in gap_orders if "血细胞" in o["name"] or "CRP" in o["name"]), None)
        self.assertIsNotNone(crp_order)
        self.assertIn("扁桃体炎", crp_order["indication"])

        # 5. Guidelines
        guidelines = res["guidelines"]
        guide_titles = [g["title"] for g in guidelines]
        self.assertTrue(any("急性咽峡炎/扁桃体炎" in t for t in guide_titles))
        self.assertTrue(any("抗菌药物" in t for t in guide_titles))
        # Ensure dizziness guideline is NOT in guidelines
    def test_generic_fallback_evidence_chain(self):
        """Tests that unknown diagnosis safely falls back to general clinical guidance."""
        res = self.engine.evaluate("某种罕见未归类疾病", "R69", {"age": 30, "chiefComplaint": "胸闷不适3天"})
        self.assertTrue(res["success"])
        self.assertGreaterEqual(len(res["checkpoints"]), 1)
        self.assertGreaterEqual(len(res["gapOrders"]), 1)
    def test_paracetamol_insert_resolution(self):
        """Tests that paracetamol drug monograph is accurately retrieved by name, dose, or brand."""
        from tools.cdss.drug_checker import DrugInsertRepository
        repo = DrugInsertRepository(self.root_dir)
        d_exact = repo.get("对乙酰氨基酚片")
        self.assertIsNotNone(d_exact)
        self.assertEqual(d_exact["id"], "对乙酰氨基酚片")
        self.assertIn("2.0g", d_exact["max_daily_dose"])

        # By generic root without form
        d_root = repo.get("对乙酰氨基酚")
        self.assertIsNotNone(d_root)
        self.assertEqual(d_root["id"], "对乙酰氨基酚片")

        # By trade name
        d_trade = repo.get("泰诺林")
        self.assertIsNotNone(d_trade)
        self.assertEqual(d_trade["id"], "对乙酰氨基酚片")


if __name__ == "__main__":
    unittest.main()

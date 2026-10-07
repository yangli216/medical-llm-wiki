"""
Unit and integration tests for CDSS Clinical Plan Recommendation & Safety Engine.
Verifies contract alignment with the RHN outpatient doctor workstation.
"""

import json
import os
import unittest
import urllib.request
import threading
import time
from pathlib import Path

os.environ['no_proxy'] = '*'

from tools.cdss.protocol_loader import ProtocolRepository
from tools.cdss.engine import CdssEngine
from tools.server.app import run_server


class TestCdssEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.engine = CdssEngine(cls.root_dir)

    def test_load_all_protocols(self):
        repo = self.engine.repo
        protocols = repo.list_all()
        self.assertEqual(len(protocols), 23)

        htn = repo.get("PROT-HTN-001")
        self.assertIsNotNone(htn)
        self.assertEqual(htn.icd10, "I10")
        self.assertIn("chiefComplaint", htn.note_template)
        self.assertIn("presentIllness", htn.note_template)
        self.assertIn("physicalExam", htn.note_template)
        self.assertGreater(len(htn.items), 5)
        self.assertGreater(len(htn.rules), 0)

        # Assert new protocols exist
        self.assertIsNotNone(repo.get("PROT-PED-013"))
        self.assertIsNotNone(repo.get("PROT-PED-014"))
        self.assertIsNotNone(repo.get("PROT-HERPES-015"))
        self.assertIsNotNone(repo.get("PROT-AR-016"))
        self.assertIsNotNone(repo.get("PROT-ANX-017"))
        self.assertIsNotNone(repo.get("PROT-TCM-018"))
        self.assertIsNotNone(repo.get("PROT-INSOM-019"))
        self.assertIsNotNone(repo.get("PROT-MIGR-020"))
        self.assertIsNotNone(repo.get("PROT-OSTEO-021"))
        self.assertIsNotNone(repo.get("PROT-DRYEYE-022"))
        self.assertIsNotNone(repo.get("PROT-CONSTIP-023"))

    def test_search_protocols(self):
        # 1. Search by condition
        matches = self.engine.search_protocols("高血压", limit=3)
        self.assertGreater(len(matches), 0)
        self.assertEqual(matches[0]["protocolId"], "PROT-HTN-001")

        # 2. Search by ICD-10
        matches_icd = self.engine.search_protocols("E11.9", limit=1)
        self.assertGreater(len(matches_icd), 0)
        self.assertEqual(matches_icd[0]["protocolId"], "PROT-T2DM-002")

        # 3. Search by symptom
        matches_symp = self.engine.search_protocols("头晕眩晕", limit=2)
        self.assertGreater(len(matches_symp), 0)
        self.assertEqual(matches_symp[0]["protocolId"], "PROT-DIZZY-007")

        # 4. Search by pediatric condition
        matches_ped = self.engine.search_protocols("小儿急性支气管炎", limit=1)
        self.assertGreater(len(matches_ped), 0)
        self.assertEqual(matches_ped[0]["protocolId"], "PROT-PED-013")

        # 5. Search by allergic rhinitis
        matches_ar = self.engine.search_protocols("变应性鼻炎", limit=1)
        self.assertGreater(len(matches_ar), 0)
        self.assertEqual(matches_ar[0]["protocolId"], "PROT-AR-016")

        # 6. Search by herpes zoster
        matches_herpes = self.engine.search_protocols("带状疱疹", limit=1)
        self.assertGreater(len(matches_herpes), 0)
        self.assertEqual(matches_herpes[0]["protocolId"], "PROT-HERPES-015")

        # 7. Search by migraine
        matches_migr = self.engine.search_protocols("偏头痛", limit=1)
        self.assertGreater(len(matches_migr), 0)
        self.assertEqual(matches_migr[0]["protocolId"], "PROT-MIGR-020")

        # 8. Search by osteoporosis
        matches_osteo = self.engine.search_protocols("骨质疏松", limit=1)
        self.assertGreater(len(matches_osteo), 0)
        self.assertEqual(matches_osteo[0]["protocolId"], "PROT-OSTEO-021")

        # 9. Search by dry eye
        matches_dry = self.engine.search_protocols("干眼症", limit=1)
        self.assertGreater(len(matches_dry), 0)
        self.assertEqual(matches_dry[0]["protocolId"], "PROT-DRYEYE-022")

    def test_rhn_plan_intent_contract(self):
        compiled = self.engine.compile_rhn_plan("2型糖尿病")
        self.assertTrue(compiled["success"])
        plan_intent = compiled["planIntent"]

        # Assert alignment with com.rhn.ai.application.ClinicalAiModelGateway.PlanIntent
        self.assertIn("name", plan_intent)
        self.assertIn("description", plan_intent)
        self.assertIn("narrative", plan_intent)
        self.assertIn("items", plan_intent)
        self.assertIn("noteTemplateContent", plan_intent)

        # Assert noteTemplateContent conforms to 6 required clinical narrative parts
        nt = plan_intent["noteTemplateContent"]
        for key in ["chiefComplaint", "presentIllness", "medicalHistory", "physicalExam", "healthEducation", "followUp"]:
            self.assertIn(key, nt)
            self.assertTrue(len(nt[key]) > 10)
            self.assertNotIn("[待填写]", nt[key])
            self.assertNotIn("[待查体]", nt[key])

        # Assert items conform to kind, name, sourceQuote, origin, details
        items = plan_intent["items"]
        kinds = {it["kind"] for it in items}
        self.assertIn("DIAGNOSIS", kinds)
        self.assertIn("MEDICATION", kinds)
        self.assertIn("LABORATORY", kinds)

        for it in items:
            self.assertIn("kind", it)
            self.assertIn("name", it)
            self.assertIn("details", it)

    def test_rhn_treatment_recommendations(self):
        compiled = self.engine.compile_rhn_plan("PROT-HTN-001")
        recs = compiled["treatmentRecommendations"]
        self.assertGreater(len(recs), 0)

        # Check alignment with ClinicalAiTreatmentRecommendation
        for rec in recs:
            self.assertIn(rec["type"], ["MEDICATION", "LABORATORY", "EXAMINATION"])
            self.assertTrue(rec["name"])
            self.assertTrue(rec["code"])
            if rec["type"] == "MEDICATION" and rec["orderDraft"]:
                od = rec["orderDraft"]
                self.assertIn("routeCode", od)
                self.assertIn("frequencyCode", od)
                self.assertIsNotNone(od["doseValue"])
                self.assertTrue(od["doseUnit"])

    def test_cdss_prescription_safety_rules(self):
        # 1. Dual RAS blockade (Red Alert)
        res_ras = self.engine.audit_prescription(["依那普利片 10mg", "氯沙坦钾片 50mg"])
        self.assertFalse(res_ras["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-SAFETY-RAS-DUAL" for a in res_ras["alerts"]))

        # 2. Metformin with eGFR < 30 (Red Alert)
        res_met = self.engine.audit_prescription(["盐酸二甲双胍片 0.5g"], {"egfr": 25})
        self.assertFalse(res_met["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-SAFETY-METFORMIN-RENAL" for a in res_met["alerts"]))

        # 3. Metformin with eGFR 40 (Yellow Alert)
        res_met_warn = self.engine.audit_prescription(["盐酸二甲双胍片 0.5g"], {"egfr": 40})
        self.assertTrue(res_met_warn["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-SAFETY-METFORMIN-WARN" for a in res_met_warn["alerts"]))

        # 4. Nitrates + Sildenafil (Red Alert)
        res_nitrate = self.engine.audit_prescription(["硝酸甘油片 0.5mg", "枸橼酸西地那非片 50mg"])
        self.assertFalse(res_nitrate["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-SAFETY-NITRATE-PDE5" for a in res_nitrate["alerts"]))

        # 5. Prescribing cascade: CCB + Diuretic (Yellow Alert)
        res_cascade = self.engine.audit_prescription(["苯磺酸氨氯地平片 5mg", "呋塞米片 20mg"])
        self.assertTrue(any(a["ruleId"] == "RULE-CASCADE-CCB-EDEMA" for a in res_cascade["alerts"]))

        # 6. Duplicate NSAIDs (Red Alert)
        res_nsaids = self.engine.audit_prescription(["布洛芬缓释胶囊 0.3g", "双氯芬酸钠缓释片 75mg"])
        self.assertFalse(res_nsaids["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-SAFETY-DUAL-NSAIDS" for a in res_nsaids["alerts"]))

        # 7. Pediatric fever with Aspirin (Red Alert)
        res_ped_asp = self.engine.audit_prescription(["阿司匹林肠溶片 100mg"], {"age": 6})
        self.assertFalse(res_ped_asp["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-PEDIATRIC-ASPIRIN" for a in res_ped_asp["alerts"]))

        # 8. Pediatric with Quinolones (Red Alert)
        res_ped_quin = self.engine.audit_prescription(["左氧氟沙星片 0.5g"], {"age": 14})
        self.assertFalse(res_ped_quin["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-PEDIATRIC-QUINOLONE" for a in res_ped_quin["alerts"]))

        # 9. Pediatric diarrhea with Loperamide (Red Alert)
        res_ped_lop = self.engine.audit_prescription(["盐酸洛哌丁胺胶囊 2mg"], {"age": 3})
        self.assertFalse(res_ped_lop["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-PEDIATRIC-LOPERAMIDE" for a in res_ped_lop["alerts"]))

        # 10. TCM Xiaoke Pill + Sulfonylurea (Red Alert)
        res_tcm_xk = self.engine.audit_prescription(["消渴丸", "格列齐特缓释片 30mg"])
        self.assertFalse(res_tcm_xk["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-TCM-XIAOKE-SULFONYLUREA" for a in res_tcm_xk["alerts"]))

        # 11. TCM Acetaminophen + Western Paracetamol (Red Alert)
        res_tcm_apap = self.engine.audit_prescription(["感冒灵颗粒", "酚麻美敏片(泰诺)"])
        self.assertFalse(res_tcm_apap["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-TCM-ACETAMINOPHEN-DUAL" for a in res_tcm_apap["alerts"]))

        # 12. Valacyclovir with eGFR < 50 (Yellow Alert)
        res_herpes_val = self.engine.audit_prescription(["盐酸伐昔洛韦片 0.5g"], {"egfr": 35})
        self.assertTrue(res_herpes_val["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-HERPES-VALACYCLOVIR-RENAL" for a in res_herpes_val["alerts"]))

        # 13. Triptan in CAD patient (Red Alert)
        res_triptan_cad = self.engine.audit_prescription(["佐米曲普坦片 2.5mg"], {"history": "既往冠心病陈旧性心肌梗死史"})
        self.assertFalse(res_triptan_cad["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-MIGR-TRIPTAN-CARDIOVASCULAR" for a in res_triptan_cad["alerts"]))

        # 14. Bisphosphonate in severe renal impairment eGFR < 35 (Red Alert)
        res_osteo_renal = self.engine.audit_prescription(["阿仑膦酸钠片 70mg"], {"egfr": 28})
        self.assertFalse(res_osteo_renal["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-OSTEO-BISPHOSPHONATE-RENAL" for a in res_osteo_renal["alerts"]))

        # 15. Stimulant laxative alert (Yellow Alert)
        res_stim_lax = self.engine.audit_prescription(["番泻叶颗粒", "比沙可啶肠溶片 5mg"])
        self.assertTrue(res_stim_lax["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-CONSTIP-STIMULANT-LAXATIVE" for a in res_stim_lax["alerts"]))

        # 16. Pure dry eye with antibiotic eyedrops misuse (Red Alert)
        res_dry_abx = self.engine.audit_prescription(["左氧氟沙星滴眼液", "玻璃酸钠滴眼液"], {"diagnosis": "双眼干眼症"})
        self.assertFalse(res_dry_abx["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-DRYEYE-ANTIBIOTIC-MISUSE" for a in res_dry_abx["alerts"]))

    def test_http_api_endpoints(self):
        server_thread = threading.Thread(target=run_server, kwargs={"port": 8789}, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        # GET /api/cdss/protocols
        req = urllib.request.Request("http://127.0.0.1:8789/api/cdss/protocols")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertGreaterEqual(len(data), 12)

        # POST /api/cdss/compile-rhn-plan
        compile_body = json.dumps({"input": "原发性高血压"}).encode("utf-8")
        req_post = urllib.request.Request(
            "http://127.0.0.1:8789/api/cdss/compile-rhn-plan",
            data=compile_body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_post) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["planIntent"]["name"], "原发性高血压门诊规范诊疗方案")

        # POST /api/cdss/audit
        audit_body = json.dumps({
            "medications": ["依那普利片", "氯沙坦钾片"],
            "patient": {"egfr": 50},
        }).encode("utf-8")
        req_audit = urllib.request.Request(
            "http://127.0.0.1:8789/api/cdss/audit",
            data=audit_body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_audit) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(data["is_safe"])
            self.assertGreater(data["red_count"], 0)


if __name__ == "__main__":
    unittest.main()

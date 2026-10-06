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
        self.assertGreaterEqual(len(protocols), 12)

        htn = repo.get("PROT-HTN-001")
        self.assertIsNotNone(htn)
        self.assertEqual(htn.icd10, "I10")
        self.assertIn("chiefComplaint", htn.note_template)
        self.assertIn("presentIllness", htn.note_template)
        self.assertIn("physicalExam", htn.note_template)
        self.assertGreater(len(htn.items), 5)
        self.assertGreater(len(htn.rules), 0)

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

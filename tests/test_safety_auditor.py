"""
Comprehensive Production-Grade Tests for CDSS Safety Auditor,
Dynamic Physiological Parameter Normalizer, and Dosage Limits Auditor.
"""

import unittest
from pathlib import Path
from tools.cdss.parameter_normalizer import ClinicalParameterNormalizer
from tools.cdss.dosage_auditor import DosageLimitsAuditor
from tools.cdss.safety_auditor import ComprehensiveSafetyAuditor
from tools.cdss.engine import CdssEngine


class TestCdssSafetyAuditor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.engine = CdssEngine(cls.root_dir)
        cls.safety_auditor = ComprehensiveSafetyAuditor(cls.root_dir)
        cls.dosage_auditor = DosageLimitsAuditor(repo=cls.safety_auditor.repo)

    # -------------------------------------------------------------------------
    # 1. Parameter Normalizer Tests
    # -------------------------------------------------------------------------
    def test_parameter_normalizer_demographics(self):
        # Elderly female
        res = ClinicalParameterNormalizer.normalize_patient({"age": 70, "gender": "女"})
        self.assertEqual(res["age"], 70)
        self.assertTrue(res["is_elderly"])
        self.assertFalse(res["is_pediatric"])
        self.assertTrue(res["is_female"])

        # Pediatric male
        res_ped = ClinicalParameterNormalizer.normalize_patient({"age": 5, "gender": "男"})
        self.assertEqual(res_ped["age"], 5)
        self.assertTrue(res_ped["is_pediatric"])
        self.assertTrue(res_ped["is_child_under_8"])
        self.assertFalse(res_ped["is_female"])

    def test_parameter_normalizer_dynamic_egfr(self):
        # 68yo male with Scr = 180 μmol/L -> eGFR should be derived around 34
        res = ClinicalParameterNormalizer.normalize_patient({
            "age": 68,
            "gender": "男",
            "scr": 180,
            "weight": 65,
        })
        self.assertIn("egfr", res)
        self.assertLess(res["egfr"], 40.0)
        self.assertGreater(res["egfr"], 25.0)
        self.assertIn("crcl", res)
        self.assertIn("derived_ckd_stage", res)
        self.assertTrue(res.get("egfr_lt_35") or res.get("egfr_lt_45"))

    def test_parameter_normalizer_pregnancy_inference(self):
        # Text corpus indicating pregnancy
        res = ClinicalParameterNormalizer.normalize_patient({
            "age": 28,
            "gender": "女",
            "chiefComplaint": "停经32周，血压偏高3天",
            "diagnosis": "妊娠期高血压",
        })
        self.assertTrue(res["is_pregnant"])
        self.assertTrue(res["pregnancy"])

    # -------------------------------------------------------------------------
    # 2. Dosage Limits Auditor Tests
    # -------------------------------------------------------------------------
    def test_dosage_limits_normal_safe(self):
        res = self.dosage_auditor.audit_medication_dosage("盐酸二甲双胍片 0.5g tid")
        self.assertTrue(res["evaluated"])
        self.assertFalse(res["isOverdose"])
        self.assertEqual(res["level"], "PASS")

    def test_dosage_limits_overdose_blocked(self):
        # 1.5g tid = 4.5g/d (Exceeds max 2550mg/d)
        res = self.dosage_auditor.audit_medication_dosage("盐酸二甲双胍片 1.5g tid")
        self.assertTrue(res["evaluated"])
        self.assertTrue(res["isOverdose"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertEqual(res["severity"], "RED")

    def test_dosage_limits_paracetamol_overdose(self):
        # 0.5g q4h = 3.0g/d (Exceeds Paracetamol max 2000mg/d)
        res = self.dosage_auditor.audit_medication_dosage("对乙酰氨基酚片 0.5g q4h")
        self.assertTrue(res["evaluated"])
        self.assertTrue(res["isOverdose"])
        self.assertEqual(res["severity"], "RED")

    # -------------------------------------------------------------------------
    # 3. Comprehensive Preflight Contract Tests (Aligned with RHN)
    # -------------------------------------------------------------------------
    def test_preflight_interactions_blocked(self):
        # Nitrate + PDE5i
        res = self.safety_auditor.audit_preflight_safety(
            medications=["硝酸甘油片 0.5mg", "枸橼酸西地那非片 50mg"],
            patient_context={"age": 60, "gender": "男"}
        )
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertGreater(res["blockingCount"], 0)

        # Check RHN EvaluationBoundaries
        bounds = res["evaluationBoundaries"]
        self.assertEqual(bounds["interactions"]["status"], "EVALUATED")
        self.assertEqual(bounds["interactions"]["evaluationCode"], "BLOCKED")
        self.assertGreater(len(bounds["interactions"]["alerts"]), 0)

    def test_preflight_contraindications_pregnancy_blocked(self):
        # Pregnancy + ACEI (Enalapril)
        res = self.safety_auditor.audit_preflight_safety(
            medications=["马来酸依那普利片 10mg qd"],
            patient_context={"age": 30, "gender": "女", "pregnancy": True}
        )
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")

        bounds = res["evaluationBoundaries"]
        self.assertEqual(bounds["contraindications"]["status"], "EVALUATED")
        self.assertEqual(bounds["contraindications"]["evaluationCode"], "BLOCKED")
        self.assertTrue(any("妊娠" in a["title"] for a in bounds["contraindications"]["alerts"]))

    def test_preflight_dynamic_scr_leads_to_block(self):
        # Patient with only Scr = 240 μmol/L, age 75, prescribed Metformin
        # System dynamically calculates eGFR < 30 and triggers METFORMIN-RENAL block
        res = self.safety_auditor.audit_preflight_safety(
            medications=["盐酸二甲双胍片 0.5g bid"],
            patient_context={"age": 75, "gender": "男", "scr": 240}
        )
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertIn("derived_egfr", res["inferredPatientParameters"])

        # Check alert specifically details eGFR
        all_alerts = res["allAlerts"]
        renal_alert = next((a for a in all_alerts if "二甲双胍" in a["title"]), None)
        self.assertIsNotNone(renal_alert)

    def test_preflight_all_pass_clean(self):
        # Clean prescription: Amlodipine 5mg qd for 55yo male with hypertension
        res = self.safety_auditor.audit_preflight_safety(
            medications=["苯磺酸氨氯地平片 5mg qd"],
            patient_context={"age": 55, "gender": "男", "diagnosis": "原发性高血压"}
        )
        self.assertTrue(res["canPrescribe"])
        self.assertEqual(res["level"], "PASS")
        self.assertEqual(res["blockingCount"], 0)
        self.assertEqual(res["warningCount"], 0)

        bounds = res["evaluationBoundaries"]
        self.assertEqual(bounds["interactions"]["evaluationCode"], "PASS")
        self.assertEqual(bounds["contraindications"]["evaluationCode"], "PASS")
        self.assertEqual(bounds["dosageLimits"]["evaluationCode"], "PASS")

    # -------------------------------------------------------------------------
    # 4. Alternative Re-routing Contract Tests
    # -------------------------------------------------------------------------
    def test_alternatives_rerouting_contracts(self):
        # 1. Test KOA Systemic Steroid -> Re-routing to Celecoxib / Topical Diclofenac
        res_koa = self.safety_auditor.audit_preflight_safety(
            medications=["地塞米松片 0.75mg qd"],
            patient_context={"age": 65, "gender": "女", "history": "双膝骨关节炎伴疼痛", "is_koa": True}
        )
        self.assertFalse(res_koa["canPrescribe"])
        koa_alert = next((a for a in res_koa["allAlerts"] if a.get("ruleId") == "RULE-KOA-SYSTEMIC-STEROID"), None)
        self.assertIsNotNone(koa_alert)
        self.assertTrue(len(koa_alert["alternatives"]) >= 2)
        
        # Verify alternative order draft structure
        alt_cele = koa_alert["alternatives"][0]
        self.assertEqual(alt_cele["name"], "塞来昔布胶囊")
        self.assertIsNotNone(alt_cele["orderDraft"])
        self.assertEqual(alt_cele["orderDraft"]["routeCode"], "PO")
        self.assertEqual(alt_cele["orderDraft"]["frequencyCode"], "QD")
        self.assertEqual(alt_cele["orderDraft"]["doseValue"], 200)
        self.assertEqual(alt_cele["orderDraft"]["doseUnit"], "mg")
        self.assertIn("膝骨关节炎", alt_cele["rationale"])

        # 2. Test Pediatric Aspirin -> Re-routing to Ibuprofen / Paracetamol
        res_ped = self.safety_auditor.audit_preflight_safety(
            medications=["阿司匹林肠溶片 100mg qd"],
            patient_context={"age": 6, "gender": "男", "diagnosis": "急性上呼吸道感染高热"}
        )
        self.assertFalse(res_ped["canPrescribe"])
        ped_alert = next((a for a in res_ped["allAlerts"] if a.get("ruleId") == "RULE-PEDIATRIC-ASPIRIN"), None)
        self.assertIsNotNone(ped_alert)
        self.assertTrue(len(ped_alert["alternatives"]) >= 2)
        alt_names = [a["name"] for a in ped_alert["alternatives"]]
        self.assertTrue(any("布洛芬" in n for n in alt_names))
        self.assertTrue(any("对乙酰氨基酚" in n for n in alt_names))

        # 3. Test Dual RAS Blockade -> Re-routing to CCB (Amlodipine)
        res_ras = self.safety_auditor.audit_preflight_safety(
            medications=["马来酸依那普利片 10mg qd", "缬沙坦胶囊 80mg qd"],
            patient_context={"age": 58, "gender": "男", "diagnosis": "原发性高血压"}
        )
        self.assertFalse(res_ras["canPrescribe"])
        ras_alert = next((a for a in res_ras["allAlerts"] if a.get("ruleId") == "RULE-SAFETY-RAS-DUAL"), None)
        self.assertIsNotNone(ras_alert)
        self.assertTrue(len(ras_alert["alternatives"]) >= 1)
        self.assertEqual(ras_alert["alternatives"][0]["name"], "苯磺酸氨氯地平片")

        # 4. Verify top-level aggregated alternatives
        self.assertTrue(len(res_ras["alternatives"]) >= 1)


if __name__ == "__main__":
    unittest.main()

"""
Unit Tests for Clinical Calculator Micro-Engine in Medical LLM Wiki.
"""

import unittest
from tools.cdss.calculators import ClinicalCalculatorRegistry


class TestClinicalCalculators(unittest.TestCase):

    def test_cha2ds2_vasc_high_risk_male(self):
        """Test male patient with CHF, HTN, DM, Age 68 -> Score: 1+1+1+1 = 4 -> HIGH."""
        params = {
            "age": 68,
            "gender": "男",
            "chf": True,
            "htn": True,
            "dm": True,
        }
        res = ClinicalCalculatorRegistry.calculate("cha2ds2_vasc", params)
        self.assertEqual(res["score"], 4)
        self.assertEqual(res["riskLevel"], "HIGH")
        self.assertIn("强烈推荐长期口服抗凝药物", res["recommendation"])

    def test_cha2ds2_vasc_low_risk_female(self):
        """Test female patient age 25 with no comorbidities -> Score: 1 (Female only) -> LOW."""
        params = {
            "age": 25,
            "gender": "女",
        }
        res = ClinicalCalculatorRegistry.calculate("cha2ds2_vasc", params)
        self.assertEqual(res["score"], 1)
        self.assertEqual(res["riskLevel"], "LOW")
        self.assertIn("不建议口服抗凝", res["recommendation"])

    def test_has_bled_high_bleeding_risk(self):
        """Test patient with SBP>160, Renal disease, Age 72, on Aspirin -> Score: 1+1+1+1 = 4 -> HIGH."""
        params = {
            "age": 72,
            "sbp_gt_160": True,
            "renal_disease": True,
            "antiplatelet": True,
        }
        res = ClinicalCalculatorRegistry.calculate("has_bled", params)
        self.assertEqual(res["score"], 4)
        self.assertEqual(res["riskLevel"], "HIGH_BLEEDING_RISK")
        self.assertIn("出血高风险", res["recommendation"])

    def test_curb_65_severe_pneumonia(self):
        """Test elderly patient with confusion, BUN 9.5, RR 32, Age 70 -> Score: 4 -> HIGH (ICU/Inpatient)."""
        params = {
            "age": 70,
            "confusion": True,
            "bun": 9.5,
            "rr": 32,
            "sbp": 110,
            "dbp": 70,
        }
        res = ClinicalCalculatorRegistry.calculate("curb_65", params)
        self.assertEqual(res["score"], 4)
        self.assertEqual(res["severity"], "HIGH")
        self.assertIn("评估ICU收治指征", res["disposition"])

    def test_centor_mcisaac(self):
        """Test 10yo child with exudate, tender nodes, fever 39C, no cough -> Score: 1+1+1+1 +1(age) = 5 -> >50%."""
        params = {
            "age": 10,
            "tonsil_exudate": True,
            "tender_cervical_nodes": True,
            "temp": 39.2,
            "no_cough": True,
        }
        res = ClinicalCalculatorRegistry.calculate("centor", params)
        self.assertEqual(res["score"], 5)
        self.assertEqual(res["strepProbability"], "> 50%")
        self.assertIn("阿莫西林足量满10天", res["recommendation"])

    def test_egfr_ckd_epi_and_cockcroft_gault(self):
        """Test 65yo male, Scr 180 μmol/L, weight 70kg -> severe CKD."""
        params = {
            "age": 65,
            "gender": "男",
            "scr": 180.0,  # μmol/L
            "weight": 70.0,
        }
        res = ClinicalCalculatorRegistry.calculate("renal_clearance", params)
        egfr = res["egfr"]
        crcl = res["crcl"]

        self.assertLess(egfr["eGFR"], 45.0)
        self.assertIn("CKD G3b", egfr["ckdStage"])
        self.assertTrue(any("二甲双胍" in a for a in egfr["drugAdjustments"]))
        self.assertGreater(crcl["crcl"], 0)
        self.assertEqual(crcl["unit"], "mL/min")

    def test_child_pugh_cirrhosis(self):
        """Test Child-Pugh Grade B calculation."""
        params = {
            "bili": 40.0,  # 34-51 -> 2
            "alb": 32.0,   # 28-35 -> 2
            "inr": 1.5,    # <1.7 -> 1
            "ascites": "mild",  # -> 2
            "encephalopathy": "none",  # -> 1
        }
        res = ClinicalCalculatorRegistry.calculate("child_pugh", params)
        self.assertEqual(res["score"], 8)
        self.assertEqual(res["grade"], "B 级")
        self.assertIn("肝功能显著受损", res["prognosis"])

    def test_pediatric_fluid_deficit(self):
        """Test 15kg child with moderate dehydration."""
        params = {
            "weight_kg": 15.0,
            "dehydration": "moderate",
        }
        res = ClinicalCalculatorRegistry.calculate("pediatric_fluid", params)
        # Holliday-Segar: 10*100 + 5*50 = 1250 ml
        self.assertEqual(res["maintenance24h_ml"], 1250.0)
        # Deficit: 15 * 80 = 1200 ml
        self.assertEqual(res["deficitVolume_ml"], 1200.0)
        self.assertEqual(res["estimated24hTotal_ml"], 2450.0)
        self.assertIn("ORS-III", res["rehydrationPlan"])


if __name__ == "__main__":
    unittest.main()

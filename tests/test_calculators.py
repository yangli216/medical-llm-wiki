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

    def test_alvarado_appendicitis_risk(self):
        """Test Alvarado score: RLQ tenderness (2) + Leukocytosis (2) + Migration (1) -> 5 (Moderate)."""
        res = ClinicalCalculatorRegistry.calculate("alvarado", {
            "migratory_pain": True,
            "rlq_tenderness": True,
            "wbc": 11.2,
        })
        self.assertEqual(res["score"], 5)
        self.assertIn("中危", res["riskStratum"])
        self.assertIn("严禁盲目开具强效麻醉镇痛药", res["recommendation"])

    def test_abcd2_tia_stroke_risk(self):
        """Test ABCD2 score: Age 65 (1) + SBP 150 (1) + Unilateral weakness (2) + 40min (1) + DM (1) -> 6 (High)."""
        res = ClinicalCalculatorRegistry.calculate("abcd2", {
            "age": 65,
            "sbp": 150,
            "clinical_features": "unilateral_weakness",
            "duration_minutes": 40,
            "diabetes": True,
        })
        self.assertEqual(res["score"], 6)
        self.assertIn("高危", res["riskStratum"])
        self.assertIn("卒中单元", res["recommendation"])

    def test_bmi_obesity_normal_weight(self):
        """Test normal weight adult (Height 175cm, Weight 68kg -> BMI 22.2) -> Normal, no pharmacotherapy."""
        res = ClinicalCalculatorRegistry.calculate("bmi_obesity", {
            "height": 175,
            "weight": 68,
            "waist": 80,
            "gender": "男",
        })
        self.assertEqual(res["bmi"], 22.2)
        self.assertEqual(res["category"], "NORMAL")
        self.assertFalse(res["central_obesity"])
        self.assertFalse(res["pharmacotherapy_indicated"])
        self.assertIn("严禁以非医学减重目的开具处方减重药", res["recommendation"])

    def test_bmi_obesity_overweight_with_comorbidity(self):
        """Test overweight with hypertension (Height 170cm, Weight 76kg -> BMI 26.3) -> Overweight, pharmacotherapy eligible."""
        res = ClinicalCalculatorRegistry.calculate("bmi", {
            "height": 170,
            "weight": 76,
            "waist": 92,
            "gender": "男",
            "htn": True,
        })
        self.assertEqual(res["bmi"], 26.3)
        self.assertEqual(res["category"], "OVERWEIGHT")
        self.assertTrue(res["central_obesity"])
        self.assertTrue(res["pharmacotherapy_indicated"])
        self.assertIn("奥利司他或GLP-1RA药物", res["recommendation"])

    def test_bmi_obesity_class_2_with_surgery_indication(self):
        """Test Class 2 obesity with diabetes (Height 165cm, Weight 92kg -> BMI 33.8) -> Surgery eligible."""
        res = ClinicalCalculatorRegistry.calculate("bmi_obesity", {
            "height": 165,
            "weight": 92,
            "waist": 102,
            "gender": "女",
            "dm": True,
        })
        self.assertEqual(res["bmi"], 33.8)
        self.assertEqual(res["category"], "OBESE")
        self.assertEqual(res["severity"], "CLASS_2")
        self.assertTrue(res["surgery_indicated"])
        self.assertIn("减重与代谢外科手术", res["recommendation"])

    def test_act_score_controlled(self):
        """Test ACT score: all 5s -> Score 25 -> CONTROLLED."""
        res = ClinicalCalculatorRegistry.calculate("act", {
            "q1": 5, "q2": 5, "q3": 5, "q4": 5, "q5": 5,
        })
        self.assertEqual(res["score"], 25)
        self.assertEqual(res["controlStatus"], "CONTROLLED")
        self.assertIn("完全控制", res["controlStatus_cn"])
        self.assertIn("梯度降级", res["recommendation"])

    def test_act_score_uncontrolled(self):
        """Test ACT score: 2+3+2+2+3 = 12 (<20) -> UNCONTROLLED."""
        res = ClinicalCalculatorRegistry.calculate("act_score", {
            "activity_limitation": 2,
            "shortness_of_breath": 3,
            "night_waking": 2,
            "reliever_usage": 2,
            "self_assessment": 3,
        })
        self.assertEqual(res["score"], 12)
        self.assertEqual(res["controlStatus"], "UNCONTROLLED")
        self.assertIn("未控制", res["controlStatus_cn"])
        self.assertIn("向上提升 1 级", res["recommendation"])

    def test_ganzoni_iron_deficit_moderate_anemia(self):
        """
        Test Ganzoni formula: Weight 60kg, Hb 70 g/L (7.0 g/dL), Target 15.0 g/dL.
        Deficit = 60 * (15.0 - 7.0) * 2.4 + 500 = 1152 + 500 = 1652.0 mg.
        Sucrose 100mg ampoules: ceil(1652 / 100) = 17.
        FCM 500mg vials: ceil(1652 / 500) = 4.
        """
        res = ClinicalCalculatorRegistry.calculate("ganzoni_iron", {
            "weight": 60,
            "hb": 70,
            "target_hb": 150,
        })
        self.assertEqual(res["totalDeficitMg"], 1652.0)
        self.assertEqual(res["anemiaSeverity"], "MODERATE")
        self.assertEqual(res["anemiaSeverity_cn"], "中度贫血")
        self.assertEqual(res["dosingEquivalents"]["iron_sucrose_100mg_ampoules"], 17)
        self.assertEqual(res["dosingEquivalents"]["ferric_carboxymaltose_500mg_vials"], 4)
        self.assertIn("Ganzoni 公式", res["recommendation"])
        self.assertIn("蔗糖铁注射液", res["recommendation"])

    def test_burch_wartofsky_thyroid_storm_crisis(self):
        """
        Test BWPS Thyroid Storm:
        Temp 39.6C -> 25
        CNS agitation -> 10
        GI diarrhea -> 10
        HR 145 bpm -> 25
        AF present -> 10
        Precipitating infection -> 10
        Total Score: 25 + 10 + 10 + 25 + 10 + 10 = 90 (>= 45) -> THYROID_STORM.
        """
        res = ClinicalCalculatorRegistry.calculate("bwps", {
            "temp": 39.6,
            "cns_effects": "烦躁激惹",
            "gi_dysfunction": "腹泻恶心",
            "hr": 145,
            "af": True,
            "precipitating_event": True,
        })
        self.assertEqual(res["score"], 90)
        self.assertEqual(res["stormStatus"], "THYROID_STORM")
        self.assertIn("甲状腺危象", res["stormStatus_cn"])
        self.assertIn("丙硫氧嘧啶", res["recommendation"])
        self.assertIn("重症监护室", res["recommendation"])

    def test_burch_wartofsky_thyroid_storm_unlikely(self):
        """Test BWPS: Normal vitals -> Score 0 (< 25) -> UNLIKELY."""
        res = ClinicalCalculatorRegistry.calculate("burch_wartofsky", {
            "temp": 36.8,
            "hr": 78,
        })
        self.assertEqual(res["score"], 0)
        self.assertEqual(res["stormStatus"], "UNLIKELY")
        self.assertIn("危象可能性小", res["stormStatus_cn"])


if __name__ == "__main__":
    unittest.main()

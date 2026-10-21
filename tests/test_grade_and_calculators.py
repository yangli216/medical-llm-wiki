import json
import unittest
from pathlib import Path
from tools.cdss.calculators import ClinicalCalculatorRegistry
from tools.cdss.rule_evaluator import RuleEvaluator
from tools.cdss.safety_auditor import ComprehensiveSafetyAuditor
from tools.linter.authority_auditor import AuthorityAuditor


class TestGradeAndClinicalCalculators(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent

    def test_wells_pe_calculator(self):
        """测试 Wells 肺栓塞量表高危与低危两分法决策逻辑"""
        # 1. 高危案例: DVT症状(+3) + PE最可能(+3) + 心率110(+1.5) = 7.5分 (>4分)
        high_res = ClinicalCalculatorRegistry.calculate("wells_pe", {
            "dvt_signs": True,
            "pe_most_likely": True,
            "hr": 110,
        })
        self.assertEqual(high_res["calculator"], "Wells PE Score")
        self.assertEqual(high_res["score"], 7.5)
        self.assertTrue(high_res["peLikely"])
        self.assertIn("CTPA", high_res["recommendation"])
        self.assertEqual(high_res["grade"], "1A")

        # 2. 低危案例: 单纯咯血(+1) = 1.0分 (≤4分)
        low_res = ClinicalCalculatorRegistry.calculate("wells", {
            "hemoptysis": True,
            "hr": 80,
        })
        self.assertEqual(low_res["score"], 1.0)
        self.assertFalse(low_res["peLikely"])
        self.assertIn("D-二聚体", low_res["recommendation"])

    def test_mmrc_copd_calculator(self):
        """测试 mMRC 呼吸困难分级与 GOLD A/B/E 分组阶梯决策"""
        # 1. 频繁加重患者 -> E组
        e_res = ClinicalCalculatorRegistry.calculate("mmrc", {
            "grade": 1,
            "exacerbations_last_year": 2,
            "eos_count": 350,
        })
        self.assertIn("E 组", e_res["goldGroup"])
        self.assertIn("三联吸入制剂", e_res["treatmentRecommendation"])

        # 2. mMRC 2级无加重史 -> B组
        b_res = ClinicalCalculatorRegistry.calculate("mmrc", {
            "grade": 2,
            "exacerbations_last_year": 0,
        })
        self.assertIn("B 组", b_res["goldGroup"])
        self.assertIn("LABA + LAMA", b_res["treatmentRecommendation"])

        # 3. mMRC 0级轻症 -> A组
        a_res = ClinicalCalculatorRegistry.calculate("mmrc", {
            "grade": 0,
            "exacerbations_last_year": 0,
        })
        self.assertIn("A 组", a_res["goldGroup"])

    def test_crb_65_pneumonia_calculator(self):
        """测试 CRB-65 门诊快速肺炎评分逻辑"""
        # 0分: 低危门诊
        res0 = ClinicalCalculatorRegistry.calculate("crb_65", {
            "age": 45,
            "rr": 20,
            "sbp": 120,
            "dbp": 80,
        })
        self.assertEqual(res0["score"], 0)
        self.assertIn("门诊口服", res0["triageRecommendation"])

        # 3分: 高危ICU预警 (年龄70 + 呼吸32 + 低血压85/55)
        res3 = ClinicalCalculatorRegistry.calculate("crb_65", {
            "age": 70,
            "rr": 32,
            "sbp": 85,
            "dbp": 55,
        })
        self.assertEqual(res3["score"], 3)
        self.assertIn("ICU", res3["triageRecommendation"])

    def test_safety_rules_100_percent_grade_coverage(self):
        """验证所有 45 条生产级 CDSS 规则均已注入 GRADE 分级字段"""
        rules_path = self.root_dir / "rules" / "clinical_safety_rules.json"
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        rules = data["rules"]
        self.assertGreaterEqual(len(rules), 45)

        for r in rules:
            self.assertIn("grade", r, f"规则 {r['id']} 缺失 grade 属性")
            self.assertIn(r["grade"], ["1A", "1B", "1C", "2A", "2B", "2C"])
            self.assertIn("evidence_level", r, f"规则 {r['id']} 缺失 evidence_level 属性")

    def test_cdss_auditor_outputs_grade(self):
        """测试安全审查引擎触发阻断时能透传 GRADE 等级"""
        evaluator = RuleEvaluator()
        # 触发双重 RAS 阻断 (ACEI + ARB)
        alerts = evaluator.evaluate_clinical_prescription(["依那普利", "缬沙坦"], {})
        self.assertGreaterEqual(len(alerts), 1)
        target = next((a for a in alerts if a["ruleId"] == "RULE-SAFETY-RAS-DUAL"), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["grade"], "1A")
        self.assertIn("强推荐", target["evidenceLevel"])

    def test_authority_whitepaper_reflects_p1_advancements(self):
        """测试权威性审计白皮书完整体现 GRADE 与临床量表覆盖度"""
        auditor = AuthorityAuditor(self.root_dir)
        res = auditor.audit()
        self.assertEqual(res["safetyRules"]["grade_coverage_ratio"], 1.0)
        self.assertEqual(res["calculators"]["totalCalculators"], 12)
        self.assertEqual(res["calculators"]["coverage_ratio"], 1.0)
        self.assertIsNone(res["credibilityScore"])
        self.assertFalse(res["quality"]["clinicalReady"])
        self.assertEqual(res["grade"], "未完成来源核验与临床审核")


if __name__ == "__main__":
    unittest.main()

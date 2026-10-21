"""
Unit and Integration Tests for P3.1, P3.2 & P3.3 Hospital In-Consultation CDSS & Wiki Upgrades:
1. Dynamic organ parameters (Child-Pugh hepatic grading, serum K+ hyperkalemia, nested HIS/EMR labs)
2. TCM active / hidden Western / toxic component overlap decomposition
3. Safe Alternative Re-routing Filter (dead-loop contraindication prevention)
4. 100% Alternative coverage across all 45 clinical safety rules & all 63 monograph rules (108 rules total)
5. Zero-manual-input clinical calculator EMR hydration & minimal follow-up prompts
6. Cross-layer semantic Linter checks on all 108 CDSS & Monograph rules & provenance
7. P3.3 CdssEngine & Live HTTP/OpenAI Gateway & Workstation UI integration
"""

import json
import socket
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from tools.cdss.parameter_normalizer import ClinicalParameterNormalizer
from tools.cdss.safety_auditor import ComprehensiveSafetyAuditor
from tools.cdss.drug_checker import DrugContraindicationAuditor
from tools.cdss.calculators import ClinicalCalculatorRegistry
from tools.cdss.engine import CdssEngine
from tools.linter.linter import WikiLinter
from tools.linter.authority_auditor import AuthorityAuditor
from tools.server.app import run_server


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestP31HospitalCdssUpgrades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.safety_auditor = ComprehensiveSafetyAuditor(cls.root_dir)
        cls.monograph_auditor = DrugContraindicationAuditor(repo=cls.safety_auditor.repo, root_dir=cls.root_dir)
        cls.cdss_engine = CdssEngine(cls.root_dir)
        cls.linter = WikiLinter(cls.root_dir)
        cls.authority_auditor = AuthorityAuditor(cls.root_dir)

    def test_01_nested_emr_labs_and_dynamic_potassium_child_pugh(self):
        """测试嵌套 HIS/EMR 化验报文自动解包、血钾高钾血症动态拦截与 Child-Pugh 肝功能推导"""
        emr_payload = {
            "patient": {"age": 62, "gender": "男", "weight": 70},
            "labs": {
                "scr": 110,
                "k": 5.6,          # 血钾 5.6 mmol/L -> 自动推导高钾血症
                "tbil": 55.0,      # 总胆红素 > 51 -> 3分
                "albumin": 26.0,   # 白蛋白 < 28 -> 3分
                "inr": 2.4,        # INR > 2.3 -> 3分 -> Child-Pugh C级
            },
            "vitals": {"sbp": 168, "dbp": 96, "hr": 108},
        }
        norm = ClinicalParameterNormalizer.normalize_patient(emr_payload)
        self.assertTrue(norm["has_hyperkalemia"])
        self.assertTrue(norm["severe_hyperkalemia"])
        self.assertEqual(norm["child_pugh_grade"], "C")
        self.assertTrue(norm["severe_liver_injury"])
        self.assertIn("高钾血症", norm["normalized_diagnoses"])

        res = self.safety_auditor.audit_preflight_safety(
            medications=["螺内酯片 20mg qd"],
            patient_context=emr_payload,
        )
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["alertTier"], "HARD_STOP")
        hk_alert = next((a for a in res["allAlerts"] if a.get("ruleId") == "RULE-HYPERKALEMIA-K-SPARING-STOP"), None)
        self.assertIsNotNone(hk_alert)
        self.assertEqual(hk_alert["alertTier"], "HARD_STOP")
        self.assertTrue(any("环硅酸锆钠散" in alt["name"] for alt in hk_alert["alternatives"]))

    def test_02_tcm_component_overlap_decomposition(self):
        """测试中成药活性成分与隐含西药/毒性生物碱成分拆解重叠拦截"""
        res_ephedrine = self.safety_auditor.audit_preflight_safety(
            medications=["连花清瘟胶囊 1.4g tid", "急支糖浆 20ml tid"],
            patient_context={"age": 60, "gender": "男", "sbp": 170, "hr": 105},
        )
        rule_ids = [a.get("ruleId") for a in res_ephedrine["allAlerts"]]
        self.assertIn("RULE-TCM-COMPONENT-EPHEDRINE-OVERLAP", rule_ids)
        self.assertIn("RULE-TCM-COMPONENT-EPHEDRINE-CV", rule_ids)

        res_toxic = self.safety_auditor.audit_preflight_safety(
            medications=["腰痛宁胶囊 4粒 qn", "附子理中丸 9g bid"],
            patient_context={"age": 55, "gender": "男"},
        )
        self.assertFalse(res_toxic["canPrescribe"])
        self.assertTrue(any(a.get("ruleId") == "RULE-TCM-COMPONENT-TOXIC-ALKALOID" for a in res_toxic["allAlerts"]))

        res_anthra = self.safety_auditor.audit_preflight_safety(
            medications=["牛黄解毒片 3片 tid", "黄连上清片 4片 bid"],
            patient_context={"age": 40, "gender": "女"},
        )
        self.assertTrue(any(a.get("ruleId") == "RULE-TCM-COMPONENT-ANTHRAQUINONE" for a in res_anthra["allAlerts"]))

    def test_03_safe_alternative_dead_loop_filter(self):
        """测试平替方案安全死循环过滤器：自动剔除触发患者自身禁忌的备选平替药"""
        res = self.safety_auditor.audit_preflight_safety(
            medications=["地塞米松片 0.75mg qd"],
            patient_context={
                "age": 72,
                "gender": "女",
                "is_koa": True,
                "egfr": 20.0,
                "conditions": ["双膝骨关节炎", "活动性消化道大出血"],
            },
        )
        koa_alert = next((a for a in res["allAlerts"] if a.get("ruleId") == "RULE-KOA-SYSTEMIC-STEROID"), None)
        self.assertIsNotNone(koa_alert)
        safe_alt_names = [alt["name"] for alt in koa_alert["alternatives"]]
        self.assertNotIn("塞来昔布胶囊", safe_alt_names)
        self.assertIn("双氯芬酸钠凝胶贴膏", safe_alt_names)
        self.assertGreaterEqual(len(res["filteredUnsafeAlternatives"]), 1)

    def test_04_zero_manual_input_calculator_emr_hydration(self):
        """测试零手动输入临床量表 EMR 自动参数提取与缺省项最小化追问"""
        emr_af = {
            "age": 76,
            "gender": "女",
            "chiefComplaint": "反复心悸胸闷2年，加重3天",
            "history": "既往有高血压病史10年，2型糖尿病史5年，否认脑卒中及心力衰竭病史",
            "diagnosis": "心房颤动",
        }
        calc_res = ClinicalCalculatorRegistry.calculate_from_emr("cha2ds2_vasc", emr_af)
        self.assertEqual(calc_res["score"], 5)
        self.assertEqual(calc_res["riskLevel"], "HIGH")
        self.assertIn("htn", calc_res["emrHydration"]["autoExtractedFields"])
        self.assertIn("dm", calc_res["emrHydration"]["autoExtractedFields"])
        self.assertLessEqual(len(calc_res["emrHydration"]["minimalFollowUpQuestions"]), 1)

        emr_af["scr"] = 135
        emr_af["weight"] = 60
        recs = ClinicalCalculatorRegistry.recommend_calculators_for_encounter(emr_af)
        calc_names = [r["calculator"] for r in recs]
        self.assertIn("CHA2DS2-VASc", calc_names)
        self.assertIn("HAS-BLED", calc_names)

    def test_05_semantic_linter_cdss_rules_100_percent_clean(self):
        """测试升级后的 WikiLinter 对 45 条宏观规则 + 63 条微观说明书规则 (共108条) 的跨层溯源与自洽性校验"""
        report = self.linter.run_all_checks()
        self.assertTrue(report["is_healthy"], f"Linter issues found: {report}")
        self.assertEqual(report["cdss_rule_issue_count"], 0)

    def test_06_all_63_monograph_rules_have_alternatives_and_grade(self):
        """验证 rules/monograph_rules.json 全部 63 条微观说明书规则 100% 注入合规平替方案与 GRADE 等级"""
        mr_path = self.root_dir / "rules" / "monograph_rules.json"
        data = json.loads(mr_path.read_text(encoding="utf-8"))
        mrules = data["rules"] if isinstance(data, dict) else data
        self.assertGreaterEqual(len(mrules), 63)

        for r in mrules:
            rid = r["id"]
            self.assertIn("grade", r, f"说明书规则 {rid} 缺失 grade")
            self.assertIn("alert_tier", r, f"说明书规则 {rid} 缺失 alert_tier")
            self.assertIn("alternatives", r, f"说明书规则 {rid} 缺失 alternatives")
            self.assertGreaterEqual(len(r["alternatives"]), 1, f"说明书规则 {rid} 的 alternatives 为空")
            for alt in r["alternatives"]:
                self.assertTrue(alt.get("name"), f"{rid} 平替缺失 name")
                self.assertTrue(alt.get("orderDraft"), f"{rid} 平替缺失 orderDraft")
                self.assertTrue(alt.get("rationale"), f"{rid} 平替缺失 rationale")
                self.assertTrue(alt.get("sourceGuideline"), f"{rid} 平替缺失 sourceGuideline")

        res_rosuva = self.monograph_auditor.audit("瑞舒伐他汀钙片", {"age": 68, "egfr": 22.0})
        self.assertFalse(res_rosuva["canPrescribe"])
        self.assertEqual(res_rosuva["alertTier"], "HARD_STOP")
        self.assertTrue(any("阿托伐他汀钙片" in alt["name"] for alt in res_rosuva["alternatives"]))

        auth_res = self.authority_auditor.audit()
        self.assertGreaterEqual(auth_res["safetyRules"]["monographRulesCount"], 63)
        self.assertEqual(auth_res["safetyRules"]["monographAlternativesCount"], auth_res["safetyRules"]["monographRulesCount"])
        self.assertGreaterEqual(auth_res["safetyRules"]["combinedTotalRules"], 108)
        self.assertEqual(auth_res["safetyRules"]["combinedAlternativesCount"], auth_res["safetyRules"]["combinedTotalRules"])

    def test_07_cdss_engine_p3_3_compile_and_audit(self):
        """测试 P3.3 CdssEngine.compile_rhn_plan 与 audit_prescription 全栈契约对齐"""
        plan = self.cdss_engine.compile_rhn_plan(
            query_or_id="PROT-TONSIL-031",
            patient_context={"age": 12, "gender": "男", "temp": 39.2, "tonsil_exudate": True, "no_cough": True, "scr": 65},
        )
        self.assertTrue(plan["success"])
        self.assertIn("recommendedCalculators", plan)
        calc_names = [c["calculator"] for c in plan["recommendedCalculators"]]
        self.assertIn("Centor-McIsaac", calc_names)

        audit = self.cdss_engine.audit_prescription(
            medications=["地塞米松片 0.75mg qd", "腰痛宁胶囊 4粒 qn", "附子理中丸 9g bid"],
            patient_profile={
                "age": 72,
                "gender": "女",
                "is_koa": True,
                "egfr": 20.0,
                "conditions": ["双膝骨关节炎", "活动性消化道大出血"],
            },
        )
        self.assertFalse(audit["canPrescribe"])
        self.assertEqual(audit["alertTier"], "HARD_STOP")
        self.assertIn("alertTierCounts", audit)
        self.assertGreaterEqual(audit["alertTierCounts"]["HARD_STOP"], 2)
        self.assertIn("alternatives", audit)
        self.assertIn("filteredUnsafeAlternatives", audit)
        self.assertGreaterEqual(len(audit["filteredUnsafeAlternatives"]), 1)

    def test_08_p3_3_live_http_endpoints_and_openai_gateway(self):
        """测试 P3.3 实时 HTTP 网关接口 (/api/cdss/calculators/hydrate, /recommend, /audit, /v1/chat/completions)"""
        port = _find_free_port()
        server_thread = threading.Thread(
            target=run_server,
            kwargs={"port": port},
            daemon=True,
        )
        server_thread.start()
        base_url = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        for _ in range(30):
            try:
                with opener.open(f"{base_url}/api/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.1)

        def post_json(path: str, payload: dict) -> dict:
            req = urllib.request.Request(
                f"{base_url}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with opener.open(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))

        # 1. Verify /api/health exposes P3.3 metadata
        with opener.open(f"{base_url}/api/health", timeout=5) as resp:
            health = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(health["p3Version"], "3.3.0")
        self.assertGreaterEqual(health["monographRules"], 63)
        self.assertGreaterEqual(health["combinedSafetyRules"], 108)

        # 2. Verify POST /api/cdss/calculators/hydrate
        hyd_res = post_json("/api/cdss/calculators/hydrate", {
            "calculator": "cha2ds2_vasc",
            "patientContext": {
                "age": 76,
                "gender": "女",
                "history": "高血压10年，糖尿病5年，否认脑卒中及心衰",
                "diagnosis": "心房颤动",
            },
        })
        self.assertTrue(hyd_res["success"])
        self.assertEqual(hyd_res["calculation"]["score"], 5)
        self.assertIn("emrHydration", hyd_res["calculation"])

        # 3. Verify POST /api/cdss/calculators/recommend
        rec_res = post_json("/api/cdss/calculators/recommend", {
            "patientContext": {
                "age": 76,
                "gender": "女",
                "scr": 140,
                "history": "高血压10年，糖尿病5年",
                "diagnosis": "心房颤动",
            },
        })
        self.assertTrue(rec_res["success"])
        self.assertGreaterEqual(rec_res["count"], 2)

        # 4. Verify POST /api/cdss/audit returns P3.3 fields
        audit_res = post_json("/api/cdss/audit", {
            "medications": ["螺内酯片 20mg qd"],
            "patient": {"age": 65, "gender": "男", "labs": {"k": 5.7, "scr": 120}},
        })
        self.assertFalse(audit_res["canPrescribe"])
        self.assertEqual(audit_res["alertTier"], "HARD_STOP")
        self.assertTrue(any("环硅酸锆钠散" in a["name"] for a in audit_res["alternatives"]))

        # 5. Verify POST /v1/chat/completions (RECORD_DIAGNOSIS) includes recommendedCalculators & alertTier
        chat_res = post_json("/v1/chat/completions", {
            "model": "medical-cdss-wiki",
            "messages": [
                {"role": "system", "content": "你是一个在医疗卫生领域辅助临床医生的专业 AI 助手。"},
                {"role": "user", "content": json.dumps({
                    "generationStage": "RECORD_DIAGNOSIS",
                    "question": "患者心房颤动反复心悸胸闷3天",
                    "draft": {
                        "chiefComplaint": "心房颤动反复心悸胸闷3天",
                        "presentIllness": "既往高血压病史8年，糖尿病史3年",
                        "medications": [{"name": "盐酸二甲双胍片"}],
                        "systolic": 156,
                        "diastolic": 92,
                    },
                    "patient": {"age": 75, "gender": "男", "scr": 240},
                    "allergies": [],
                }, ensure_ascii=False)},
            ],
            "stream": False,
        })
        content = json.loads(chat_res["choices"][0]["message"]["content"])
        self.assertIn("recommendedCalculators", content)
        self.assertGreaterEqual(len(content["recommendedCalculators"]), 2)
        self.assertTrue(any(a.get("alertTier") == "HARD_STOP" for a in content["safetyAlerts"]))


if __name__ == "__main__":
    unittest.main()

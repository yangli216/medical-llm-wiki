"""
End-to-End Live Integration Test Suite for RHN (Outpatient Doctor Workstation) & Medical Knowledge Base.
Tests live HTTP endpoints (no mocking):
- OpenAI ChatCompletion protocol (/v1/chat/completions) for compilePlan and analyze
- SSE Streaming protocol (/v1/chat/completions with stream=true)
- Knowledge Gateway protocol (/api/knowledge/search) for PmphaiClinicalKnowledgeGateway
- Native REST Plan Compilation (/api/cdss/compile-rhn-plan)
- CDSS Preflight Prescription Auditing (/api/cdss/audit)
"""

import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import HTTPServer
from pathlib import Path
from tools.server.app import WikiHTTPHandler


TEST_PORT = 18099
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


class TestRhnLiveIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["no_proxy"] = "*"
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cls.server = HTTPServer(("127.0.0.1", TEST_PORT), WikiHTTPHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{BASE_URL}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with self.opener.open(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    def _get_json(self, path: str) -> dict:
        import urllib.parse
        quoted_path = urllib.parse.quote(path, safe="/:?=&")
        url = f"{BASE_URL}{quoted_path}"
        req = urllib.request.Request(url, method="GET")
        with self.opener.open(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    def test_01_health_and_models(self):
        """Verifies health check and OpenAI /v1/models endpoint."""
        health = self._get_json("/api/health")
        self.assertEqual(health["status"], "UP")
        self.assertEqual(health["version"], "1.9.0")
        self.assertEqual(health["protocols"], 35)
        self.assertEqual(health["rules"], 35)

        models = self._get_json("/v1/models")
        self.assertEqual(models["object"], "list")
        self.assertTrue(len(models["data"]) >= 1)
        self.assertEqual(models["data"][0]["id"], "medical-cdss-wiki")

    def test_02_openai_compile_plan_koa(self):
        """Verifies OpenAI ChatCompletion protocol for Knee Osteoarthritis PlanIntent compilation."""
        payload = {
            "model": "medical-cdss-wiki",
            "temperature": 0.1,
            "max_tokens": 3000,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "你是门诊临床诊疗方案编译器。"},
                {"role": "user", "content": json.dumps({
                    "mode": "INPUT",
                    "text": "膝骨关节炎",
                    "availablePlans": [],
                    "currentNarrative": "",
                    "revisionInstruction": "",
                }, ensure_ascii=False)}
            ],
            "stream": False,
        }
        res = self._post_json("/v1/chat/completions", payload)
        self.assertEqual(res["object"], "chat.completion")
        self.assertTrue(len(res["choices"]) > 0)
        content_str = res["choices"][0]["message"]["content"]
        plan_intent = json.loads(content_str)

        # Verify RHN PlanIntent contract
        self.assertIn("膝骨关节炎", plan_intent["name"])
        self.assertIn("M17.9", plan_intent["description"])
        note = plan_intent["noteTemplateContent"]
        for key in ["chiefComplaint", "presentIllness", "medicalHistory", "physicalExam", "healthEducation", "followUp"]:
            self.assertIn(key, note)
            self.assertTrue(len(note[key].strip()) > 10, f"Section {key} should have authentic content")
            # Strictly zero placeholders
            for forbidden in ["待询问", "待查体", "待填写", "需查/需记录"]:
                self.assertNotIn(forbidden, note[key])

        # Verify items logic
        items = plan_intent["items"]
        self.assertTrue(len(items) >= 4)
        self.assertLessEqual(len(items), 30)
        self.assertEqual(items[0]["kind"], "DIAGNOSIS")
        self.assertIn("膝骨关节炎", items[0]["name"])
        self.assertEqual(items[0]["origin"], "SUGGESTED")
        self.assertEqual(items[0]["sourceQuote"], "")  # Clean empty string as per RHN prompt

        # Verify medication items
        med_items = [it for it in items if it["kind"] == "MEDICATION"]
        self.assertTrue(len(med_items) >= 2)
        med_names = [m["name"] for m in med_items]
        self.assertTrue(any("塞来昔布" in n or "双氯芬酸" in n for n in med_names))

    def test_03_openai_compile_plan_streaming(self):
        """Verifies OpenAI ChatCompletion SSE streaming output for PlanIntent."""
        url = f"{BASE_URL}/v1/chat/completions"
        payload = {
            "model": "medical-cdss-wiki",
            "messages": [
                {"role": "system", "content": "你是门诊临床诊疗方案编译器。"},
                {"role": "user", "content": json.dumps({"mode": "INPUT", "text": "2型糖尿病"}, ensure_ascii=False)}
            ],
            "stream": True,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8", "Accept": "text/event-stream"},
            method="POST",
        )
        chunks = []
        with self.opener.open(req, timeout=10) as resp:
            for line in resp:
                decoded = line.decode("utf-8").strip()
                if decoded.startswith("data: "):
                    payload_part = decoded[6:]
                    if payload_part == "[DONE]":
                        break
                    chunk_obj = json.loads(payload_part)
                    delta = chunk_obj["choices"][0]["delta"].get("content", "")
                    chunks.append(delta)

        full_content = "".join(chunks)
        plan_intent = json.loads(full_content)
        self.assertIn("2型糖尿病", plan_intent["name"])
        self.assertIn("chiefComplaint", plan_intent["noteTemplateContent"])
        self.assertTrue(len(plan_intent["items"]) >= 4)

    def test_04_openai_analyze_record_diagnosis(self):
        """Verifies intelligent outpatient visit analysis and CDSS safety alerts."""
        payload = {
            "model": "medical-cdss-wiki",
            "messages": [
                {"role": "system", "content": "你是一个在医疗卫生领域辅助临床医生的专业 AI 助手。"},
                {"role": "user", "content": json.dumps({
                    "generationStage": "RECORD_DIAGNOSIS",
                    "question": "患者双膝关节隐痛6个月，加重1周",
                    "draft": {
                        "chiefComplaint": "双膝关节隐痛6个月",
                        "medications": [
                            {"name": "地塞米松片"},
                            {"name": "塞来昔布胶囊"},
                            {"name": "双氯芬酸钠缓释片"}
                        ],
                        "temperature": 36.6,
                        "systolic": 120,
                        "diastolic": 78
                    },
                    "patient": {
                        "age": 68,
                        "gender": "FEMALE",
                        "is_koa": True
                    },
                    "allergies": []
                }, ensure_ascii=False)}
            ],
            "stream": False,
        }
        res = self._post_json("/v1/chat/completions", payload)
        content_str = res["choices"][0]["message"]["content"]
        suggestion = json.loads(content_str)

        # Verify RecordDraft
        rec_draft = suggestion["recordDraft"]
        self.assertIsNotNone(rec_draft)
        self.assertEqual(rec_draft["systolic"], 120)
        self.assertEqual(rec_draft["diastolic"], 78)

        # Verify diagnosis candidates
        diag_candidates = suggestion["diagnosisCandidates"]
        self.assertTrue(len(diag_candidates) >= 1)
        self.assertEqual(diag_candidates[0]["code"], "M17.9")

        # Verify CDSS safety alerts triggered
        alerts = suggestion["safetyAlerts"]
        self.assertTrue(len(alerts) >= 2)
        alert_titles = [a["title"] for a in alerts]
        self.assertTrue(any("糖皮质激素" in t for t in alert_titles))
        self.assertTrue(any("非甾体抗炎药" in t or "NSAIDs" in t for t in alert_titles))

    def test_05_pmphai_knowledge_search_gateway(self):
        """Verifies PmphaiClinicalKnowledgeGateway ProviderResult[] protocol."""
        res = self._post_json("/api/knowledge/search", {"query": "高血压", "limit": 3})
        self.assertIsInstance(res, list)
        self.assertTrue(len(res) >= 1)
        first = res[0]
        self.assertIn("id", first)
        self.assertIn("name", first)
        self.assertIn("content", first)
        self.assertIn("score", first)
        self.assertIn("sourceInfo", first)
        self.assertIn("knowledgeLibName", first["sourceInfo"])

    def test_06_native_cdss_compile_and_order_draft(self):
        """Verifies native REST API compilation with realistic orderDraft specs."""
        res = self._post_json("/api/cdss/compile-rhn-plan", {"input": "PROT-KOA-032"})
        self.assertTrue(res["success"])
        recs = res["treatmentRecommendations"]
        self.assertTrue(len(recs) >= 3)

        # Check patch order draft
        patch_item = next(r for r in recs if "贴膏" in r["name"])
        od = patch_item["orderDraft"]
        self.assertIsNotNone(od)
        self.assertEqual(od["routeCode"], "外用")
        self.assertEqual(od["frequencyCode"], "QD")
        self.assertEqual(od["doseValue"], 1.0)
        self.assertEqual(od["durationValue"], 14)

    def test_07_cdss_prescription_safety_audit(self):
        """Verifies authoritative CDSS preflight rules (5 distinct severe clinical cases)."""
        # Case 1: KOA with systemic steroid
        audit1 = self._post_json("/api/cdss/audit", {
            "medications": ["地塞米松磷酸钠注射液"],
            "patient": {"is_koa": True}
        })
        self.assertFalse(audit1["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-KOA-SYSTEMIC-STEROID" for a in audit1["alerts"]))

        # Case 2: BPH with Anticholinergic drug
        audit2 = self._post_json("/api/cdss/audit", {
            "medications": ["阿托品片"],
            "patient": {"is_bph": True}
        })
        self.assertFalse(audit2["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-BPH-ANTICHOLINERGIC" for a in audit2["alerts"]))

        # Case 3: Rabies Grade III missing HRIG
        audit3 = self._post_json("/api/cdss/audit", {
            "medications": ["人用狂犬病疫苗(Vero细胞)"],
            "patient": {"history": "右下肢深部犬咬伤伴多处渗血，III级暴露"}
        })
        self.assertFalse(audit3["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-RABIES-III-PASSIVE-IMMUNITY" for a in audit3["alerts"]))

        # Case 4: Dual RAS Blockade
        audit4 = self._post_json("/api/cdss/audit", {
            "medications": ["缬沙坦胶囊", "马来酸依那普利片"]
        })
        self.assertFalse(audit4["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-SAFETY-RAS-DUAL" for a in audit4["alerts"]))

        # Case 5: Penicillin allergy with amoxicillin
        audit5 = self._post_json("/api/cdss/audit", {
            "medications": ["阿莫西林胶囊"],
            "patient": {"allergy": "青霉素过敏"}
        })
        self.assertFalse(audit5["is_safe"])
        self.assertTrue(any(a["ruleId"] == "RULE-ALLERGY-PENICILLIN" for a in audit5["alerts"]))

    def test_08_drug_inserts_api_endpoints(self):
        """Verifies /api/drugs, /api/drugs/<name>, and /api/drugs/check-contraindications live endpoints."""
        # 1. Test List all drugs
        all_drugs = self._get_json("/api/drugs")
        self.assertEqual(len(all_drugs), 100)
        self.assertTrue(any(d["genericName"] == "盐酸二甲双胍片" for d in all_drugs))
        self.assertTrue(any("沙库巴曲缬沙坦" in d["genericName"] for d in all_drugs))

        # 2. Test Category filter
        cvd_drugs = self._get_json("/api/drugs?category=心血管系统")
        self.assertEqual(len(cvd_drugs), 19)

        # 3. Test Detail lookup
        detail = self._get_json("/api/drugs/盐酸二甲双胍片")
        self.assertEqual(detail["id"], "盐酸二甲双胍片")
        self.assertIn("html", detail)
        self.assertIn("specialPopulations", detail)
        self.assertEqual(detail["atcCode"], "A10BA02")

        # 4. Test Contraindication Check (Nitroglycerin + Sildenafil DDI lethal block)
        audit_res = self._post_json("/api/drugs/check-contraindications", {
            "medications": ["硝酸甘油片", "枸橼酸西地那非片"],
            "patient": {"age": 60}
        })
        self.assertFalse(audit_res["canPrescribe"])
        self.assertEqual(audit_res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_NITRO_PDE5I" for a in audit_res["alerts"]))

        # 5. Test 2026 Essential Drug Check (Sacubitril/Valsartan + Enalapril 36h Washout)
        audit_arni = self._post_json("/api/drugs/check-contraindications", {
            "medications": ["沙库巴曲缬沙坦钠片", "马来酸依那普利片"],
            "patient": {"age": 65}
        })
        self.assertFalse(audit_arni["canPrescribe"])
        self.assertEqual(audit_arni["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_ARNI_ACEI_WASHOUT_36H" for a in audit_arni["alerts"]))


if __name__ == "__main__":
    unittest.main()

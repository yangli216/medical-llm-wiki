"""ChatApiMixin extracted from the HTTP entrypoint."""

import json
import re
import time
from typing import Any, Dict
from tools.cdss.calculators import ClinicalCalculatorRegistry
from tools.quality import audit_quality


class ChatApiMixin:
    def _handle_chat_completions(self, payload: Dict[str, Any]) -> None:
        """Adapts to OpenAI ChatCompletion protocol consumed by RHN OpenAiCompatibleClinicalAiModelGateway."""
        messages = payload.get("messages", [])
        model = payload.get("model", "medical-cdss-wiki")
        stream = bool(payload.get("stream", False))

        system_content = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        user_messages = [m.get("content", "") for m in messages if m.get("role") == "user"]
        last_user_content = user_messages[-1] if user_messages else ""

        u_obj = None
        for u_msg in reversed(user_messages):
            if isinstance(u_msg, str) and u_msg.strip().startswith("{"):
                try:
                    cand = json.loads(u_msg)
                    if isinstance(cand, dict) and ("text" in cand or "mode" in cand or "draft" in cand or "generationStage" in cand):
                        u_obj = cand
                        break
                except Exception:
                    pass

        is_plan_compile = (
            "PLAN_PROMPT" in system_content
            or "门诊临床诊疗方案编译器" in system_content
            or "noteTemplateContent" in system_content
            or (u_obj is not None and "text" in u_obj and "mode" in u_obj)
        )
        is_plan_match = "PLAN_MATCH" in system_content or "匹配院内已有的整体诊疗方案" in system_content
        is_clinical_suggest = (
            "SYSTEM_PROMPT" in system_content
            or "医疗卫生领域辅助临床医生" in system_content
            or (u_obj is not None and ("generationStage" in u_obj or "draft" in u_obj))
        )

        assistant_content = ""

        if is_plan_match:
            available_plans = (u_obj.get("availablePlans") if u_obj else []) or []
            recommended = []
            for p in available_plans[:3]:
                p_id = p.get("templateId") or p.get("id")
                p_name = p.get("name", "已有方案")
                recommended.append({
                    "templateId": p_id,
                    "rationale": f"基于就诊主诉与临床表现推荐核对已有标准化方案【{p_name}】",
                })
            assistant_content = json.dumps({"recommendedPlans": recommended}, ensure_ascii=False)

        elif is_plan_compile:
            query = ""
            available_plans = []
            if u_obj:
                query = u_obj.get("text", "")
                available_plans = u_obj.get("availablePlans", [])
            else:
                query = last_user_content

            res = self.cdss.compile_rhn_plan(query)
            if res.get("success"):
                plan_intent = res["planIntent"]
                matched_ref_id = None
                for ap in available_plans:
                    ap_name = ap.get("name", "")
                    if ap_name and (ap_name in plan_intent["name"] or plan_intent["name"] in ap_name):
                        matched_ref_id = ap.get("id") or ap.get("templateId")
                        break
                plan_intent["referenceTemplateId"] = matched_ref_id
                assistant_content = json.dumps(plan_intent, ensure_ascii=False)
            else:
                assistant_content = json.dumps({
                    "name": query.strip()[:20] if query else "未特指临床方案",
                    "description": "",
                    "noteTemplateContent": {
                        "chiefComplaint": "",
                        "presentIllness": "",
                        "medicalHistory": "",
                        "physicalExam": "",
                        "healthEducation": "",
                        "followUp": "",
                    },
                    "items": [],
                    "referenceTemplateId": None,
                }, ensure_ascii=False)

        elif is_clinical_suggest:
            ctx = u_obj or {}
            draft = ctx.get("draft") or {}
            question = ctx.get("question") or ""
            voice = ctx.get("voiceTranscript") or ""
            patient = ctx.get("patient") or {}
            allergies = ctx.get("allergies") or []

            medications_to_audit = []
            if draft.get("medications") and isinstance(draft["medications"], list):
                for m in draft["medications"]:
                    if isinstance(m, dict) and m.get("name"):
                        medications_to_audit.append(m["name"])
                    elif isinstance(m, str):
                        medications_to_audit.append(m)

            kw = draft.get("chiefComplaint") or question or voice or ""
            if not kw and draft.get("diagnoses") and isinstance(draft["diagnoses"], list):
                first_diag = draft["diagnoses"][0]
                kw = first_diag.get("display") or first_diag.get("code") or ""

            res = self.cdss.compile_rhn_plan(kw) if kw else None
            prot = self.cdss.repo.get(res["protocolId"]) if (res and res.get("success")) else None

            patient_profile = dict(patient)
            if allergies:
                patient_profile["allergies"] = " ".join([
                    a.get("substanceDisplay", "") for a in allergies if isinstance(a, dict)
                ])
            # Merge clinical draft vitals and text into patient_profile for dynamic inference
            if draft.get("systolic") is not None and "sbp" not in patient_profile:
                patient_profile["sbp"] = draft.get("systolic")
            if draft.get("diastolic") is not None and "dbp" not in patient_profile:
                patient_profile["dbp"] = draft.get("diastolic")
            if draft.get("pulseRate") is not None and "hr" not in patient_profile:
                patient_profile["hr"] = draft.get("pulseRate")
            if draft.get("respiratoryRate") is not None and "rr" not in patient_profile:
                patient_profile["rr"] = draft.get("respiratoryRate")
            if draft.get("temperature") is not None and "temp" not in patient_profile:
                patient_profile["temp"] = draft.get("temperature")
            if draft.get("weightKg") is not None and "weight" not in patient_profile:
                patient_profile["weight"] = draft.get("weightKg")
            for tk in ("chiefComplaint", "presentIllness", "medicalHistory", "physicalExam"):
                if draft.get(tk) and not patient_profile.get(tk):
                    patient_profile[tk] = draft.get(tk)
            if not patient_profile.get("diagnosis") and kw:
                patient_profile["diagnosis"] = kw

            # 1. Protocol-level prescription audit
            audit_res = self.cdss.audit_prescription(medications_to_audit, patient_profile)
            safety_alerts = []
            seen_alert_titles = set()
            for a in audit_res.get("alerts", []):
                safety_alerts.append({
                    "level": "CRITICAL" if a.get("severity") == "RED" else "WARNING",
                    "alertTier": a.get("alertTier", "HARD_STOP" if a.get("severity") == "RED" else "SOFT_NUDGE"),
                    "title": a.get("title", "处方安全预警"),
                    "detail": a.get("message", ""),
                    "alternatives": a.get("alternatives", []),
                })
                seen_alert_titles.add(a.get("title"))

            # 2. Monograph-level CDSS contraindication & DDI audit (covering 100 essential drugs)
            if medications_to_audit:
                drug_audit = self.drug_auditor.audit_prescription(medications_to_audit, patient_profile)
                for da in drug_audit.get("alerts", []):
                    title = da.get("title", "药品说明书安全阻断")
                    if title not in seen_alert_titles:
                        safety_alerts.append({
                            "level": "CRITICAL" if da.get("level") == "BLOCK" else "WARNING",
                            "alertTier": da.get("alertTier", "HARD_STOP" if da.get("level") == "BLOCK" else "SOFT_NUDGE"),
                            "title": title,
                            "detail": f"{da.get('reason', '')} (依据：{da.get('evidence', '')})",
                            "alternatives": da.get("alternatives", []),
                        })
                        seen_alert_titles.add(title)

            encounter_calculators = ClinicalCalculatorRegistry.recommend_calculators_for_encounter({
                **patient_profile,
                "chiefComplaint": str(draft.get("chiefComplaint") or question or ""),
                "presentIllness": str(draft.get("presentIllness") or ""),
                "diagnosis": str(kw or question or "")
            })

            if prot:
                rec_draft = {
                    "chiefComplaint": draft.get("chiefComplaint") or prot.note_template.get("chiefComplaint", ""),
                    "presentIllness": draft.get("presentIllness") or prot.note_template.get("presentIllness", ""),
                    "medicalHistory": draft.get("medicalHistory") or prot.note_template.get("medicalHistory", ""),
                    "physicalExam": draft.get("physicalExam") or prot.note_template.get("physicalExam", ""),
                    "treatmentPlan": None,
                    "healthEducation": draft.get("healthEducation") or prot.note_template.get("healthEducation", ""),
                    "followUp": draft.get("followUp") or prot.note_template.get("followUp", ""),
                    "systolic": draft.get("systolic"),
                    "diastolic": draft.get("diastolic"),
                    "temperature": draft.get("temperature"),
                    "pulseRate": draft.get("pulseRate"),
                    "respiratoryRate": draft.get("respiratoryRate"),
                    "oxygenSaturation": draft.get("oxygenSaturation"),
                    "heightCm": draft.get("heightCm"),
                    "weightKg": draft.get("weightKg"),
                }
                diag_candidates = [{
                    "code": prot.icd10,
                    "display": prot.title,
                    "type": "PRIMARY",
                    "confidence": 0.95,
                    "rationale": f"符合《{prot.sources[0] if prot.sources else '国家权威临床指南'}》规范诊断标准与临床路径",
                }]
                recs = prot.to_rhn_treatment_recommendations()
                suggestion = {
                    "summary": f"针对【{prot.title}】（ICD-10: {prot.icd10}）提供权威门诊临床路径、6段规范病历范文及用药安全核对建议。",
                    "recordDraft": rec_draft,
                    "diagnosisCandidates": diag_candidates,
                    "differentialDiagnoses": [],
                    "missingInformation": [],
                    "safetyAlerts": safety_alerts,
                    "alertTierCounts": audit_res.get("alertTierCounts", {}),
                    "recommendedCalculators": encounter_calculators,
                    "recommendedPlans": [{
                        "templateId": 1,
                        "name": prot.title,
                        "description": prot.summary,
                        "rationale": "基于国家权威临床指南建立的标准方案",
                    }],
                    "treatmentRecommendations": recs,
                    "disclaimer": "本建议来自知识库整理内容，原文来源与临床内容须按审核状态核验。",
                }
                assistant_content = json.dumps(suggestion, ensure_ascii=False)
            else:
                assistant_content = json.dumps({
                    "summary": "未识别到明确的主诉或疾病主题，建议补充问诊资料。",
                    "recordDraft": None,
                    "diagnosisCandidates": [],
                    "differentialDiagnoses": [],
                    "missingInformation": ["请补充患者主要就诊不适症状及持续时间"],
                    "safetyAlerts": safety_alerts,
                    "alertTierCounts": audit_res.get("alertTierCounts", {}),
                    "recommendedCalculators": encounter_calculators,
                    "recommendedPlans": [],
                    "treatmentRecommendations": [],
                    "disclaimer": "本临床建议仅供注册医师参考核验。",
                }, ensure_ascii=False)
        else:
            hits = self.searcher.search(last_user_content, limit=3)
            if hits:
                evidence_text = "\n\n".join([f"### 来源《{h.get('title')}》\n{h.get('snippet', '')}" for h in hits])
                assistant_content = f"根据中国医学权威指南与标准知识库检索结果：\n\n{evidence_text}"
            else:
                assistant_content = "知识库中暂未检索到直接匹配的指南条目，建议核对疾病或药物名称。"

        now_ts = int(time.time())
        completion_id = f"chatcmpl-cdss-{now_ts}"

        ready = audit_quality(self.root_dir)["clinicalReady"]
        review_state = {"status": "approved" if ready else "pending", "requiresClinicianReview": not ready}
        try:
            content_object = json.loads(assistant_content)
        except json.JSONDecodeError:
            content_object = None
        if isinstance(content_object, dict):
            content_object["clinicalReview"] = review_state
            assistant_content = json.dumps(content_object, ensure_ascii=False)
        elif not ready:
            assistant_content = "【待审核资料】原文来源及临床内容尚需核验。\n\n" + assistant_content

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            chunk_size = 120
            for i in range(0, len(assistant_content), chunk_size):
                sub = assistant_content[i:i + chunk_size]
                chunk_data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": now_ts,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": sub},
                        "finish_reason": None,
                    }],
                }
                self.wfile.write(f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": now_ts,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
            }
            self.wfile.write(f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            response_obj = {
                "id": completion_id,
                "object": "chat.completion",
                "created": now_ts,
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": assistant_content,
                    },
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": len(last_user_content),
                    "completion_tokens": len(assistant_content),
                    "total_tokens": len(last_user_content) + len(assistant_content),
                },
            }
            self._send_json(response_obj)

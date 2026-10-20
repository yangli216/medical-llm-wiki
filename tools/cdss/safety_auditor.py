"""
Comprehensive Clinical Decision Support Safety Auditor.
Production-grade unified prescription auditing engine integrating:
1. Dynamic physiological parameter inference (via parameter_normalizer)
2. Declarative macro-level clinical safety rules (via rule_evaluator)
3. Micro-level package insert contraindications & DDIs (via drug_checker)
4. Official NMPA daily maximum dosage & overdose auditing (via dosage_auditor)
5. TCM active / hidden Western / toxic component overlap decomposition
6. Safe Alternative Re-routing Filter (prevents dead-loop contraindicated alternatives)
7. 3-tier anti-alert-fatigue classification (HARD_STOP / SOFT_NUDGE / PASSIVE_INFO)
8. Strict contract alignment with RHN Preflight & EvaluationBoundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.cdss.parameter_normalizer import ClinicalParameterNormalizer
from tools.cdss.rule_evaluator import RuleEvaluator
from tools.cdss.drug_checker import DrugInsertRepository, DrugContraindicationAuditor
from tools.cdss.dosage_auditor import DosageLimitsAuditor
from tools.quality import audit_quality


# Authoritative TCM active / hidden Western / toxic pharmacological component dictionary
TCM_COMPONENT_DICTIONARY: Dict[str, Dict[str, Any]] = {
    "ACETAMINOPHEN": {
        "componentName": "对乙酰氨基酚 (扑热息痛)",
        "tcmKeywords": ["感冒灵", "维c银翘", "新复方大青叶", "速感宁", "感冒清", "精制银翘解毒"],
        "westernKeywords": ["对乙酰氨基酚", "扑热息痛", "泰诺", "必理通", "日夜百服咛", "白加黑", "氨酚"],
        "severity": "RED",
        "ruleId": "RULE-TCM-COMPONENT-ACETAMINOPHEN",
        "title": "中西药隐含成分重叠：对乙酰氨基酚叠加致暴发性肝衰竭风险",
        "message": "处方中多种药品均含有【对乙酰氨基酚】成分，叠加服用极易超过 2000mg/日安全红线，诱发急性肝小叶坏死与暴发性肝功能衰竭！",
        "guideline": "《中成药临床应用指导原则与中西药联合安全规范》",
        "grade": "1A",
        "alternatives": [
            {
                "name": "疏风解毒胶囊",
                "specification": "0.4g*36粒",
                "orderDraft": {"routeCode": "PO", "frequencyCode": "TID", "doseValue": 1.6, "doseUnit": "g", "durationValue": 5},
                "rationale": "纯中药疏风清热解毒制剂，不含对乙酰氨基酚等解热镇痛西药成分，可安全联用单方退热药",
                "sourceGuideline": "SRC-NAT-TCM-2021-01",
            }
        ],
    },
    "EPHEDRINE": {
        "componentName": "麻黄碱 / 伪麻黄碱 (麻黄生物碱)",
        "tcmKeywords": ["连花清瘟", "金花清感", "急支糖浆", "苏黄止咳", "通宣理肺", "麻杏石甘", "小青龙"],
        "westernKeywords": ["伪麻黄碱", "麻黄碱", "新康泰克", "泰诺酚麻美敏"],
        "severity": "YELLOW",
        "ruleId": "RULE-TCM-COMPONENT-EPHEDRINE-OVERLAP",
        "title": "中成药麻黄碱活性成分叠加预警（升压与心律失常风险）",
        "message": "处方中同时包含两种及以上含【麻黄/麻黄碱】成分的制剂，拟交感神经兴奋效应叠加易诱发血压急剧升高、窦性心动过速、心悸及前列腺增生尿潴留！",
        "guideline": "《中成药临床应用指导原则与中西药联合安全规范》",
        "grade": "1B",
        "alternatives": [
            {
                "name": "蒲地蓝消炎口服液",
                "specification": "10ml*10支",
                "orderDraft": {"routeCode": "PO", "frequencyCode": "TID", "doseValue": 10, "doseUnit": "ml", "durationValue": 5},
                "rationale": "不含麻黄生物碱成分，无拟交感升压与兴奋心肌风险",
                "sourceGuideline": "SRC-NAT-TCM-2021-01",
            }
        ],
    },
    "STRYCHNINE_ACONITINE": {
        "componentName": "马钱子碱 / 乌头碱 (剧毒生物碱)",
        "tcmKeywords": ["腰痛宁", "附子理中", "金匮肾气", "小活络丸", "大活络丸", "木瓜丸", "追风透骨"],
        "westernKeywords": [],
        "severity": "RED",
        "ruleId": "RULE-TCM-COMPONENT-TOXIC-ALKALOID",
        "title": "含剧毒生物碱（马钱子碱/乌头碱）中成药叠加中毒强阻断",
        "message": "处方中重复开具含【马钱子/川乌/草乌/附子】剧毒生物碱的中成药！治疗窗极窄，叠加服用极易诱发中枢强直性惊厥、室性心动过速、室颤及呼吸肌麻痹猝死！",
        "guideline": "《中成药临床应用指导原则与中西药联合安全规范》",
        "grade": "1A",
        "alternatives": [
            {
                "name": "双氯芬酸钠凝胶贴膏",
                "specification": "50mg/贴",
                "orderDraft": {"routeCode": "TOPICAL", "frequencyCode": "BID", "doseValue": 1, "doseUnit": "贴", "durationValue": 7},
                "rationale": "外用非甾体抗炎透皮贴剂，局部消炎镇痛确切且无乌头碱/马钱子碱神经心脏毒性",
                "sourceGuideline": "SRC-CSGP-MSK-2023-01",
            }
        ],
    },
    "ANTHRAQUINONE_PURGATIVE": {
        "componentName": "大黄蒽醌 / 苦寒峻下成分",
        "tcmKeywords": ["牛黄解毒", "黄连上清", "小儿豉翘清热", "防风通圣", "三黄片", "麻仁润肠"],
        "westernKeywords": ["番泻叶", "比沙可啶"],
        "severity": "YELLOW",
        "ruleId": "RULE-TCM-COMPONENT-ANTHRAQUINONE",
        "title": "苦寒泻下与大黄蒽醌成分重复叠加预警",
        "message": "处方中同时包含两味及以上含【大黄/番泻叶/苦寒泻下】成分的药物，叠加使用易致剧烈腹泻脱水、电解质紊乱及蒽醌类药物性肝肾损害！建议仅保留单一清热通便制剂。",
        "guideline": "《中成药临床应用指导原则与中西药联合安全规范》",
        "grade": "2A",
        "alternatives": [
            {
                "name": "乳果糖口服溶液",
                "specification": "15ml/袋",
                "orderDraft": {"routeCode": "PO", "frequencyCode": "QD", "doseValue": 15, "doseUnit": "ml", "durationValue": 14},
                "rationale": "温和渗透性泻药，不含蒽醌类刺激成分，不伤脾胃且无结肠黑变病风险",
                "sourceGuideline": "SRC-CMA-GAST-2020-01",
            }
        ],
    },
}


class ComprehensiveSafetyAuditor:
    """Production-grade CDSS prescription safety and preflight auditing engine."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.repo = DrugInsertRepository(self.root_dir)
        self.rule_evaluator = RuleEvaluator(rules_dir=self.root_dir / "rules")
        self.monograph_auditor = DrugContraindicationAuditor(
            repo=self.repo, root_dir=self.root_dir, evaluator=self.rule_evaluator
        )
        self.dosage_auditor = DosageLimitsAuditor(repo=self.repo)

    def audit_preflight_safety(
        self,
        medications: List[Any],
        patient_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes exhaustive, deterministic preflight clinical safety evaluation.
        Accepts:
          - medications: list of strings or list of dicts
          - patient_context: demographic, physiological, lab, and diagnostic parameters.
        Returns:
          Structured contract directly aligning with RHN PlanPreflight & EvaluationBoundary.
        """
        # 1. Normalize Patient Context and Execute Dynamic Physiological Inference
        normalized_patient = ClinicalParameterNormalizer.normalize_patient(patient_context)
        inferred = normalized_patient.get("_inferred_parameters", {})

        parsed_meds: List[Dict[str, Any]] = []
        med_names_for_rules: List[str] = []

        for item in medications or []:
            if isinstance(item, str):
                name = item.strip()
                parsed_meds.append({"raw": name, "name": name, "draft": None})
                med_names_for_rules.append(name)
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("medicationName") or item.get("catalogName") or "").strip()
                draft = item.get("orderDraft") or item.get("draft")
                parsed_meds.append({"raw": str(item), "name": name, "draft": draft})
                if name:
                    med_names_for_rules.append(name)

        if not parsed_meds:
            return self._build_empty_response(normalized_patient)

        # 2. Evaluate Clinical Safety Rules (Macro-level: DDI, Contraindications, Prescribing Cascades)
        macro_alerts = self.rule_evaluator.evaluate_clinical_prescription(
            med_names_for_rules, normalized_patient
        )

        # 3. Micro-level Package Insert Checks & Monograph Audit
        monograph_audit_res = self.monograph_auditor.audit_prescription(
            med_names_for_rules, normalized_patient
        )
        micro_alerts = monograph_audit_res.get("alerts", [])

        # 3b. TCM Active / Hidden Western / Toxic Component Overlap Audit
        tcm_component_alerts = self._audit_tcm_component_overlaps(
            med_names_for_rules, normalized_patient
        )

        # 4. Dosage and Daily Overdose Limits Audit
        dosage_alerts: List[Dict[str, Any]] = []
        dosage_items: List[Dict[str, Any]] = []

        for item in parsed_meds:
            d_res = self.dosage_auditor.audit_medication_dosage(
                medication_query=item["name"],
                order_draft=item["draft"],
            )
            dosage_items.append(d_res)
            if d_res.get("isOverdose"):
                sev = d_res.get("severity", "RED")
                dosage_alerts.append({
                    "ruleId": "OVERDOSE_LIMIT_EXCEEDED",
                    "severity": sev,
                    "alertTier": RuleEvaluator.map_alert_tier(sev),
                    "title": f"{d_res.get('drugName')} 超过法定日最大极量",
                    "message": d_res.get("message", ""),
                    "guideline": d_res.get("guideline", "国家药品监督管理局法定药品说明书"),
                    "grade": "1A",
                    "evidenceLevel": "强推荐 (Strong recommendation)，国家法定说明书强制极量标准",
                    "alternatives": [],
                })

        # 5. Merge and deduplicate macro, micro, and TCM component alerts
        all_candidate_alerts = list(macro_alerts)
        for ta in tcm_component_alerts:
            if not any(x.get("ruleId") == ta.get("ruleId") for x in all_candidate_alerts):
                all_candidate_alerts.append(ta)

        for ma in micro_alerts:
            sev = "RED" if ma.get("level") == "BLOCK" else "YELLOW"
            unified = {
                "ruleId": ma.get("rule") or ma.get("ruleId"),
                "severity": sev,
                "alertTier": ma.get("alertTier") or RuleEvaluator.map_alert_tier(sev),
                "title": ma.get("title") or "药品说明书安全预警",
                "message": ma.get("reason") or ma.get("message", ""),
                "guideline": ma.get("evidence") or "国家药品监督管理局法定核准说明书",
                "grade": "1A" if sev == "RED" else "1B",
                "evidenceLevel": "强推荐，国家药品监督管理局法定核准说明书",
                "alternatives": list(ma.get("alternatives", [])),
            }
            if not any(x.get("ruleId") == unified["ruleId"] for x in all_candidate_alerts):
                all_candidate_alerts.append(unified)

        # 6. Safe Alternative Re-routing Filter (prevents recommending contraindicated alternatives)
        filtered_unsafe_alternatives: List[Dict[str, Any]] = []
        for alert in all_candidate_alerts:
            raw_alts = alert.get("alternatives", [])
            if raw_alts:
                safe_alts, rejected_alts = self._filter_safe_alternatives(
                    raw_alts, normalized_patient, med_names_for_rules
                )
                alert["alternatives"] = safe_alts
                if rejected_alts:
                    alert["filteredUnsafeAlternatives"] = rejected_alts
                    filtered_unsafe_alternatives.extend(rejected_alts)

        # 7. Classify Alerts into Interactions vs Contraindications vs Dosage
        interaction_alerts: List[Dict[str, Any]] = []
        contraindication_alerts: List[Dict[str, Any]] = []

        for a in all_candidate_alerts:
            rid = str(a.get("ruleId") or "").upper()
            title = str(a.get("title") or "")
            msg = str(a.get("message") or "")

            is_interaction = (
                "DDI" in rid
                or "DUAL" in rid
                or "COMB" in rid
                or "CASCADE" in rid
                or "COMPONENT" in rid
                or "INTERVAL" in rid
                or "CHELATION" in rid
                or "DISULFIRAM" in rid
                or "合用" in title
                or "联合" in title
                or "重叠" in title
                or "叠加" in title
                or "相互作用" in title
                or "合用" in msg
                or "配伍禁忌" in title
            )
            if is_interaction:
                interaction_alerts.append(a)
            else:
                contraindication_alerts.append(a)

        # 8. Build High-Fidelity RHN Evaluation Boundaries
        int_status = self._derive_status(interaction_alerts)
        contra_status = self._derive_status(contraindication_alerts)
        dose_status = self._derive_status(dosage_alerts)

        overall_blocking = (
            int_status == "BLOCKED" or contra_status == "BLOCKED" or dose_status == "BLOCKED"
        )
        overall_warning = (
            int_status == "WARNING" or contra_status == "WARNING" or dose_status == "WARNING"
        )

        overall_level = "BLOCK" if overall_blocking else ("WARNING" if overall_warning else "PASS")
        overall_alert_tier = (
            "HARD_STOP" if overall_blocking else ("SOFT_NUDGE" if overall_warning else "PASSIVE_INFO")
        )
        can_prescribe = not overall_blocking

        if overall_blocking:
            summary = (
                f"【规则阻断】处方触发了当前配置的高风险规则。"
                f"阻断项包含：{self._summarize_alerts(interaction_alerts + contraindication_alerts + dosage_alerts, 'RED')}。"
            )
        elif overall_warning:
            summary = (
                f"【临床用药安全预警】处方中包含用药监护、特殊人群滴定或药物相互作用提示："
                f"{self._summarize_alerts(interaction_alerts + contraindication_alerts + dosage_alerts, 'YELLOW')}。"
            )
        else:
            summary = "【处方预检全部通过】经国家级指南与法定药品说明书核查，未检索到配伍禁忌或超极量风险。"

        preflight_checks = [
            {
                "code": "CLINICAL_INTERACTIONS",
                "status": int_status,
                "title": "药物相互作用与配伍禁忌核查 (DDI & 中西药成分拆解)",
                "message": (
                    f"触发 {len(interaction_alerts)} 项临床相互作用或成分重叠风险提示"
                    if interaction_alerts else "未检出高危药物相互作用或中西药隐含成分叠加"
                ),
                "alerts": interaction_alerts,
            },
            {
                "code": "CLINICAL_CONTRAINDICATIONS",
                "status": contra_status,
                "title": "特殊人群、生理指标与疾病禁忌核查",
                "message": (
                    f"触发 {len(contraindication_alerts)} 项人群或器官功能禁忌提示"
                    if contraindication_alerts else "患者特征与所开药品说明书适应禁忌相符"
                ),
                "alerts": contraindication_alerts,
            },
            {
                "code": "CLINICAL_DOSAGE_LIMITS",
                "status": dose_status,
                "title": "整理页剂量上限与给药频次核查",
                "message": (
                    f"触发 {len(dosage_alerts)} 项超极量用药风险提示"
                    if dosage_alerts else "给药剂量未超过当前配置上限"
                ),
                "alerts": dosage_alerts,
                "items": dosage_items,
            },
        ]

        quality = audit_quality(self.root_dir)
        all_alerts_combined = interaction_alerts + contraindication_alerts + dosage_alerts
        dedup_alternatives: List[Dict[str, Any]] = []
        seen_alt_names = set()
        for a in all_alerts_combined:
            for alt in a.get("alternatives", []):
                alt_name = alt.get("name")
                if alt_name and alt_name not in seen_alt_names:
                    seen_alt_names.add(alt_name)
                    dedup_alternatives.append(alt)
        return {
            "success": True,
            "clinicalReview": {"status": "approved" if quality["clinicalReady"] else "pending",
                               "requiresClinicianReview": not quality["clinicalReady"]},
            "canPrescribe": can_prescribe,
            "level": overall_level,
            "alertTier": overall_alert_tier,
            "summary": summary,
            "blockingCount": len([a for a in all_alerts_combined if a.get("severity") == "RED"]),
            "warningCount": len([a for a in all_alerts_combined if a.get("severity") == "YELLOW"]),
            "alertTierCounts": {
                "HARD_STOP": len([a for a in all_alerts_combined if a.get("alertTier") == "HARD_STOP"]),
                "SOFT_NUDGE": len([a for a in all_alerts_combined if a.get("alertTier") == "SOFT_NUDGE"]),
                "PASSIVE_INFO": len([a for a in all_alerts_combined if a.get("alertTier") == "PASSIVE_INFO"]),
            },
            "evaluationBoundaries": {
                "interactions": {
                    "status": "EVALUATED",
                    "evaluationCode": int_status,
                    "message": "已依据国家卫健委指南及中成药活性成分字典完成配伍与成分重叠前置审查；临床审核状态见 clinicalReview。",
                    "alerts": interaction_alerts,
                },
                "contraindications": {
                    "status": "EVALUATED",
                    "evaluationCode": contra_status,
                    "message": "已依据国家药监局法定说明书完成特殊人群与肝肾器官功能截断前置审查；临床审核状态见 clinicalReview。",
                    "alerts": contraindication_alerts,
                },
                "dosageLimits": {
                    "status": "EVALUATED",
                    "evaluationCode": dose_status,
                    "message": "已按当前整理页剂量上限执行剂量与频次检查。",
                    "alerts": dosage_alerts,
                },
            },
            "preflightChecks": preflight_checks,
            "inferredPatientParameters": inferred,
            "allAlerts": all_alerts_combined,
            "alternatives": dedup_alternatives,
            "filteredUnsafeAlternatives": filtered_unsafe_alternatives,
        }

    def _audit_tcm_component_overlaps(
        self,
        medications: List[str],
        normalized_patient: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Decomposes Chinese Patent Medicines (TCM) and Western compound drugs into active/toxic
        pharmacological components to intercept hidden overlaps and cardiovascular risks.
        """
        alerts: List[Dict[str, Any]] = []
        if not medications:
            return alerts

        meds_lower = [m.lower().strip() for m in medications if m.strip()]

        for comp_code, cfg in TCM_COMPONENT_DICTIONARY.items():
            matched_drugs: List[str] = []
            has_tcm_hit = False
            all_kw = cfg["tcmKeywords"] + cfg["westernKeywords"]

            for med in meds_lower:
                if any(k in med for k in all_kw):
                    matched_drugs.append(med)
                    if any(tk in med for tk in cfg["tcmKeywords"]):
                        has_tcm_hit = True

            # Trigger overlap alert if >= 2 distinct medications share this active/toxic component
            # and at least one is a TCM preparation
            if len(matched_drugs) >= 2 and has_tcm_hit:
                sev = cfg["severity"]
                alerts.append({
                    "ruleId": cfg["ruleId"],
                    "severity": sev,
                    "alertTier": RuleEvaluator.map_alert_tier(sev),
                    "title": cfg["title"],
                    "message": f"{cfg['message']}（检出含【{cfg['componentName']}】的重叠药品：{', '.join(matched_drugs)}）",
                    "guideline": cfg["guideline"],
                    "grade": cfg["grade"],
                    "evidenceLevel": "强推荐，国家中医药管理局《中成药临床应用指导原则》",
                    "alternatives": list(cfg.get("alternatives", [])),
                })

            # Additional patient-specific check: Ephedrine-containing TCM in severe hypertension / tachycardia / AF
            if comp_code == "EPHEDRINE" and has_tcm_hit:
                has_severe_cv = bool(
                    normalized_patient.get("sbp_gt_160")
                    or normalized_patient.get("hypertensive_crisis")
                    or normalized_patient.get("tachycardia")
                    or normalized_patient.get("has_af")
                )
                if has_severe_cv:
                    alerts.append({
                        "ruleId": "RULE-TCM-COMPONENT-EPHEDRINE-CV",
                        "severity": "YELLOW",
                        "alertTier": "SOFT_NUDGE",
                        "title": "含麻黄碱中成药用于未控制高血压/心动过速/房颤患者警戒",
                        "message": (
                            f"患者存在血压显著升高(SBP≥160mmHg)、心动过速或房颤，所开中成药（{', '.join(matched_drugs)}）"
                            f"含麻黄碱成分，可兴奋交感神经诱发血压骤升或快速型心律失常，建议严密监测血压心率或换用不含麻黄制剂。"
                        ),
                        "guideline": "《中成药临床应用指导原则与中西药联合安全规范》",
                        "grade": "1B",
                        "evidenceLevel": "强推荐，国家中医药管理局《中成药临床应用指导原则》",
                        "alternatives": list(cfg.get("alternatives", [])),
                    })

        return alerts

    def _filter_safe_alternatives(
        self,
        alternatives: List[Dict[str, Any]],
        normalized_patient: Dict[str, Any],
        prescribed_meds: List[str],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Verifies that each recommended alternative drug does NOT itself violate
        the current patient's contraindications (allergies, pregnancy, eGFR, hepatic, etc.).
        Prevents dead-loop unsafe recommendations in clinical decision support.
        """
        safe_list: List[Dict[str, Any]] = []
        rejected_list: List[Dict[str, Any]] = []

        allergy_text = " ".join(normalized_patient.get("normalized_allergies", [])).lower()

        for alt in alternatives:
            alt_name = str(alt.get("name") or "").strip()
            if not alt_name:
                continue

            # 1. Direct allergy match check against alternative name
            if allergy_text and any(
                alg in alt_name.lower() or (alg in ("头孢", "先锋") and "头孢" in alt_name)
                or (alg in ("青霉素", "阿莫西林") and ("阿莫西林" in alt_name or "青霉素" in alt_name))
                or (alg in ("磺胺",) and ("磺胺" in alt_name or "塞来昔布" in alt_name))
                for alg in normalized_patient.get("normalized_allergies", [])
            ):
                rejected_list.append({
                    "name": alt_name,
                    "filterReason": f"备选平替药【{alt_name}】命中当前患者过敏史（{allergy_text}），已由安全死循环过滤器自动剔除",
                })
                continue

            # 2. Monograph contraindication check if the alternative is in the drug insert repository
            drug_obj = self.repo.get(alt_name)
            if drug_obj:
                audit_res = self.monograph_auditor.audit(alt_name, normalized_patient)
                if audit_res.get("success") and not audit_res.get("canPrescribe"):
                    reasons = [a.get("title") or a.get("reason") for a in audit_res.get("alerts", []) if a.get("level") == "BLOCK"]
                    rejected_list.append({
                        "name": alt_name,
                        "filterReason": f"备选平替药【{alt_name}】触发当前患者个体化禁忌（{'；'.join(reasons)}），已由安全过滤器自动剔除",
                    })
                    continue

            safe_list.append(alt)

        return safe_list, rejected_list

    @staticmethod
    def _derive_status(alerts: List[Dict[str, Any]]) -> str:
        if any(a.get("severity") == "RED" or a.get("level") == "BLOCK" for a in alerts):
            return "BLOCKED"
        if any(a.get("severity") == "YELLOW" or a.get("level") == "WARNING" for a in alerts):
            return "WARNING"
        return "PASS"

    @staticmethod
    def _summarize_alerts(alerts: List[Dict[str, Any]], target_sev: str) -> str:
        matched = [a.get("title") for a in alerts if a.get("severity") == target_sev and a.get("title")]
        if not matched:
            return "无"
        return "；".join(matched[:3])

    def _build_empty_response(self, patient: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "canPrescribe": True,
            "level": "PASS",
            "alertTier": "PASSIVE_INFO",
            "summary": "处方中无药品项需核查",
            "blockingCount": 0,
            "warningCount": 0,
            "alertTierCounts": {"HARD_STOP": 0, "SOFT_NUDGE": 0, "PASSIVE_INFO": 0},
            "evaluationBoundaries": {
                "interactions": {"status": "EVALUATED", "evaluationCode": "PASS", "message": "无药品"},
                "contraindications": {"status": "EVALUATED", "evaluationCode": "PASS", "message": "无药品"},
                "dosageLimits": {"status": "EVALUATED", "evaluationCode": "PASS", "message": "无药品"},
            },
            "preflightChecks": [],
            "inferredPatientParameters": patient.get("_inferred_parameters", {}),
            "allAlerts": [],
            "alternatives": [],
            "filteredUnsafeAlternatives": [],
        }

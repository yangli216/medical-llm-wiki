"""
Comprehensive Clinical Decision Support Safety Auditor.
Production-grade unified prescription auditing engine integrating:
1. Dynamic physiological parameter inference (via parameter_normalizer)
2. Declarative macro-level clinical safety rules (via rule_evaluator)
3. Micro-level package insert contraindications & DDIs (via drug_checker)
4. Official NMPA daily maximum dosage & overdose auditing (via dosage_auditor)
5. Strict contract alignment with RHN Preflight & EvaluationBoundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.cdss.parameter_normalizer import ClinicalParameterNormalizer
from tools.cdss.rule_evaluator import RuleEvaluator
from tools.cdss.drug_checker import DrugInsertRepository, DrugContraindicationAuditor
from tools.cdss.dosage_auditor import DosageLimitsAuditor
from tools.quality import audit_quality


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
          - medications: list of strings (e.g. ["盐酸二甲双胍片 0.5g tid", "缬沙坦胶囊 80mg qd"])
            or list of dicts (e.g. [{ "name": "二甲双胍", "orderDraft": { ... } }])
          - patient_context: demographic, physiological, lab, and diagnostic parameters.
        Returns:
          Structured contract directly aligning with RHN PlanPreflight & EvaluationBoundary.
        """
        # 1. Normalize Patient Context and Execute Dynamic Physiological Inference
        normalized_patient = ClinicalParameterNormalizer.normalize_patient(patient_context)
        inferred = normalized_patient.get("_inferred_parameters", {})

        # Extract plain medication query names and optional structured drafts
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
                dosage_alerts.append({
                    "ruleId": "OVERDOSE_LIMIT_EXCEEDED",
                    "severity": d_res.get("severity", "RED"),
                    "title": f"{d_res.get('drugName')} 超过法定日最大极量",
                    "message": d_res.get("message", ""),
                    "guideline": d_res.get("guideline", "国家药品监督管理局法定药品说明书"),
                    "grade": "1A",
                    "evidenceLevel": "强推荐 (Strong recommendation)，国家法定说明书强制极量标准",
                })

        # 5. Classify Alerts into Interactions vs Contraindications vs Dosage
        interaction_alerts: List[Dict[str, Any]] = []
        contraindication_alerts: List[Dict[str, Any]] = []

        # Merge and deduplicate macro and micro alerts
        all_candidate_alerts = list(macro_alerts)
        for ma in micro_alerts:
            # Map micro alert schema to unified schema
            unified = {
                "ruleId": ma.get("rule") or ma.get("ruleId"),
                "severity": "RED" if ma.get("level") == "BLOCK" else "YELLOW",
                "title": ma.get("title") or "药品说明书安全预警",
                "message": ma.get("reason") or ma.get("message", ""),
                "guideline": ma.get("evidence") or "国家药品监督管理局法定核准说明书",
                "alternatives": ma.get("alternatives", []),
            }
            if not any(x.get("ruleId") == unified["ruleId"] for x in all_candidate_alerts):
                all_candidate_alerts.append(unified)

        for a in all_candidate_alerts:
            rid = str(a.get("ruleId") or "").upper()
            title = str(a.get("title") or "")
            msg = str(a.get("message") or "")

            # Identify if interaction or contraindication
            is_interaction = (
                "DDI" in rid
                or "DUAL" in rid
                or "COMB" in rid
                or "CASCADE" in rid
                or "合用" in title
                or "联合" in title
                or "相互作用" in title
                or "合用" in msg
                or "配伍禁忌" in title
            )
            if is_interaction:
                interaction_alerts.append(a)
            else:
                contraindication_alerts.append(a)

        # 6. Build High-Fidelity RHN Evaluation Boundaries
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
        can_prescribe = not overall_blocking

        # Summary Generation
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
            summary = f"【规则检查通过】已检索 {len(self.repo.list_all())} 篇药品整理页，当前规则未检出配伍禁忌或超极量风险。"

        # Construct preflight check items for RHN
        preflight_checks = [
            {
                "code": "CLINICAL_INTERACTIONS",
                "status": int_status,
                "title": "药物相互作用与配伍禁忌核查 (DDI)",
                "message": (
                    f"触发 {len(interaction_alerts)} 项临床相互作用风险提示"
                    if interaction_alerts else "未检出高危药物相互作用"
                ),
                "alerts": interaction_alerts,
            },
            {
                "code": "CLINICAL_CONTRAINDICATIONS",
                "status": contra_status,
                "title": "特殊人群、生理指标与疾病禁忌核查",
                "message": (
                    f"触发 {len(contraindication_alerts)} 项人群或疾病禁忌提示"
                    if contraindication_alerts else "当前规则未检出特殊人群或器官功能风险"
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
        return {
            "success": True,
            "clinicalReview": {"status": "approved" if quality["clinicalReady"] else "pending",
                               "requiresClinicianReview": not quality["clinicalReady"]},
            "canPrescribe": can_prescribe,
            "level": overall_level,
            "summary": summary,
            "blockingCount": len([a for a in (interaction_alerts + contraindication_alerts + dosage_alerts) if a.get("severity") == "RED"]),
            "warningCount": len([a for a in (interaction_alerts + contraindication_alerts + dosage_alerts) if a.get("severity") == "YELLOW"]),
            "evaluationBoundaries": {
                "interactions": {
                    "status": "EVALUATED",
                    "evaluationCode": int_status,
                    "message": "已执行当前配置的配伍相互作用规则；临床审核状态见 clinicalReview。",
                    "alerts": interaction_alerts,
                },
                "contraindications": {
                    "status": "EVALUATED",
                    "evaluationCode": contra_status,
                    "message": "已执行药品整理页对应的特殊人群与器官功能规则；临床审核状态见 clinicalReview。",
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
            "allAlerts": interaction_alerts + contraindication_alerts + dosage_alerts,
            "alternatives": [
                alt
                for a in (interaction_alerts + contraindication_alerts + dosage_alerts)
                for alt in a.get("alternatives", [])
            ],
        }

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
            "summary": "处方中无药品项需核查",
            "blockingCount": 0,
            "warningCount": 0,
            "evaluationBoundaries": {
                "interactions": {"status": "EVALUATED", "evaluationCode": "PASS", "message": "无药品"},
                "contraindications": {"status": "EVALUATED", "evaluationCode": "PASS", "message": "无药品"},
                "dosageLimits": {"status": "EVALUATED", "evaluationCode": "PASS", "message": "无药品"},
            },
            "preflightChecks": [],
            "inferredPatientParameters": patient.get("_inferred_parameters", {}),
            "allAlerts": [],
        }

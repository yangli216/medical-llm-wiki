"""
CDSS Decision Support Engine for Outpatient Clinical Plan Recommendation.
Empowers RHN (Clinical Assistant / Plan Compiler) with authoritative evidence,
structured order compilation, zero-manual-input clinical calculator recommendations,
and 108-rule (45 macro + 63 micro monograph + TCM component) prescription safety auditing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.cdss.protocol_loader import ProtocolRepository, ClinicalProtocol
from tools.cdss.rule_evaluator import RuleEvaluator
from tools.cdss.parameter_normalizer import ClinicalParameterNormalizer
from tools.cdss.safety_auditor import ComprehensiveSafetyAuditor
from tools.cdss.calculators import ClinicalCalculatorRegistry


class CdssEngine:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.repo = ProtocolRepository(self.root_dir)
        self.evaluator = RuleEvaluator(self.root_dir / "rules")
        self.safety_auditor = ComprehensiveSafetyAuditor(self.root_dir)

    def search_protocols(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Searches protocols by natural query or diagnosis name."""
        q = (query or "").lower().strip()
        if not q:
            return []

        from tools.cdss.diagnosis_normalizer import ClinicalDiagnosisNormalizer, GENERIC_CLINICAL_MODIFIERS
        norm = ClinicalDiagnosisNormalizer.normalize(query)

        tokens = [q]
        if norm.canonical_name and norm.canonical_name.lower() not in tokens:
            tokens.append(norm.canonical_name.lower())
        for stem in norm.core_stems:
            if stem.lower() not in tokens:
                tokens.append(stem.lower())
        if norm.icd_code and norm.icd_code.lower() not in tokens:
            tokens.append(norm.icd_code.lower())

        for w in re.split(r"[\s,，、/]+", norm.clean.lower()):
            if w and w not in tokens and w not in GENERIC_CLINICAL_MODIFIERS:
                tokens.append(w)

        synonyms_map = {
            "阑尾炎": ["急性阑尾炎", "阑尾炎门诊决策", "急腹症与急性阑尾炎"],
            "胆囊炎": ["急性胆囊炎", "胆囊结石", "胆石症"],
            "胰腺炎": ["急性胰腺炎", "重症胰腺炎"],
            "消化性溃疡": ["胃溃疡", "十二指肠溃疡", "胃黏膜病变"],
            "肾绞痛": ["输尿管结石", "肾结石", "泌尿系结石"],
            "面神经炎": ["特发性面神经麻痹", "贝尔面瘫", "bell麻痹"],
            "脑卒中": ["短暂性脑缺血发作", "tia", "缺血性脑卒中"],
            "颈椎病": ["神经根型颈椎病", "颈椎间盘突出"],
            "甲减": ["甲状腺功能减退", "甲状腺功能减退症"],
            "甲亢": ["甲状腺功能亢进", "甲状腺功能亢进症"],
            "上感": ["急性上呼吸道感染", "普通感冒"],
            "扁桃体炎": ["急性扁桃体炎", "化脓性扁桃体炎"],
            "阴道炎": ["外阴阴道假丝酵母菌病", "细菌性阴道病", "滴虫阴道炎"],
            "尿路感染": ["急性单纯性尿路感染", "急性膀胱炎"],
            "反流": ["胃食管反流", "胃食管反流病"],
            "膝骨关节炎": ["骨关节炎", "退行性膝关节炎", "膝关节炎"],
            "骨关节炎": ["膝骨关节炎", "膝关节退变"],
            "膝关节": ["膝骨关节炎", "退行性膝关节炎", "膝关节炎"],
            "膝痛": ["膝骨关节炎", "退行性膝关节炎"],
            "双膝": ["膝骨关节炎", "退行性膝关节炎"],
            "右下腹痛": ["急性阑尾炎", "阑尾炎"],
            "右上腹痛": ["急性胆囊炎", "胆囊结石"],
            "上腹痛": ["急性胰腺炎", "消化性溃疡"],
            "腰腹部绞痛": ["输尿管结石", "肾绞痛"],
            "肾区绞痛": ["输尿管结石", "肾绞痛"],
            "口角歪斜": ["特发性面神经麻痹", "贝尔面瘫"],
            "一过性肢体无力": ["短暂性脑缺血发作", "tia"],
            "颈肩痛": ["颈椎病", "神经根型颈椎综合征"],
            "荨麻疹": ["风疹块", "过敏性风团", "急性荨麻疹"],
            "前列腺增生": ["良性前列腺增生", "前列腺肥大", "bph"],
            "狂犬病": ["狂犬病暴露", "动物致伤", "犬伤", "动物咬伤"],
            "犬伤": ["狂犬病暴露", "动物致伤与犬伤暴露"],
            "肥胖": ["肥胖症", "成人超重与肥胖症", "减重", "超重"],
            "超重": ["肥胖症", "成人超重与肥胖症", "减重", "超重"],
            "减重": ["肥胖症", "成人超重与肥胖症", "减重", "超重"],
            "哮喘": ["支气管哮喘", "成人支气管哮喘", "成人哮喘"],
            "喘息": ["支气管哮喘", "成人哮喘"],
        }
        for k, syn_list in synonyms_map.items():
            if k in q or (norm.core_stems and any(k in s for s in norm.core_stems)):
                for syn in syn_list:
                    if ("儿童" in q or "小儿" in q) and "成人" in syn:
                        continue
                    if "成人" in q and ("儿童" in syn or "小儿" in syn):
                        continue
                    if syn not in tokens:
                        tokens.append(syn)

        scored: List[tuple[float, ClinicalProtocol]] = []
        for prot in self.repo.list_all():
            diag_items = [it.name for it in prot.items if it.kind == "DIAGNOSIS"]
            if not norm.is_compatible_with(prot.title, prot.aliases, prot.icd10, diag_items):
                continue

            score = 0.0

            if norm.canonical_name and norm.canonical_name.lower() in prot.title.lower():
                score += 80.0
            elif q.lower() in prot.title.lower():
                score += 60.0

            for alias in prot.aliases:
                if norm.canonical_name and norm.canonical_name.lower() == alias.lower():
                    score += 90.0
                elif q.lower() == alias.lower():
                    score += 80.0
                elif norm.canonical_name and norm.canonical_name.lower() in alias.lower():
                    score += 60.0
                elif q.lower() in alias.lower() or alias.lower() in q.lower():
                    score += 40.0

            if norm.icd_code and prot.icd10:
                from tools.cdss.icd_mapper import ICDMapper
                icd_cands = ICDMapper.get_instance().resolve_candidates(norm.icd_code)
                prot_icds = [c.strip().upper() for c in prot.icd10.split(",") if c.strip()]
                matched_rank = None
                for idx, cand in enumerate(icd_cands):
                    if cand in prot_icds:
                        matched_rank = idx
                        break
                if matched_rank == 0:
                    score += 100.0
                elif matched_rank is not None and matched_rank <= 2:
                    score += 90.0
                elif matched_rank is not None:
                    score += 75.0
                elif norm.icd_category and any(p_icd.startswith(norm.icd_category.upper()) for p_icd in prot_icds):
                    score += 60.0

            for stem in norm.core_stems:
                if stem.lower() in prot.title.lower():
                    score += 40.0
                for alias in prot.aliases:
                    if stem.lower() in alias.lower():
                        score += 30.0

            for item in prot.items:
                if item.kind == "DIAGNOSIS":
                    if norm.canonical_name and norm.canonical_name.lower() in item.name.lower():
                        score += 35.0
                    for stem in norm.core_stems:
                        if stem.lower() in item.name.lower():
                            score += 25.0

            for t in tokens:
                if t in GENERIC_CLINICAL_MODIFIERS or len(t) < 2:
                    continue
                if t in prot.title.lower():
                    score += 15.0
                for alias in prot.aliases:
                    if t in alias.lower():
                        score += 10.0

            if score >= 30.0:
                scored.append((score, prot))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for rank, (score, p) in enumerate(scored[:limit], start=1):
            results.append({
                "rank": rank,
                "score": score,
                "protocolId": p.protocol_id,
                "title": p.title,
                "icd10": p.icd10,
                "category": p.category,
                "summary": p.summary,
            })
        return results

    def compile_rhn_plan(
        self,
        query_or_id: str,
        patient_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compiles a clinical plan intent compatible with RHN PlanIntent and PlanTextDraft."""
        prot = self.repo.get(query_or_id)
        if not prot:
            matches = self.search_protocols(query_or_id, limit=1)
            if matches:
                prot = self.repo.get(matches[0]["protocolId"])

        if not prot:
            return {
                "success": False,
                "error": f"知识库暂未收录该病种临床诊疗方案: {query_or_id}",
                "not_found": True,
            }

        plan_intent = prot.to_rhn_plan_intent()

        # Automatically recommend and pre-calculate clinical calculators for this encounter
        emr_ctx = dict(patient_context) if isinstance(patient_context, dict) else {}
        if not emr_ctx.get("diagnosis"):
            emr_ctx["diagnosis"] = prot.title
        recommended_calcs = ClinicalCalculatorRegistry.recommend_calculators_for_encounter(emr_ctx)

        return {
            "success": True,
            "protocolId": prot.protocol_id,
            "scopeType": "HOSPITAL",
            "sourceType": "AI_INPUT",
            "planIntent": plan_intent,
            "candidate": prot.to_rhn_plan_candidate(1),
            "treatmentRecommendations": prot.to_rhn_treatment_recommendations(),
            "recommendedCalculators": recommended_calcs,
        }

    def audit_prescription(
        self,
        medications: List[str],
        patient_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Audits a proposed prescription list against declarative CDSS rules in rules/clinical_safety_rules.json
        and TCM active/toxic component decomposition, with Safe Alternative Re-routing filtering.
        """
        norm_profile = ClinicalParameterNormalizer.normalize_patient(patient_profile)
        profile = dict(norm_profile)
        meds_text = " ".join(medications).lower()

        alt_val = profile.get("alt")
        if alt_val is not None:
            try:
                if float(alt_val) >= 120:
                    profile["alt_above_3x"] = True
            except (ValueError, TypeError):
                pass

        if any(x in meds_text for x in ["50μg", "100μg", "75μg", "50ug", "100ug", "75ug"]):
            profile["lt4_dose_above_25"] = True

        # 1. Evaluate macro clinical rules
        alerts = self.evaluator.evaluate_clinical_prescription(medications, profile)

        # 2. Evaluate TCM active/hidden component overlap rules
        tcm_alerts = self.safety_auditor._audit_tcm_component_overlaps(medications, profile)
        for ta in tcm_alerts:
            if not any(x.get("ruleId") == ta.get("ruleId") for x in alerts):
                alerts.append(ta)

        # Handle contextual informed-consent override for off-label pediatric tetracyclines
        has_consent = bool(profile.get("off_label_consent") or profile.get("informed_consent"))
        if has_consent:
            for a in alerts:
                if a.get("ruleId") == "RULE-PED-TETRACYCLINE-AGE":
                    a["severity"] = "YELLOW"
                    a["alertTier"] = "SOFT_NUDGE"
                    a["title"] = "8岁以下儿童使用新型四环素类超说明书告知与监测"
                    a["message"] = "患者年龄 <8 岁，多西环素/米诺环素用于大环内酯耐药重症支原体肺炎属于超说明书用药。已记录监护人知情同意，请严格按照指南疗程用药，并密切监测牙齿黄染釉质发育及胃肠道反应。"

        # Handle specific eGFR formatted message
        egfr = profile.get("egfr")
        if egfr is not None:
            for a in alerts:
                if a.get("ruleId") == "RULE-SAFETY-METFORMIN-RENAL":
                    a["message"] = f"患者 eGFR = {egfr} ml/min/1.73m² (< 30)，二甲双胍蓄积导致致死性乳酸酸中毒风险极高，绝对禁用！"
                elif a.get("ruleId") == "RULE-SAFETY-METFORMIN-WARN":
                    a["message"] = f"患者 eGFR = {egfr} ml/min/1.73m² (30～44)，二甲双胍每日最大剂量不得超过 1000mg，并每 3 个月复查肾功能。"
                elif a.get("ruleId") == "RULE-OSTEO-BISPHOSPHONATE-RENAL":
                    a["message"] = f"患者 eGFR = {egfr} ml/min/1.73m² (< 35)，双膦酸盐完全经肾小球滤过与肾小管排泄，重度肾损伤蓄积可诱发急性肾小管坏死及不可逆肾衰竭！绝对禁用，推荐换用地舒单抗或活性维生素D。"
                elif a.get("ruleId") == "RULE-UTI-NITROFURANTOIN-RENAL":
                    a["message"] = f"患者 eGFR = {egfr} ml/min/1.73m² (< 30)，呋喃妥因无法正常滤过排泄至尿液导致尿液杀菌浓度不足（治疗无效），且药物在血液组织中严重蓄积可诱发不可逆外周神经病变与严重肺纤维化毒性！绝对禁用，推荐换用头孢克肟等药物。"

        # Handle specific age formatted message
        age = profile.get("age")
        if age is not None:
            for a in alerts:
                if a.get("ruleId") == "RULE-PIM-ELDERLY-BZD":
                    a["message"] = f"患者年龄 {age} 岁 (>=65)，长效苯二氮䓬类具有强肌松和镇静蓄积作用，显著增加跌倒、股骨骨折和急性谵妄风险！"
                elif a.get("ruleId") == "RULE-PEDIATRIC-ASPIRIN":
                    a["message"] = f"患者年龄 {age} 岁 (<18)，儿童青少年病毒感染发热使用阿司匹林/赖氨匹林可诱发致死性 Reye 综合征（急性脑病合并肝衰竭），绝对禁用！推荐退热换用对乙酰氨基酚或布洛芬。"
                elif a.get("ruleId") == "RULE-PEDIATRIC-QUINOLONE":
                    a["message"] = f"患者年龄 {age} 岁 (<18)，喹诺酮类抗菌药物可导致幼年动物负重关节软骨损伤与骨骺退变，儿童门诊严禁开具！推荐遵指征选用头孢菌素或阿莫西林克拉维酸钾。"
                elif a.get("ruleId") == "RULE-PEDIATRIC-LOPERAMIDE":
                    a["message"] = f"患者年龄 {age} 岁 (<12)，洛哌丁胺等强效止泻药在儿童中极易引发麻痹性肠梗阻、中毒性巨结肠及中枢神经抑制，严禁使用！儿童补液首选口服补液盐散(III)。"

        # 3. Filter alternatives via Safe Alternative Re-routing Filter
        filtered_unsafe: List[Dict[str, Any]] = []
        dedup_alternatives: List[Dict[str, Any]] = []
        seen_alt_names = set()

        for a in alerts:
            if not a.get("alertTier"):
                a["alertTier"] = RuleEvaluator.map_alert_tier(a.get("severity", "RED"))
            raw_alts = a.get("alternatives", [])
            if raw_alts:
                safe_alts, rejected_alts = self.safety_auditor._filter_safe_alternatives(
                    raw_alts, profile, medications
                )
                a["alternatives"] = safe_alts
                if rejected_alts:
                    a["filteredUnsafeAlternatives"] = rejected_alts
                    filtered_unsafe.extend(rejected_alts)
                for sa in safe_alts:
                    aname = sa.get("name")
                    if aname and aname not in seen_alt_names:
                        seen_alt_names.add(aname)
                        dedup_alternatives.append(sa)

        red_count = len([a for a in alerts if a["severity"] == "RED"])
        yellow_count = len([a for a in alerts if a["severity"] == "YELLOW"])
        overall_tier = "HARD_STOP" if red_count > 0 else ("SOFT_NUDGE" if yellow_count > 0 else "PASSIVE_INFO")

        return {
            "is_safe": red_count == 0,
            "canPrescribe": (red_count == 0),
            "alertTier": overall_tier,
            "total_alerts": len(alerts),
            "red_count": red_count,
            "yellow_count": yellow_count,
            "alertTierCounts": {
                "HARD_STOP": red_count,
                "SOFT_NUDGE": yellow_count,
                "PASSIVE_INFO": 0,
            },
            "alerts": alerts,
            "alternatives": dedup_alternatives,
            "filteredUnsafeAlternatives": filtered_unsafe,
            "inferredPatientParameters": profile.get("_inferred_parameters", {}),
        }

    def audit_preflight_safety(
        self,
        medications: List[Any],
        patient_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Performs exhaustive, production-grade clinical preflight safety evaluation.
        Outputs structured evaluation boundaries and preflight checks aligned with RHN contract.
        """
        return self.safety_auditor.audit_preflight_safety(medications, patient_profile)

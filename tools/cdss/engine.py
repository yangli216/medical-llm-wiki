"""
CDSS Decision Support Engine for Outpatient Clinical Plan Recommendation.
Empowers RHN (Clinical Assistant / Plan Compiler) with authoritative evidence,
structured order compilation, and prescription safety auditing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.cdss.protocol_loader import ProtocolRepository, ClinicalProtocol
from tools.cdss.rule_evaluator import RuleEvaluator


class CdssEngine:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.repo = ProtocolRepository(self.root_dir)
        self.evaluator = RuleEvaluator(self.root_dir / "rules")

    def search_protocols(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Searches protocols by natural query or diagnosis name."""
        q = (query or "").lower().strip()
        if not q:
            return []

        # Generate tokens
        tokens = [q]
        for w in re.split(r"[\s,，、/]+", q):
            if w and w not in tokens:
                tokens.append(w)

        # Expand clinical synonyms
        synonyms_map = {
            "甲减": ["甲状腺功能减退", "甲状腺功能减退症"],
            "甲亢": ["甲状腺功能亢进", "甲状腺功能亢进症"],
            "上感": ["急性上呼吸道感染", "普通感冒"],
            "扁桃体炎": ["急性扁桃体炎", "化脓性扁桃体炎"],
            "阴道炎": ["外阴阴道假丝酵母菌病", "细菌性阴道病", "滴虫阴道炎"],
            "尿路感染": ["急性单纯性尿路感染", "急性膀胱炎"],
            "反流": ["胃食管反流", "胃食管反流病"],
            "膝骨关节炎": ["骨关节炎", "退行性膝关节炎", "膝关节炎"],
            "骨关节炎": ["膝骨关节炎", "膝关节退变"],
            "荨麻疹": ["风疹块", "过敏性风团", "急性荨麻疹"],
            "前列腺增生": ["良性前列腺增生", "前列腺肥大", "bph"],
            "狂犬病": ["狂犬病暴露", "动物致伤", "犬伤", "动物咬伤"],
            "犬伤": ["狂犬病暴露", "动物致伤与犬伤暴露"],
        }
        for k, syn_list in synonyms_map.items():
            if k in q:
                for syn in syn_list:
                    if syn not in tokens:
                        tokens.append(syn)

        # Extract 2-character n-grams for Chinese queries
        if len(q) >= 4:
            for i in range(len(q) - 1):
                bi = q[i:i+2]
                if bi not in tokens:
                    tokens.append(bi)

        scored: List[tuple[float, ClinicalProtocol]] = []
        for prot in self.repo.list_all():
            score = 0.0
            # 0. Full query match in title or aliases
            if q.lower() in prot.title.lower():
                score += 60.0
            for alias in prot.aliases:
                if q.lower() == alias.lower():
                    score += 80.0
                elif q.lower() in alias.lower() or alias.lower() in q.lower():
                    score += 50.0

            # 1. Exact ICD-10 match
            if prot.icd10 and any(prot.icd10.lower() == t for t in tokens):
                score += 50.0

            # 2. Title match
            for t in tokens:
                if t in prot.title.lower():
                    score += 25.0
                if prot.title.lower() in t:
                    score += 30.0

            # 3. Aliases match
            for alias in prot.aliases:
                for t in tokens:
                    if t in alias.lower() or alias.lower() in t:
                        score += 20.0

            # 4. Diagnoses items match
            for item in prot.items:
                if item.kind == "DIAGNOSIS":
                    for t in tokens:
                        if t in item.name.lower() or item.name.lower() in t:
                            score += 20.0

            # 5. Category match
            if prot.category:
                for t in tokens:
                    if t in prot.category.lower():
                        score += 10.0

            # 6. Keyword overlap in note template
            for text in prot.note_template.values():
                for t in tokens:
                    if len(t) >= 2 and t in text.lower():
                        score += 5.0
                        break

            if score > 0:
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

    def compile_rhn_plan(self, query_or_id: str) -> Dict[str, Any]:
        """Compiles a clinical plan intent compatible with RHN PlanIntent and PlanTextDraft."""
        # Try direct ID lookup first
        prot = self.repo.get(query_or_id)
        if not prot:
            # Fallback to search
            matches = self.search_protocols(query_or_id, limit=1)
            if matches:
                prot = self.repo.get(matches[0]["protocolId"])

        if not prot:
            return {
                "success": False,
                "error": f"No clinical decision protocol found matching: {query_or_id}",
            }

        plan_intent = prot.to_rhn_plan_intent()
        return {
            "success": True,
            "protocolId": prot.protocol_id,
            "scopeType": "HOSPITAL",
            "sourceType": "AI_INPUT",
            "planIntent": plan_intent,
            "candidate": prot.to_rhn_plan_candidate(1),
            "treatmentRecommendations": prot.to_rhn_treatment_recommendations(),
        }

    def audit_prescription(
        self,
        medications: List[str],
        patient_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Audits a proposed prescription list against declarative CDSS rules in rules/clinical_safety_rules.json:
        - Contraindications (pregnancy, renal thresholds, allergy)
        - Dual RAS blockade
        - Prescribing cascades
        - Dosage and duration boundaries
        """
        profile = dict(patient_profile or {})
        meds_text = " ".join(medications).lower()

        # Clinical parameter normalization
        alt_val = profile.get("alt")
        if alt_val is not None:
            try:
                if float(alt_val) >= 120:
                    profile["alt_above_3x"] = True
            except (ValueError, TypeError):
                pass

        if any(x in meds_text for x in ["50μg", "100μg", "75μg", "50ug", "100ug", "75ug"]):
            profile["lt4_dose_above_25"] = True

        # Evaluate rules declaratively via RuleEvaluator
        alerts = self.evaluator.evaluate_clinical_prescription(medications, profile)

        # Handle contextual informed-consent override for off-label pediatric tetracyclines
        has_consent = bool(profile.get("off_label_consent") or profile.get("informed_consent"))
        if has_consent:
            for a in alerts:
                if a.get("ruleId") == "RULE-PED-TETRACYCLINE-AGE":
                    a["severity"] = "YELLOW"
                    a["title"] = "8岁以下儿童使用新型四环素类超说明书告知与监测"
                    a["message"] = "患者年龄 <8 岁，多西环素/米诺环素用于大环内酯耐药重症支原体肺炎属于超说明书用药。已记录监护人知情同意，请严格按照指南疗程用药，并密切监测牙齿黄染釉质发育及胃肠道反应。"

        # Handle specific eGFR formatted message
        egfr = profile.get("egfr")
        if egfr is not None:
            for a in alerts:
                if a.get("ruleId") == "RULE-SAFETY-METFORMIN-RENAL":
                    a["message"] = f"患者 eGFR = {egfr} ml/min/1.73m² (< 30)，二甲双胍蓄积导致致死性乳酸酸中毒风险极高，绝对禁用！"
                elif a.get("ruleId") == "RULE-SAFETY-METFORMIN-WARN":
                    a["message"] = f"患者 eGFR = {egfr} ml/min/1.73m² (30~44)，二甲双胍每日最大剂量不得超过 1000mg，并每 3 个月复查肾功能。"
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

        return {
            "is_safe": len([a for a in alerts if a["severity"] == "RED"]) == 0,
            "total_alerts": len(alerts),
            "red_count": len([a for a in alerts if a["severity"] == "RED"]),
            "yellow_count": len([a for a in alerts if a["severity"] == "YELLOW"]),
            "alerts": alerts,
        }

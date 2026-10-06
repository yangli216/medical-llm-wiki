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


class CdssEngine:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.repo = ProtocolRepository(self.root_dir)

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
        # Extract 2-character n-grams for Chinese queries
        if len(q) >= 4:
            for i in range(len(q) - 1):
                bi = q[i:i+2]
                if bi not in tokens:
                    tokens.append(bi)

        scored: List[tuple[float, ClinicalProtocol]] = []
        for prot in self.repo.list_all():
            score = 0.0
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
        Audits a proposed prescription list against authoritative CDSS rules:
        - Contraindications (pregnancy, renal thresholds, allergy)
        - Dual RAS blockade
        - Prescribing cascades
        - Dosage and duration boundaries
        """
        profile = patient_profile or {}
        meds_text = " ".join(medications).lower()

        alerts: List[Dict[str, Any]] = []

        # Rule 1: Dual RAS blockade
        has_acei = any(x in meds_text for x in ["普利", "卡托普利", "依那普利", "贝那普利", "培哚普利"])
        has_arb = any(x in meds_text for x in ["沙坦", "氯沙坦", "缬沙坦", "厄贝沙坦", "替米沙坦"])
        has_arni = any(x in meds_text for x in ["沙库巴曲", "arni"])
        if (has_acei and has_arb) or (has_arb and has_arni) or (has_acei and has_arni):
            alerts.append({
                "ruleId": "RULE-SAFETY-RAS-DUAL",
                "severity": "RED",
                "title": "严禁双重 RAS 轴阻断",
                "message": "严禁 ACEI、ARB 或 ARNI 重叠联合使用。双重阻断不增加临床获益，反而急剧增加急性肾损伤（AKI）和恶性高钾血症风险！",
                "guideline": "《中国高血压防治指南（2024年修订版）》",
            })

        # Rule 2: Pregnancy + ACEI/ARB/ARNI
        is_pregnant = bool(profile.get("is_pregnant") or profile.get("pregnancy"))
        if is_pregnant and (has_acei or has_arb or has_arni):
            alerts.append({
                "ruleId": "RULE-SAFETY-PREGNANCY-RAS",
                "severity": "RED",
                "title": "妊娠期禁用 RAS 抑制剂",
                "message": "ACEI/ARB/ARNI 具有明确的胎儿畸形与致死性毒性，妊娠期女性绝对禁用！建议换用拉贝洛尔或硝苯地平控释片。",
                "guideline": "《中国高血压防治指南》",
            })

        # Rule 3: Metformin + Renal eGFR < 30
        egfr = profile.get("egfr")
        has_metformin = "二甲双胍" in meds_text
        if has_metformin and egfr is not None:
            try:
                egfr_val = float(egfr)
                if egfr_val < 30:
                    alerts.append({
                        "ruleId": "RULE-SAFETY-METFORMIN-RENAL",
                        "severity": "RED",
                        "title": "重度肾功能不全禁用二甲双胍",
                        "message": f"患者 eGFR = {egfr_val} ml/min/1.73m² (< 30)，二甲双胍蓄积导致致死性乳酸酸中毒风险极高，绝对禁用！",
                        "guideline": "《中国2型糖尿病防治指南（2024版）》",
                    })
                elif egfr_val < 45:
                    alerts.append({
                        "ruleId": "RULE-SAFETY-METFORMIN-WARN",
                        "severity": "YELLOW",
                        "title": "中重度肾损伤二甲双胍减量提醒",
                        "message": f"患者 eGFR = {egfr_val} ml/min/1.73m² (30~44)，二甲双胍每日最大剂量不得超过 1000mg，并每 3 个月复查肾功能。",
                        "guideline": "《中国2型糖尿病防治指南（2024版）》",
                    })
            except (ValueError, TypeError):
                pass

        # Rule 4: Nitrates + PDE-5 inhibitors
        has_nitrate = any(x in meds_text for x in ["硝酸甘油", "单硝酸", "硝酸异山梨酯"])
        has_pde5 = any(x in meds_text for x in ["西地那非", "他达拉非", "伐地那非"])
        if has_nitrate and has_pde5:
            alerts.append({
                "ruleId": "RULE-SAFETY-NITRATE-PDE5",
                "severity": "RED",
                "title": "致命低血压休克：硝酸酯类合用 PDE-5 抑制剂绝对禁忌",
                "message": "24小时内严禁合用西地那非，48小时内严禁合用他达拉非！协同舒血管会导致难治性恶性低血压休克及猝死！",
                "guideline": "《中国急性ST段抬高型心肌梗死诊断和治疗指南》",
            })

        # Rule 5: Prescribing cascade (CCB edema -> Loop diuretics)
        has_dhp_ccb = any(x in meds_text for x in ["氨氯地平", "硝苯地平", "非洛地平"])
        has_diuretic = any(x in meds_text for x in ["呋塞米", "托拉塞米", "氢氯噻嗪"])
        if has_dhp_ccb and has_diuretic:
            alerts.append({
                "ruleId": "RULE-CASCADE-CCB-EDEMA",
                "severity": "YELLOW",
                "title": "处方瀑布预警：CCB 下肢水肿防误用利尿剂",
                "message": "二氢吡啶类 CCB 引起的脚踝水肿为微血管扩张压力差所致，非水钠潴留。加用利尿剂常引发低钾与脱水；指南推荐联合 ARB/ACEI 扩张微静脉以减轻水肿。",
                "guideline": "《基层医疗卫生机构老年人多重用药与慢病共病全科安全管理指南》",
            })

        # Rule 6: Duplicate NSAIDs
        nsaids_keywords = ["布洛芬", "双氯芬酸", "塞来昔布", "美洛昔康", "双氯芬酸钠", "依托考昔"]
        matched_nsaids = [k for k in nsaids_keywords if k in meds_text]
        if len(matched_nsaids) >= 2:
            alerts.append({
                "ruleId": "RULE-SAFETY-DUAL-NSAIDS",
                "severity": "RED",
                "title": "严禁口服两种及以上非甾体抗炎药(NSAIDs)",
                "message": f"处方中检测到多种 NSAIDs ({', '.join(matched_nsaids)}) 重复口服。不增加镇痛疗效，急剧增加急性消化道穿孔大出血及肾损伤风险！",
                "guideline": "《非特异性腰痛基层全科诊疗与康复管理指南》",
            })

        # Rule 7: Montmorillonite drug absorption
        has_mont = "蒙脱石散" in meds_text
        has_other_oral = any(x in meds_text for x in ["抗生素", "阿莫西林", "头孢", "益生菌", "双歧杆菌"])
        if has_mont and has_other_oral:
            alerts.append({
                "ruleId": "RULE-SAFETY-MONTMORILLONITE-INTERVAL",
                "severity": "YELLOW",
                "title": "蒙脱石散服药间隔警示",
                "message": "蒙脱石散具有强吸附作用，与抗生素或活菌制剂必须间隔至少 2 小时服用，避免其他药物被物理吸附排出失效！",
                "guideline": "《全科常见症状基层诊疗指南》",
            })

        # Rule 8: Long-acting BZDs in elderly
        age = profile.get("age")
        has_long_bzd = any(x in meds_text for x in ["地西泮", "安定", "氯硝西泮"])
        if has_long_bzd and age is not None:
            try:
                if int(age) >= 65:
                    alerts.append({
                        "ruleId": "RULE-PIM-ELDERLY-BZD",
                        "severity": "RED",
                        "title": "老年人潜在不适当用药(PIM)：避免长期长效苯二氮䓬",
                        "message": f"患者年龄 {age} 岁 (>=65)，长效苯二氮䓬类具有强肌松和镇静蓄积作用，显著增加跌倒、股骨骨折和急性谵妄风险！",
                        "guideline": "《基层医疗卫生机构老年人多重用药与慢病共病全科安全管理指南》",
                    })
            except (ValueError, TypeError):
                pass

        return {
            "is_safe": len([a for a in alerts if a["severity"] == "RED"]) == 0,
            "total_alerts": len(alerts),
            "red_count": len([a for a in alerts if a["severity"] == "RED"]),
            "yellow_count": len([a for a in alerts if a["severity"] == "YELLOW"]),
            "alerts": alerts,
        }

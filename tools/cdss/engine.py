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

        # Expand clinical synonyms
        synonyms_map = {
            "甲减": ["甲状腺功能减退", "甲状腺功能减退症"],
            "甲亢": ["甲状腺功能亢进", "甲状腺功能亢进症"],
            "上感": ["急性上呼吸道感染", "普通感冒"],
            "扁桃体炎": ["急性扁桃体炎", "化脓性扁桃体炎"],
            "阴道炎": ["外阴阴道假丝酵母菌病", "细菌性阴道病", "滴虫阴道炎"],
            "尿路感染": ["急性单纯性尿路感染", "急性膀胱炎"],
            "反流": ["胃食管反流", "胃食管反流病"],
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

        # Rule 9: Pediatric fever - Aspirin contraindication (Reye Syndrome)
        has_aspirin = any(x in meds_text for x in ["阿司匹林", "赖氨匹林", "巴米尔"])
        if has_aspirin and age is not None:
            try:
                if int(age) < 18:
                    alerts.append({
                        "ruleId": "RULE-PEDIATRIC-ASPIRIN",
                        "severity": "RED",
                        "title": "儿童发热严禁使用阿司匹林（Reye综合征风险）",
                        "message": f"患者年龄 {age} 岁 (<18)，儿童青少年病毒感染发热使用阿司匹林/赖氨匹林可诱发致死性 Reye 综合征（急性脑病合并肝衰竭），绝对禁用！推荐退热换用对乙酰氨基酚或布洛芬。",
                        "guideline": "《儿童急性呼吸道感染与急性支气管炎规范化诊疗专家共识（2023）》",
                    })
            except (ValueError, TypeError):
                pass

        # Rule 10: Pediatric contraindication - Quinolones
        has_quinolone = any(x in meds_text for x in ["左氧氟沙星", "莫西沙星", "诺氟沙星", "环丙沙星", "氧氟沙星"])
        if has_quinolone and age is not None:
            try:
                if int(age) < 18:
                    alerts.append({
                        "ruleId": "RULE-PEDIATRIC-QUINOLONE",
                        "severity": "RED",
                        "title": "18岁以下儿童禁用喹诺酮类抗生素（软骨发育毒性）",
                        "message": f"患者年龄 {age} 岁 (<18)，喹诺酮类抗菌药物可导致幼年动物负重关节软骨损伤与骨骺退变，儿童门诊严禁开具！推荐遵指征选用头孢菌素或阿莫西林克拉维酸钾。",
                        "guideline": "《中国儿童急性感染性腹泻病临床实践指南（2022）》",
                    })
            except (ValueError, TypeError):
                pass

        # Rule 11: Pediatric diarrhea - Loperamide contraindication
        has_loperamide = any(x in meds_text for x in ["洛哌丁胺", "易蒙停", "地芬诺酯"])
        if has_loperamide and age is not None:
            try:
                if int(age) < 12:
                    alerts.append({
                        "ruleId": "RULE-PEDIATRIC-LOPERAMIDE",
                        "severity": "RED",
                        "title": "儿童急性腹泻严禁使用洛哌丁胺等肠蠕动抑制剂",
                        "message": f"患者年龄 {age} 岁 (<12)，洛哌丁胺等强效止泻药在儿童中极易引发麻痹性肠梗阻、中毒性巨结肠及中枢神经抑制，严禁使用！儿童补液首选口服补液盐散(III)。",
                        "guideline": "《中国儿童急性感染性腹泻病临床实践指南（2022）》",
                    })
            except (ValueError, TypeError):
                pass

        # Rule 12: TCM Xiaoke Pill + Sulfonylureas (Fatal Hypoglycemia)
        has_xiaoke = "消渴丸" in meds_text
        has_sulfonylurea = any(x in meds_text for x in ["格列本脲", "优降糖", "格列齐特", "格列美脲", "格列吡嗪"])
        if has_xiaoke and has_sulfonylurea:
            alerts.append({
                "ruleId": "RULE-TCM-XIAOKE-SULFONYLUREA",
                "severity": "RED",
                "title": "消渴丸严禁与磺脲类降糖西药重复联用",
                "message": "消渴丸每 10 丸含格列本脲 2.5mg，与西药磺脲类降糖药叠加会导致严重、不可逆的致死性低血糖昏迷与脑水肿，绝对禁止联合处方！",
                "guideline": "《中成药临床应用指导原则与中西药联合安全规范》",
            })

        # Rule 13: TCM with Acetaminophen + Western Paracetamol duplication
        has_tcm_apap = any(x in meds_text for x in ["感冒灵", "维c银翘片"])
        has_western_apap = any(x in meds_text for x in ["对乙酰氨基酚", "扑热息痛", "酚麻美敏", "散利痛", "泰诺", "白加黑", "快克"])
        if has_tcm_apap and has_western_apap:
            alerts.append({
                "ruleId": "RULE-TCM-ACETAMINOPHEN-DUAL",
                "severity": "RED",
                "title": "含对乙酰氨基酚中成药与西药感冒药重叠（暴发性肝坏死风险）",
                "message": "感冒灵颗粒（每袋含0.2g对乙酰氨基酚）或维C银翘片严禁与含扑热息痛西药叠加开具，否则对乙酰氨基酚日剂量超标可导致急性药物性肝衰竭与肝坏死！",
                "guideline": "《中成药临床应用指导原则与中西药联合安全规范》",
            })

        # Rule 14: Antiviral Valacyclovir in renal impairment
        has_antiviral = any(x in meds_text for x in ["伐昔洛韦", "阿昔洛韦"])
        if has_antiviral and egfr is not None:
            try:
                egfr_val = float(egfr)
                if egfr_val < 50:
                    alerts.append({
                        "ruleId": "RULE-HERPES-VALACYCLOVIR-RENAL",
                        "severity": "YELLOW",
                        "title": "肾功能减退患者抗疱疹病毒药物剂量调整预警",
                        "message": f"患者 eGFR = {egfr_val} ml/min/1.73m² (< 50)，伐昔洛韦/阿昔洛韦主要经肾脏排泄，高剂量易析出肾小管针状结晶加重急性肾损伤。必须根据肾功能减量（eGFR 30~49 改为 1000mg q12h；eGFR 10~29 改为 1000mg q24h；<10 改为 500mg q24h）。",
                        "guideline": "《中国带状疱疹诊疗专家共识（2023版）》",
                    })
            except (ValueError, TypeError):
                pass

        # Rule 15: Triptans in Ischemic Cardiovascular/Cerebrovascular Disease
        has_triptan = any(x in meds_text for x in ["曲普坦", "佐米曲普坦", "利扎曲普坦", "舒马曲普坦"])
        history_text = str(profile.get("history", "") or profile.get("disease", "") or "").lower()
        has_cvd = any(k in history_text for k in ["冠心病", "心绞痛", "心肌梗死", "脑梗", "脑卒中", "tia", "缺血性", "高血压"]) or bool(profile.get("has_cad") or profile.get("has_stroke"))
        if has_triptan and has_cvd:
            alerts.append({
                "ruleId": "RULE-MIGR-TRIPTAN-CARDIOVASCULAR",
                "severity": "RED",
                "title": "缺血性心脑血管疾病严禁使用曲普坦类",
                "message": "曲普坦类具有强效外周及冠状动脉收缩作用，患有冠心病、心绞痛、心肌梗死史、脑卒中/TIA 或未控制高血压者绝对禁用！可诱发严重冠脉痉挛导致心肌梗死或心律失常猝死。",
                "guideline": "《中国偏头痛诊治指南（2022版）》",
            })

        # Rule 16: Bisphosphonates in Severe Renal Impairment (eGFR < 35)
        has_bisphosphonate = any(x in meds_text for x in ["阿仑膦酸", "唑来膦酸", "利塞膦酸", "依班膦酸"])
        if has_bisphosphonate and egfr is not None:
            try:
                egfr_val = float(egfr)
                if egfr_val < 35:
                    alerts.append({
                        "ruleId": "RULE-OSTEO-BISPHOSPHONATE-RENAL",
                        "severity": "RED",
                        "title": "重度肾功能不全禁用双膦酸盐类抗骨吸收药物",
                        "message": f"患者 eGFR = {egfr_val} ml/min/1.73m² (< 35)，双膦酸盐完全经肾小球滤过与肾小管排泄，重度肾损伤蓄积可诱发急性肾小管坏死及不可逆肾衰竭！绝对禁用，推荐换用地舒单抗或活性维生素D。",
                        "guideline": "《原发性骨质疏松症诊疗指南（2022）》",
                    })
            except (ValueError, TypeError):
                pass

        # Rule 17: Stimulant laxative overuse alert
        has_stimulant_lax = any(x in meds_text for x in ["番泻叶", "大黄苏打", "比沙可啶", "酚酞", "芦荟胶囊"])
        if has_stimulant_lax:
            alerts.append({
                "ruleId": "RULE-CONSTIP-STIMULANT-LAXATIVE",
                "severity": "YELLOW",
                "title": "刺激性泻药长期使用警戒（结肠黑变病与神经损伤风险）",
                "message": "番泻叶、比沙可啶等刺激性泻药仅限短期（≤1周）临时备用；长期大剂量使用可导致结肠平滑肌肌间神经丛变性坏死及结肠黑变病，门诊慢性便秘推荐换用渗透性（聚乙二醇/乳果糖）或容积性泻药。",
                "guideline": "《慢性便秘基层诊疗指南（2020年）》",
            })

        # Rule 18: Pure dry eye with antibiotic eye drops misuse
        is_dry_eye = any(k in str(profile.get("diagnosis", "")).lower() for k in ["干眼", "角结膜干燥"])
        has_abx_eyedrop = any(x in meds_text for x in ["左氧氟沙星滴眼液", "妥布霉素滴眼液", "氯霉素滴眼液", "加替沙星滴眼液"])
        if is_dry_eye and has_abx_eyedrop:
            alerts.append({
                "ruleId": "RULE-DRYEYE-ANTIBIOTIC-MISUSE",
                "severity": "RED",
                "title": "单纯干眼症严禁经验性滥用抗生素滴眼液",
                "message": "单纯干眼症系非感染性眼表泪膜稳态破坏，无化脓性感染证据严禁使用抗生素眼药水！不仅无效，而且会破坏眼表正常微生物群并诱发耐药性与角膜上皮毒性。",
                "guideline": "《中国干眼专家共识（2020年）》",
            })

        # Rule 19: Pediatric Macrolide + QT prolongation drugs / QT history
        has_macrolide = any(x in meds_text for x in ["阿奇霉素", "克拉霉素", "红霉素", "罗红霉素"])
        has_qt_drugs = any(x in meds_text for x in ["多潘立酮", "昂丹司琼", "西沙必利", "胺碘酮", "索他洛尔", "喹尼丁", "特非那定"])
        has_qt_risk = any(k in history_text for k in ["qt延长", "长qt", "心律失常", "尖端扭转"]) or bool(profile.get("has_long_qt"))
        if has_macrolide and (has_qt_drugs or has_qt_risk):
            alerts.append({
                "ruleId": "RULE-PED-MACROLIDE-QT",
                "severity": "RED",
                "title": "大环内酯类合并延长 QT 间期药物/心律失常风险强阻断",
                "message": "阿奇霉素等大环内酯类药物可抑制心肌复极延迟心电图 QT 间期。合用多潘立酮/昂丹司琼或心律失常体质者可协同显著延长 QTc，极易诱发致命性尖端扭转型室性心动过速（TdP）及心室颤动！绝对禁止联合使用。",
                "guideline": "《儿童肺炎支原体肺炎诊疗指南（2023年版）》与国家药监局大环内酯类心脏安全性警示",
            })

        # Rule 20: Pediatric Tetracyclines (<8 years off-label boundary)
        has_tetracycline = any(x in meds_text for x in ["多西环素", "米诺环素", "四环素", "美他环素"])
        if has_tetracycline and age is not None:
            try:
                age_val = int(age)
                if age_val < 8:
                    has_consent = bool(profile.get("off_label_consent") or profile.get("informed_consent"))
                    if has_consent:
                        alerts.append({
                            "ruleId": "RULE-PED-TETRACYCLINE-AGE",
                            "severity": "YELLOW",
                            "title": "8岁以下儿童使用新型四环素类超说明书告知与监测",
                            "message": f"患者年龄 {age_val} 岁 (<8)，多西环素/米诺环素用于大环内酯耐药重症支原体肺炎属于超说明书用药。已记录监护人知情同意，请严格按照指南疗程用药，并密切监测牙齿黄染釉质发育及胃肠道反应。",
                            "guideline": "《儿童肺炎支原体肺炎诊疗指南（2023年版）》",
                        })
                    else:
                        alerts.append({
                            "ruleId": "RULE-PED-TETRACYCLINE-AGE",
                            "severity": "RED",
                            "title": "8岁以下儿童禁用四环素类（牙釉质发育不全与骨生长发育毒性）",
                            "message": f"患者年龄 {age_val} 岁 (<8)，四环素类与钙离子螯合沉积于牙齿和骨骼，可导致永久性牙齿黄染、牙釉质发育不良及骨生长抑制！除耐药重症充分知情同意外，常规门诊严禁处方。",
                            "guideline": "《儿童肺炎支原体肺炎诊疗指南（2023年版）》",
                        })
            except (ValueError, TypeError):
                pass

        # Rule 21: Pediatric Asthma - Avoid oral SABA monotherapy or systemic steroids long-term
        diag_text = str(profile.get("diagnosis", "")).lower()
        is_asthma = any(k in diag_text for k in ["哮喘", "喘息"]) or any(k in history_text for k in ["哮喘"])
        has_oral_saba = any(x in meds_text for x in ["沙丁胺醇片", "沙丁胺醇胶囊", "特布他林片"])
        has_oral_steroid = any(x in meds_text for x in ["泼尼松片", "强的松片", "地塞米松片", "甲泼尼龙片"])
        if is_asthma and (has_oral_saba or has_oral_steroid) and age is not None:
            try:
                if int(age) < 18:
                    alerts.append({
                        "ruleId": "RULE-PED-ASTHMA-ORAL-STEROID",
                        "severity": "RED",
                        "title": "儿童哮喘维持期严禁常规口服短效舒张剂或无指征口服激素",
                        "message": "儿童支气管哮喘控制基石为吸入性糖皮质激素（ICS），严禁长期规律单用口服沙丁胺醇等 SABA（可引起受体下调和气道反应性反跳增加死亡风险），且严禁常规门诊长期口服泼尼松等全身激素作为维持治疗（严重抑制骨骼生长发育及肾上腺皮质轴）！",
                        "guideline": "《儿童支气管哮喘诊断与防治指南（2020年版）》",
                    })
            except (ValueError, TypeError):
                pass

        # Rule 22: Clopidogrel + CYP2C19-inhibiting PPIs (Omeprazole/Esomeprazole)
        has_clopidogrel = any(x in meds_text for x in ["氯吡格雷", "波立维", "泰嘉"])
        has_cyp2c19_ppi = any(x in meds_text for x in ["奥美拉唑", "艾司奥美拉唑", "埃索美拉唑"])
        if has_clopidogrel and has_cyp2c19_ppi:
            alerts.append({
                "ruleId": "RULE-GERD-PPI-CLOPIDOGREL",
                "severity": "RED",
                "title": "严禁氯吡格雷联合奥美拉唑/艾司奥美拉唑（支架内急性血栓风险）",
                "message": "奥美拉唑及艾司奥美拉唑对肝药酶 CYP2C19 具有强竞争性抑制作用，与氯吡格雷合用时阻断其转化为活性抗血小板代谢产物，显著增加心肌梗死、支架内血栓及心血管死亡风险！绝对禁止联合处方，推荐换用对 CYP2C19 影响极小的雷贝拉唑或泮托拉唑。",
                "guideline": "《2020年中国胃食管反流病专家共识》与国家药监局氯吡格雷安全警示",
            })

        # Rule 23: Statin + Gemfibrozil (Severe Rhabdomyolysis)
        has_statin = any(x in meds_text for x in ["他汀", "阿托伐他汀", "瑞舒伐他汀", "辛伐他汀", "普伐他汀", "氟伐他汀", "匹伐他汀"])
        has_gemfibrozil = any(x in meds_text for x in ["吉非罗齐", "诺衡"])
        if has_statin and has_gemfibrozil:
            alerts.append({
                "ruleId": "RULE-LIPID-STATIN-GEMFIBROZIL",
                "severity": "RED",
                "title": "致命横纹肌溶解：严禁他汀类与吉非罗齐联合处方",
                "message": "吉非罗齐强效抑制他汀类药物的葡萄糖醛酸化清除代谢途径，使他汀血药浓度急剧暴增数倍，诱发致死性急性横纹肌溶解综合征、肌红蛋白尿及急性肾衰竭！绝对禁止联合使用，若高甘油三酯血症需联用贝特类首选非诺贝特。",
                "guideline": "《中国血脂管理指南（2023年）》",
            })

        # Rule 24: Nitrofurantoin in severe renal impairment (eGFR < 30)
        has_nitrofurantoin = any(x in meds_text for x in ["呋喃妥因", "呋喃咀啶"])
        if has_nitrofurantoin and egfr is not None:
            try:
                egfr_val = float(egfr)
                if egfr_val < 30:
                    alerts.append({
                        "ruleId": "RULE-UTI-NITROFURANTOIN-RENAL",
                        "severity": "RED",
                        "title": "重度肾功能不全禁用呋喃妥因（治疗无效与神经肺毒性）",
                        "message": f"患者 eGFR = {egfr_val} ml/min/1.73m² (< 30)，呋喃妥因无法正常滤过排泄至尿液导致尿液杀菌浓度不足（治疗无效），且药物在血液组织中严重蓄积可诱发不可逆外周神经病变与严重肺纤维化毒性！绝对禁用，推荐换用头孢克肟等药物。",
                        "guideline": "《尿路感染基层合理用药指南（2021年）》",
                    })
            except (ValueError, TypeError):
                pass

        # Rule 25: Statin in active hepatic disease or ALT/AST > 3x ULN
        is_active_hepatic = any(k in history_text for k in ["活动性肝炎", "肝衰竭", "失代偿期肝硬化", "肝功能衰竭"]) or bool(profile.get("alt_above_3x") or profile.get("ast_above_3x"))
        alt_val = profile.get("alt")
        alt_high = False
        if alt_val is not None:
            try:
                alt_high = float(alt_val) >= 120
            except (ValueError, TypeError):
                pass
        if has_statin and (is_active_hepatic or alt_high):
            alerts.append({
                "ruleId": "RULE-LIPID-STATIN-HEPATIC",
                "severity": "RED",
                "title": "活动性肝病或转氨酶显著升高禁用他汀类",
                "message": "患者存在活动性肝病或血清转氨酶 ALT/AST 持续升高达正常上限 3 倍以上，此时开具他汀类药物可加剧急性肝细胞损伤与药物性肝衰竭！严禁处方全量他汀，须暂停用药并积极保肝复查。",
                "guideline": "《中国血脂管理指南（2023年）》",
            })

        # Rule 26: Pregnancy + Oral Fluconazole (Teratogenicity & Spontaneous Abortion)
        has_fluconazole = any(x in meds_text for x in ["氟康唑", "大扶康"])
        if is_pregnant and has_fluconazole:
            alerts.append({
                "ruleId": "RULE-PREGNANCY-ORAL-FLUCONAZOLE",
                "severity": "RED",
                "title": "妊娠期严禁口服氟康唑（胎儿先天畸形与自发流产风险）",
                "message": "流行病学研究证实妊娠早期系统暴露于氟康唑可显著增加胎儿复杂先天性心脏畸形、颅面畸形及自然流产风险！妊娠期外阴阴道假丝酵母菌病绝对禁用口服氟康唑，推荐选用局部克霉唑阴道栓。",
                "guideline": "《阴道炎症诊断与治疗规范（2021版）》与国家药监局氟康唑妊娠安全性警示",
            })

        # Rule 27: Levothyroxine + Multivalent Cation Chelation (Calcium / Iron / Aluminum)
        has_lt4 = any(x in meds_text for x in ["左甲状腺素", "优甲乐", "雷替斯"])
        has_chelating_metals = any(x in meds_text for x in ["碳酸钙", "醋酸钙", "硫酸亚铁", "富马酸亚铁", "铝碳酸镁", "氢氧化铝"])
        if has_lt4 and has_chelating_metals:
            alerts.append({
                "ruleId": "RULE-LEVOTHYROXINE-CHELATION",
                "severity": "YELLOW",
                "title": "左甲状腺素钠与钙/铁/铝制剂螯合吸收障碍预警",
                "message": "碳酸钙、硫酸亚铁及铝碳酸镁等多价阳离子在胃肠道与左甲状腺素强烈螯合形成不溶性沉淀，导致左甲状腺素生物利用度下降超50%引起甲减控制失败！两类药物服用时间必须间隔至少 4 小时以上（建议左甲状腺素清晨空腹服用，钙铁铝剂改在午餐或晚餐后）。",
                "guideline": "《成人甲状腺功能减退症诊治指南》",
            })

        # Rule 28: Levothyroxine in elderly or CAD patient - Avoid large starting dose
        has_cad_history = any(k in history_text for k in ["冠心病", "心绞痛", "心肌梗死", "心肌缺血", "支架"]) or bool(profile.get("has_cad"))
        is_elderly = False
        if age is not None:
            try:
                is_elderly = int(age) >= 65
            except (ValueError, TypeError):
                pass
        has_high_dose_lt4 = any(x in meds_text for x in ["左甲状腺素钠片 50μg", "左甲状腺素钠片 100μg", "优甲乐 50μg", "优甲乐 100μg", "左甲状腺素钠片 75μg"])
        if has_lt4 and (has_cad_history or is_elderly) and (has_high_dose_lt4 or bool(profile.get("lt4_dose_above_25"))):
            alerts.append({
                "ruleId": "RULE-THYROID-CAD-DOSE",
                "severity": "RED",
                "title": "冠心病或高龄患者左甲状腺素严禁大剂量直接起始",
                "message": "患者伴有冠心病缺血病史或高龄 (>=65岁)，甲状腺激素可急剧增加心肌做功与耗氧量，大剂量（>=50μg/d）直接起始极易诱发急性心绞痛、心肌梗死或致死性心律失常！指南强制要求必须从超小剂量（12.5~25μg/d）起始、每2~4周缓慢滴定。",
                "guideline": "《成人甲状腺功能减退症诊治指南》",
            })

        # Rule 29: Penicillin Allergy + Penicillins
        allergy_text = str(profile.get("allergy", "") or profile.get("allergies", "") or "").lower()
        has_penicillin_allergy = any(k in allergy_text for k in ["青霉素", "阿莫西林", "penicillin"]) or bool(profile.get("penicillin_allergy"))
        has_penicillin_drug = any(x in meds_text for x in ["阿莫西林", "青霉素", "氨苄西林", "哌拉西林", "舒巴坦"])
        if has_penicillin_allergy and has_penicillin_drug:
            alerts.append({
                "ruleId": "RULE-ALLERGY-PENICILLIN",
                "severity": "RED",
                "title": "青霉素过敏史患者严禁使用青霉素类药物（致死性过敏性休克风险）",
                "message": "患者明确记录有青霉素过敏史或皮试阳性，严禁处方阿莫西林或青霉素类药物！强行使用可诱发急性喉头水肿、支气管痉挛及严重过敏性休克致死！推荐换用头孢菌素或大环内酯类。",
                "guideline": "《急性咽峡炎/扁桃体炎基层诊疗指南（2020年）》与国家药典临床用药须知",
            })






        return {
            "is_safe": len([a for a in alerts if a["severity"] == "RED"]) == 0,
            "total_alerts": len(alerts),
            "red_count": len([a for a in alerts if a["severity"] == "RED"]),
            "yellow_count": len([a for a in alerts if a["severity"] == "YELLOW"]),
            "alerts": alerts,
        }

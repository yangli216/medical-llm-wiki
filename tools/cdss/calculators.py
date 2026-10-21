"""
Clinical Calculator Micro-Engine for Medical LLM Wiki & CDSS.
Provides pure Python, zero-external-dependency, rigorously validated
clinical score and laboratory clearance calculators aligned with CMA/NHC guidelines.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


class ClinicalCalculatorRegistry:
    """Registry and executor for medical quantitative calculators."""

    @classmethod
    def calculate(cls, calculator_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches calculation by calculator identifier."""
        name = calculator_name.strip().lower().replace("-", "_")
        dispatch = {
            "cha2ds2_vasc": cls.calc_cha2ds2_vasc,
            "has_bled": cls.calc_has_bled,
            "curb_65": cls.calc_curb_65,
            "centor": cls.calc_centor,
            "centor_mcisaac": cls.calc_centor,
            "egfr_ckd_epi": cls.calc_egfr_ckd_epi,
            "cockcroft_gault": cls.calc_cockcroft_gault,
            "renal_clearance": cls.calc_renal_clearance,
            "child_pugh": cls.calc_child_pugh,
            "pediatric_fluid": cls.calc_pediatric_fluid,
            "alvarado": cls.calc_alvarado,
            "alvarado_score": cls.calc_alvarado,
            "abcd2": cls.calc_abcd2,
            "abcd2_score": cls.calc_abcd2,
            "wells": cls.calc_wells_pe,
            "wells_pe": cls.calc_wells_pe,
            "wells_score": cls.calc_wells_pe,
            "mmrc": cls.calc_mmrc,
            "mmrc_score": cls.calc_mmrc,
            "crb_65": cls.calc_crb_65,
            "bmi": cls.calc_bmi_obesity,
            "bmi_obesity": cls.calc_bmi_obesity,
            "act": cls.calc_act_score,
            "act_score": cls.calc_act_score,
            "ganzoni": cls.calc_ganzoni_iron,
            "ganzoni_iron": cls.calc_ganzoni_iron,
            "iron_deficit": cls.calc_ganzoni_iron,
            "burch_wartofsky": cls.calc_burch_wartofsky_thyroid_storm,
            "bwps": cls.calc_burch_wartofsky_thyroid_storm,
            "thyroid_storm": cls.calc_burch_wartofsky_thyroid_storm,
        }
        fn = dispatch.get(name)
        if not fn:
            raise ValueError(f"Unknown calculator '{calculator_name}'. Supported: {list(dispatch.keys())}")
        return fn(params)

    # -------------------------------------------------------------------------
    # 1. CHA2DS2-VASc: 非瓣膜性房颤卒中风险评估
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_cha2ds2_vasc(p: Dict[str, Any]) -> Dict[str, Any]:
        age = int(p.get("age", 0))
        is_female = bool(p.get("gender") in ("女", "female", "F") or p.get("is_female"))
        has_chf = bool(p.get("chf") or p.get("heart_failure") or p.get("lvef_le_40"))
        has_htn = bool(p.get("htn") or p.get("hypertension"))
        has_dm = bool(p.get("dm") or p.get("diabetes"))
        has_stroke = bool(p.get("stroke") or p.get("tia") or p.get("thromboembolism"))
        has_vascular = bool(p.get("vascular") or p.get("mi") or p.get("pad") or p.get("aortic_plaque"))

        score = 0
        details = []

        if has_chf:
            score += 1
            details.append("充血性心力衰竭 / LVEF≤40% (+1)")
        if has_htn:
            score += 1
            details.append("高血压史 (+1)")
        if age >= 75:
            score += 2
            details.append("年龄 ≥ 75岁 (+2)")
        elif age >= 65:
            score += 1
            details.append("年龄 65～74岁 (+1)")
        if has_dm:
            score += 1
            details.append("糖尿病史 (+1)")
        if has_stroke:
            score += 2
            details.append("脑卒中 / TIA / 动脉血栓栓塞史 (+2)")
        if has_vascular:
            score += 1
            details.append("血管疾病 (陈旧性心梗/外周动脉疾病/主动脉斑块) (+1)")
        if is_female:
            score += 1
            details.append("女性性别 (+1)")

        # Recommendation logic according to CMA 2024 / ESC guidelines
        if is_female:
            if score >= 3:
                risk_level = "HIGH"
                recommendation = "强烈推荐长期口服抗凝药物 (I类推荐，首选新型口服抗凝药 DOACs 如利伐沙班、达比加群，或华法林)。"
            elif score == 2:
                risk_level = "INTERMEDIATE"
                recommendation = "考虑口服抗凝治疗 (IIa类推荐，权衡获益与出血风险)。"
            else:
                risk_level = "LOW"
                recommendation = "卒中低危，不建议口服抗凝或抗血小板治疗。"
        else:
            if score >= 2:
                risk_level = "HIGH"
                recommendation = "强烈推荐长期口服抗凝药物 (I类推荐，首选 DOACs 如利伐沙班、达比加群，或华法林)。"
            elif score == 1:
                risk_level = "INTERMEDIATE"
                recommendation = "考虑口服抗凝治疗 (IIa类推荐，权衡获益与出血风险)。"
            else:
                risk_level = "LOW"
                recommendation = "卒中极低危，不建议口服抗凝或抗血小板治疗。"

        return {
            "calculator": "CHA2DS2-VASc",
            "score": score,
            "riskLevel": risk_level,
            "recommendation": recommendation,
            "details": details,
            "guideline": "《中国心力衰竭诊断和治疗指南（2024）》及《心房颤动抗凝治疗中国专家共识》",
        }

    # -------------------------------------------------------------------------
    # 2. HAS-BLED: 房颤抗凝出血风险评估
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_has_bled(p: Dict[str, Any]) -> Dict[str, Any]:
        age = int(p.get("age", 0))
        has_htn = bool(p.get("uncontrolled_htn") or p.get("sbp_gt_160"))
        has_renal = bool(p.get("renal_disease") or p.get("dialysis") or p.get("transplant") or p.get("cr_gt_200"))
        has_liver = bool(p.get("liver_disease") or p.get("cirrhosis") or p.get("bili_gt_2x") or p.get("ast_alt_gt_3x"))
        has_stroke = bool(p.get("stroke_history"))
        has_bleeding = bool(p.get("bleeding_history") or p.get("anemia"))
        has_labile_inr = bool(p.get("labile_inr"))
        uses_drugs = bool(p.get("antiplatelet") or p.get("nsaids"))
        uses_alcohol = bool(p.get("alcohol_abuse"))

        score = 0
        details = []

        if has_htn:
            score += 1
            details.append("未控制的高血压 (收缩压 > 160 mmHg) (+1)")
        if has_renal:
            score += 1
            details.append("肾功能异常 (透析/移植/Scr>200μmol/L) (+1)")
        if has_liver:
            score += 1
            details.append("肝功能异常 (肝硬化/胆红素>2倍上限/转氨酶>3倍上限) (+1)")
        if has_stroke:
            score += 1
            details.append("卒中病史 (+1)")
        if has_bleeding:
            score += 1
            details.append("出血史或出血体质 / 重度贫血 (+1)")
        if has_labile_inr:
            score += 1
            details.append("INR易变 (使用华法林时TTR<60%) (+1)")
        if age >= 65:
            score += 1
            details.append("高龄 (年龄 ≥ 65岁) (+1)")
        if uses_drugs:
            score += 1
            details.append("联用抗血小板药或NSAIDs (+1)")
        if uses_alcohol:
            score += 1
            details.append("长期大量饮酒 (+1)")

        if score >= 3:
            risk_level = "HIGH_BLEEDING_RISK"
            recommendation = "出血高风险 (得分 ≥ 3分)：必须排查纠正可逆性出血危险因素（如停用NSAIDs、强化降压、戒酒），并密切随访，但高危绝非抗凝绝对禁忌证！"
        else:
            risk_level = "LOW_TO_MODERATE"
            recommendation = "出血低至中度风险：常规抗凝监测即可。"

        return {
            "calculator": "HAS-BLED",
            "score": score,
            "riskLevel": risk_level,
            "recommendation": recommendation,
            "details": details,
            "guideline": "《心房颤动抗凝治疗中国专家共识》",
        }

    # -------------------------------------------------------------------------
    # 3. CURB-65: 社区获得性肺炎 (CAP) 严重度与收治场所
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_curb_65(p: Dict[str, Any]) -> Dict[str, Any]:
        age = int(p.get("age", 0))
        confusion = bool(p.get("confusion") or p.get("altered_mental_state"))
        bun = float(p.get("bun", 0.0))  # mmol/L
        rr = int(p.get("rr", 0) or p.get("respiratory_rate", 0))
        sbp = int(p.get("sbp", 120))
        dbp = int(p.get("dbp", 80))

        score = 0
        details = []

        if confusion:
            score += 1
            details.append("意识障碍 / 新发定向力障碍 (+1)")
        if bun > 7.0:
            score += 1
            details.append(f"尿素氮升高 (BUN={bun} > 7.0 mmol/L) (+1)")
        if rr >= 30:
            score += 1
            details.append(f"呼吸急促 (RR={rr} ≥ 30 次/分) (+1)")
        if sbp < 90 or dbp <= 60:
            score += 1
            details.append(f"低血压 (SBP={sbp}<90 或 DBP={dbp}≤60 mmHg) (+1)")
        if age >= 65:
            score += 1
            details.append(f"高龄 (年龄={age} ≥ 65岁) (+1)")

        if score in (0, 1):
            severity = "LOW"
            disposition = "门诊治疗"
            recommendation = "低危患者，死亡率 < 3%。通常可门诊口服抗菌药物（阿莫西林/克拉维酸钾或口服二代头孢/呼吸喹诺酮），密切随访。"
        elif score == 2:
            severity = "INTERMEDIATE"
            disposition = "住院观察或日间严格监护"
            recommendation = "中度风险，死亡率约 9%。建议短期住院治疗，或在留观室密切监护评估。"
        else:
            severity = "HIGH"
            disposition = "立即收住院 / 评估ICU收治指征"
            recommendation = "重症高危肺炎，死亡率 15%～40%。必须收住院，若合并感染性休克或需机械通气应直接入住 ICU！"

        return {
            "calculator": "CURB-65",
            "score": score,
            "severity": severity,
            "disposition": disposition,
            "recommendation": recommendation,
            "details": details,
            "guideline": "《中国成人社区获得性肺炎诊断和治疗指南》（SRC-CMA-RESP-2016-02）",
        }

    # -------------------------------------------------------------------------
    # 4. Centor / McIsaac: 急性扁桃体炎链球菌感染概率与抗菌决策
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_centor(p: Dict[str, Any]) -> Dict[str, Any]:
        age = int(p.get("age", 25))
        exudate = bool(p.get("tonsil_exudate") or p.get("pus") or p.get("exudate"))
        tender_nodes = bool(p.get("tender_cervical_nodes") or p.get("lymphadenopathy"))
        fever = bool(p.get("fever") or p.get("temp_gt_38") or float(p.get("temp", 0)) > 38.0)
        no_cough = bool(p.get("no_cough") or (p.get("cough") is False))

        score = 0
        details = []

        if exudate:
            score += 1
            details.append("扁桃体红肿伴化脓性渗出 (+1)")
        if tender_nodes:
            score += 1
            details.append("颈前淋巴结肿大伴压痛 (+1)")
        if fever:
            score += 1
            details.append("发热体温 > 38.0℃ (+1)")
        if no_cough:
            score += 1
            details.append("无咳嗽症状 (+1)")

        # McIsaac age adjustment
        if 3 <= age <= 14:
            score += 1
            details.append("年龄 3～14岁 (链球菌高发年龄段) (+1)")
        elif age >= 45:
            score -= 1
            details.append("年龄 ≥ 45岁 (链球菌低发年龄段) (-1)")

        # Probability and guidance
        if score <= 1:
            gas_risk = "< 10%"
            recommendation = "A族链球菌感染概率低，病毒性自限可能大。对症支持治疗，严禁盲目开具抗生素！"
        elif score in (2, 3):
            gas_risk = "15%～30%"
            recommendation = "链球菌中度可疑。强烈建议咽拭子抗原快检 (RADT) 或咽拭子培养；阳性者给予阿莫西林连服满10天。"
        else:
            gas_risk = "> 50%"
            recommendation = "高度提示A族链球菌感染！建议经验性口服阿莫西林足量满10天疗程，彻底阻断风湿热与肾小球肾炎。"

        return {
            "calculator": "Centor-McIsaac",
            "score": score,
            "strepProbability": gas_risk,
            "recommendation": recommendation,
            "details": details,
            "guideline": "《急性咽峡炎/扁桃体炎基层诊疗指南》（SRC-CMA-ENT-2020-02）",
        }

    # -------------------------------------------------------------------------
    # 5. eGFR (2021 CKD-EPI) & Cockcroft-Gault 肾功能与药量校正
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_egfr_ckd_epi(p: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates 2021 CKD-EPI Creatinine equation without race variable."""
        age = int(p.get("age", 50))
        is_female = bool(p.get("gender") in ("女", "female", "F") or p.get("is_female"))
        scr = float(p.get("scr", 0.0) or p.get("creatinine", 0.0))

        # Normalize to mg/dL if provided in μmol/L
        if scr > 25.0:
            scr_mg = scr / 88.4
            scr_umol = scr
        else:
            scr_mg = scr
            scr_umol = scr * 88.4

        if scr_mg <= 0:
            raise ValueError("Serum creatinine must be greater than 0")

        # 2021 CKD-EPI formula
        if is_female:
            k = 0.7
            alpha = -0.241 if scr_mg <= 0.7 else -1.200
            factor = 1.012
        else:
            k = 0.9
            alpha = -0.302 if scr_mg <= 0.9 else -1.200
            factor = 1.0

        egfr = 142.0 * ((scr_mg / k) ** alpha) * (0.9938 ** age) * factor
        egfr = round(egfr, 1)

        # CKD Staging
        if egfr >= 90:
            stage = "CKD G1 (正常或高)"
        elif egfr >= 60:
            stage = "CKD G2 (轻度下降)"
        elif egfr >= 45:
            stage = "CKD G3a (轻到中度下降)"
        elif egfr >= 30:
            stage = "CKD G3b (中到重度下降)"
        elif egfr >= 15:
            stage = "CKD G4 (重度下降)"
        else:
            stage = "CKD G5 (肾衰竭/尿毒症期)"

        # Clinical drug adjustments
        adjustments = []
        if egfr < 30:
            adjustments.append("二甲双胍绝对禁用 (防致死性乳酸酸中毒)")
            adjustments.append("SGLT2抑制剂 (达格列净/恩格列净) 不建议起始用于控糖")
            adjustments.append("大多数口服NSAIDs (布洛芬/双氯芬酸) 绝对禁用")
            adjustments.append("直接口服抗凝药 (利伐沙班/达比加群) 禁用或极端谨慎减量")
        elif egfr < 45:
            adjustments.append("二甲双胍每日最大剂量严格限制在 500～1000mg 以内")
            adjustments.append("利伐沙班减量至 15mg qd")
        elif egfr < 60:
            adjustments.append("避免长期大剂量使用肾毒性药物与含造影剂检查")

        return {
            "calculator": "eGFR (2021 CKD-EPI)",
            "eGFR": egfr,
            "unit": "mL/min/1.73m²",
            "scr_umol": round(scr_umol, 1),
            "scr_mg": round(scr_mg, 2),
            "ckdStage": stage,
            "drugAdjustments": adjustments,
            "guideline": "《中国慢性肾脏病早期筛查、诊断及治疗临床实践指南》（SRC-CMA-NEPH-2024-01）",
        }

    @staticmethod
    def calc_cockcroft_gault(p: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates Cockcroft-Gault Creatinine Clearance (CrCl) for drug monograph dosing."""
        age = int(p.get("age", 50))
        is_female = bool(p.get("gender") in ("女", "female", "F") or p.get("is_female"))
        weight = float(p.get("weight", 65.0) or p.get("weight_kg", 65.0))
        scr = float(p.get("scr", 0.0) or p.get("creatinine", 0.0))

        if scr > 25.0:
            scr_mg = scr / 88.4
        else:
            scr_mg = scr

        if scr_mg <= 0:
            raise ValueError("Serum creatinine must be greater than 0")

        crcl = ((140.0 - age) * weight) / (72.0 * scr_mg)
        if is_female:
            crcl *= 0.85
        crcl = round(crcl, 1)

        return {
            "calculator": "Cockcroft-Gault CrCl",
            "crcl": crcl,
            "unit": "mL/min",
            "weight_kg": weight,
            "is_female": is_female,
            "guideline": "国家药品监督管理局 (NMPA) 官方药品说明书剂量折算标准",
        }

    @classmethod
    def calc_renal_clearance(cls, p: Dict[str, Any]) -> Dict[str, Any]:
        """Combines both 2021 CKD-EPI eGFR and Cockcroft-Gault CrCl."""
        egfr_res = cls.calc_egfr_ckd_epi(p)
        crcl_res = cls.calc_cockcroft_gault(p) if (p.get("weight") or p.get("weight_kg")) else None
        return {
            "calculator": "Renal Clearance Suite",
            "egfr": egfr_res,
            "crcl": crcl_res,
        }

    # -------------------------------------------------------------------------
    # 6. Child-Pugh: 肝硬化肝功能储备评分与分级
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_child_pugh(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates Child-Pugh Score (5-15) and Class (A, B, C)
        Parameters:
        - bili: Total bilirubin (μmol/L)
        - alb: Serum albumin (g/L)
        - inr: INR (or pt_prolong: PT prolongation in seconds)
        - ascites: "none" / "mild" / "moderate_severe"
        - encephalopathy: "none" / "grade_1_2" / "grade_3_4"
        """
        bili = float(p.get("bili") or p.get("tbil") or p.get("bilirubin") or 15.0)
        alb = float(p.get("alb") or p.get("albumin") or 40.0)
        inr = float(p.get("inr", 1.0))
        ascites = str(p.get("ascites", "none")).lower()
        enc = str(p.get("encephalopathy", "none")).lower()

        score = 0
        details = []

        # 1. Bilirubin (μmol/L)
        if bili < 34.0:
            score += 1
            details.append(f"总胆红素={bili} < 34 μmol/L (+1)")
        elif bili <= 51.0:
            score += 2
            details.append(f"总胆红素={bili} 在 34～51 μmol/L (+2)")
        else:
            score += 3
            details.append(f"总胆红素={bili} > 51 μmol/L (+3)")

        # 2. Albumin (g/L)
        if alb > 35.0:
            score += 1
            details.append(f"白蛋白={alb} > 35 g/L (+1)")
        elif alb >= 28.0:
            score += 2
            details.append(f"白蛋白={alb} 在 28～35 g/L (+2)")
        else:
            score += 3
            details.append(f"白蛋白={alb} < 28 g/L (+3)")

        # 3. INR
        if inr < 1.7:
            score += 1
            details.append(f"INR={inr} < 1.7 (+1)")
        elif inr <= 2.3:
            score += 2
            details.append(f"INR={inr} 在 1.7～2.3 (+2)")
        else:
            score += 3
            details.append(f"INR={inr} > 2.3 (+3)")

        # 4. Ascites
        if ascites in ("none", "无", "0"):
            score += 1
            details.append("无腹水 (+1)")
        elif ascites in ("mild", "轻度", "少量", "1"):
            score += 2
            details.append("轻度腹水 (+2)")
        else:
            score += 3
            details.append("中重度/大量腹水 (+3)")

        # 5. Encephalopathy
        if enc in ("none", "无", "0"):
            score += 1
            details.append("无肝性脑病 (+1)")
        elif enc in ("grade_1_2", "1-2级", "轻度", "1", "2"):
            score += 2
            details.append("1～2级肝性脑病 (+2)")
        else:
            score += 3
            details.append("3～4级严重肝性脑病 (+3)")

        # Classification
        if score <= 6:
            grade = "A 级"
            prognosis = "肝功能代偿良好，手术及药物耐受性优良。"
        elif score <= 9:
            grade = "B 级"
            prognosis = "肝功能显著受损，需严谨权衡肝毒性药物及减量口服药物。"
        else:
            grade = "C 级"
            prognosis = "肝功能严重失代偿，死亡率高，禁绝绝大多数中重度肝代谢药物！"

        return {
            "calculator": "Child-Pugh",
            "score": score,
            "grade": grade,
            "prognosis": prognosis,
            "details": details,
            "guideline": "《原发性肝癌诊疗指南（2024年版）》（SRC-NHC-ONC-2024-01）",
        }

    # -------------------------------------------------------------------------
    # 7. Pediatric Fluid: 儿童脱水与补液量估算
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_pediatric_fluid(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        Estimates pediatric dehydration fluid deficit and Holliday-Segar maintenance.
        Parameters:
        - weight_kg: Child weight in kg
        - dehydration: "mild" (3～5%) / "moderate" (6～9%) / "severe" (≥10%)
        """
        wt = float(p.get("weight_kg", 0.0) or p.get("weight", 0.0))
        if wt <= 0:
            raise ValueError("Child weight must be positive")

        dehydration = str(p.get("dehydration", "mild")).lower()

        # Maintenance requirement (Holliday-Segar method)
        if wt <= 10.0:
            maint = wt * 100.0
        elif wt <= 20.0:
            maint = 1000.0 + (wt - 10.0) * 50.0
        else:
            maint = 1500.0 + (wt - 20.0) * 20.0

        # Deficit calculation
        if dehydration in ("mild", "轻度"):
            deficit_rate = 50.0  # ml/kg
            degree = "轻度脱水 (丢失体重大约 3%～5%)"
            ors_rate = "首选低渗口服补液盐 (ORS-III)，前4小时按 50 mL/kg 少量多次口服"
        elif dehydration in ("moderate", "中度"):
            deficit_rate = 80.0  # ml/kg
            degree = "中度脱水 (丢失体重大约 6%～9%)"
            ors_rate = "首选 ORS-III 补液，前4小时按 80～100 mL/kg 口服；若频繁剧吐则转静脉补液"
        else:
            deficit_rate = 110.0  # ml/kg
            degree = "重度脱水 (丢失体重 ≥ 10%)"
            ors_rate = "【急危重症警告】：重度脱水常伴低血容量休克，绝对禁止单纯口服！立即建立静脉通路，首剂生理盐水 20 mL/kg 在 30～60 分钟内快速扩容！"

        total_deficit = round(wt * deficit_rate, 0)
        daily_total = round(maint + total_deficit, 0)

        return {
            "calculator": "Pediatric Fluid Deficit",
            "weight_kg": wt,
            "dehydrationDegree": degree,
            "maintenance24h_ml": round(maint, 0),
            "deficitVolume_ml": total_deficit,
            "estimated24hTotal_ml": daily_total,
            "rehydrationPlan": ors_rate,
            "guideline": "《中国儿童急性感染性腹泻病临床实践指南（2022）》（SRC-CMA-PED-2022-01）",
        }

    # -------------------------------------------------------------------------
    # 11. Alvarado 评分: 急性阑尾炎临床危险评估与手术指征分层
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_alvarado(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates Alvarado score (MANTRELS) for acute appendicitis evaluation (0～10 points).
        """
        has_migratory = bool(p.get("migratory_pain") or p.get("migration") or p.get("migratory_rlq_pain"))
        has_anorexia = bool(p.get("anorexia") or p.get("loss_of_appetite"))
        has_nausea = bool(p.get("nausea") or p.get("vomiting") or p.get("nausea_vomiting"))
        has_rlq_tenderness = bool(p.get("rlq_tenderness") or p.get("tenderness_rlq") or p.get("mcburney_tenderness"))
        has_rebound = bool(p.get("rebound_tenderness") or p.get("blumberg_sign") or p.get("rebound"))

        # Temperature
        temp_val = float(p.get("temp", 0.0) or p.get("temperature", 0.0) or p.get("temp_c", 0.0))
        has_fever = bool(p.get("fever") or (temp_val >= 37.3))

        # WBC
        wbc_val = float(p.get("wbc", 0.0) or p.get("leukocyte", 0.0))
        has_leukocytosis = bool(p.get("leukocytosis") or (wbc_val >= 10.0))

        # Neutrophil shift
        neut_val = float(p.get("neut_pct", 0.0) or p.get("neutrophil_pct", 0.0) or p.get("neutrophil_ratio", 0.0))
        has_shift = bool(p.get("neutrophil_shift") or p.get("shift_to_left") or (neut_val >= 75.0))

        score = 0
        details = []

        if has_migratory:
            score += 1
            details.append("转移性右下腹痛 (+1)")
        if has_anorexia:
            score += 1
            details.append("食欲减退 / 拒食 (+1)")
        if has_nausea:
            score += 1
            details.append("恶心或呕吐 (+1)")
        if has_rlq_tenderness:
            score += 2
            details.append("右下腹麦氏点局限压痛 (+2)")
        if has_rebound:
            score += 1
            details.append("腹膜刺激反跳痛 (Blumberg征) (+1)")
        if has_fever:
            score += 1
            details.append("体温升高 ≥ 37.3℃ (+1)")
        if has_leukocytosis:
            score += 2
            details.append("白细胞升高 ≥ 10.0×10^9/L (+2)")
        if has_shift:
            score += 1
            details.append("中性粒细胞核左移 ≥ 75% (+1)")

        if score <= 4:
            stratum = "低危 (极低概率)"
            rec = "急性阑尾炎可能性极小；排查急性胃肠炎、泌尿系结石或肠系膜淋巴结炎；可在门诊留观动态随访。"
        elif score <= 6:
            stratum = "中危 (疑似阑尾炎)"
            rec = "疑似急性阑尾炎；严禁盲目开具强效麻醉镇痛药掩盖体征；立即行全腹低剂量CT或高频彩超，留观复查。"
        else:
            stratum = "高危 (高度拟诊)"
            rec = "高度拟诊急性阑尾炎；严格禁食禁水、严禁导泻灌肠；立即启动急诊普通外科急会诊，评估急诊腹腔镜手术。"

        return {
            "calculator": "Alvarado Score",
            "score": score,
            "maxScore": 10,
            "riskStratum": stratum,
            "recommendation": rec,
            "positiveCriteria": details,
            "guideline": "《国家卫生健康委急性阑尾炎临床路径与中华医学会外科学诊疗规范》（SRC-CSES-APP-2023-01）",
        }

    # -------------------------------------------------------------------------
    # 12. ABCD2 评分: 短暂性脑缺血发作 (TIA) 早期卒中风险预测
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_abcd2(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates ABCD2 score for TIA 48-hour stroke risk prediction (0～7 points).
        """
        age = int(p.get("age", 0))
        sbp = float(p.get("sbp", 0.0) or p.get("systolic_bp", 0.0))
        dbp = float(p.get("dbp", 0.0) or p.get("diastolic_bp", 0.0))
        has_bp_high = bool(p.get("bp_high") or p.get("hypertension") or (sbp >= 140.0) or (dbp >= 90.0))

        feat = str(p.get("clinical_features", "") or p.get("features", "")).lower()
        has_unilateral_weakness = bool("weakness" in feat or "偏瘫" in feat or "无力" in feat or p.get("unilateral_weakness"))
        has_speech_impairment = bool("speech" in feat or "言语" in feat or "失语" in feat or p.get("speech_impairment"))

        dur_min = int(p.get("duration_minutes", 0) or p.get("duration_min", 0) or p.get("duration", 0))
        has_diabetes = bool(p.get("dm") or p.get("diabetes") or p.get("diabetes_mellitus"))

        score = 0
        details = []

        if age >= 60:
            score += 1
            details.append("年龄 ≥ 60 岁 (+1)")
        if has_bp_high:
            score += 1
            details.append("首测血压 ≥ 140/90 mmHg (+1)")

        if has_unilateral_weakness:
            score += 2
            details.append("单侧肢体无力 (+2)")
        elif has_speech_impairment:
            score += 1
            details.append("单纯言语功能障碍不伴无力 (+1)")

        if dur_min >= 60:
            score += 2
            details.append("症状持续时间 ≥ 60 分钟 (+2)")
        elif dur_min >= 10:
            score += 1
            details.append("症状持续时间 10～59 分钟 (+1)")

        if has_diabetes:
            score += 1
            details.append("合并糖尿病史 (+1)")

        if score <= 3:
            stratum = "低危 (48小时卒中风险 约1.0%)"
            rec = "门诊急查头颅MRI-DWI与颈动脉彩超；启动阿司匹林单抗与强化他汀降脂治疗。"
        elif score <= 5:
            stratum = "中危 (48小时卒中风险 约4.1%)"
            rec = "急诊绿色通道留观；发病24小时内启动 CHANCE 双联抗血小板治疗（阿司匹林+氯吡格雷 21天疗程）。"
        else:
            stratum = "高危 (48小时卒中风险 约8.1%，7天达11.7%)"
            rec = "【急危重症预警】：紧急收住神经内科卒中单元；发病24小时内立即给予阿司匹林+氯吡格雷负荷量双抗（维持21天）及强化他汀，急诊血管影像评估。"

        return {
            "calculator": "ABCD2 Score",
            "score": score,
            "maxScore": 7,
            "riskStratum": stratum,
            "recommendation": rec,
            "positiveCriteria": details,
            "guideline": "《中国短暂性脑缺血发作与轻型卒中诊治指南（2020）》（SRC-CMA-NEUR-TIA-2020-01）",
        }

    # -------------------------------------------------------------------------
    # 11. Wells PE: 肺栓塞临床预测概率评分
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_wells_pe(p: Dict[str, Any]) -> Dict[str, Any]:
        has_dvt = bool(p.get("dvt_signs") or p.get("dvt") or p.get("leg_swelling"))
        pe_most_likely = bool(p.get("pe_most_likely") or p.get("pe_likely") or p.get("alternative_less_likely"))
        hr = float(p.get("hr", 0) or p.get("heart_rate", 0))
        recent_surgery = bool(p.get("recent_surgery") or p.get("immobilization") or p.get("bedridden"))
        prior_pe = bool(p.get("prior_pe") or p.get("prior_dvt") or p.get("history_vte"))
        hemoptysis = bool(p.get("hemoptysis") or p.get("bloody_sputum"))
        cancer = bool(p.get("cancer") or p.get("malignancy") or p.get("active_cancer"))

        score = 0.0
        details = []

        if has_dvt:
            score += 3.0
            details.append("深静脉血栓形成 (DVT) 临床症状与体征 (+3.0)")
        if pe_most_likely:
            score += 3.0
            details.append("其他诊断的可能性小于肺栓塞 (+3.0)")
        if hr > 100:
            score += 1.5
            details.append(f"心率 > 100次/分 ({hr:.0f} bpm) (+1.5)")
        if recent_surgery:
            score += 1.5
            details.append("近4周内手术制动或卧床≥3天 (+1.5)")
        if prior_pe:
            score += 1.5
            details.append("既往 DVT 或 PE 病史 (+1.5)")
        if hemoptysis:
            score += 1.0
            details.append("咯血 (+1.0)")
        if cancer:
            score += 1.0
            details.append("活动性恶性肿瘤 (+1.0)")

        # 两分法 (Two-tier)
        pe_likely = (score > 4.0)
        if pe_likely:
            stratum = "高度可能 (PE Likely, 栓塞发生率约 37.1%)"
            rec = "【致死性急症警报】：立即开启急诊绿色通道，跳过单纯D-二聚体排查，紧急安排 CTPA (肺动脉造影) 确诊，并准备启动抗凝治疗！"
            grade = "1A"
        else:
            stratum = "低度/中度可能 (PE Unlikely, 栓塞发生率约 12.1%)"
            rec = "首选急查高敏 D-二聚体定量排查。若 D-二聚体阴性 (<500 μg/L 或年龄调整切点)，可 100% 安全豁免 CTPA 检查；若阳性则进一步安排 CTPA。"
            grade = "1A"

        return {
            "calculator": "Wells PE Score",
            "score": round(score, 1),
            "maxScore": 12.5,
            "peLikely": pe_likely,
            "riskStratum": stratum,
            "recommendation": rec,
            "positiveCriteria": details,
            "grade": grade,
            "guideline": "《诊断学（第9/10版·国家卫健委规划教材）》（SRC-PMPH-DIAG-2024-01）",
        }

    # -------------------------------------------------------------------------
    # 12. mMRC: 改良英国医学研究学会呼吸困难量表与 COPD 分组
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_mmrc(p: Dict[str, Any]) -> Dict[str, Any]:
        grade_val = int(p.get("grade", p.get("mmrc_grade", 0)))
        exacerbations = int(p.get("exacerbations_last_year", 0))
        hospitalizations = int(p.get("hospitalizations_last_year", 0))
        eos = float(p.get("eos_count", 0))

        grade_val = max(0, min(4, grade_val))
        descriptions = {
            0: "0级: 仅在剧烈运动或费力活动时感到呼吸急促",
            1: "1级: 在平地快步行走或微上坡时感到气短",
            2: "2级: 在平地行走比同龄人慢，或平地正常速度需停下休息 (关键分水岭)",
            3: "3级: 在平地行走约100米或数分钟后需停下喘气",
            4: "4级: 因严重气促不能出门，或在穿脱衣服时即出现明显呼吸困难",
        }

        # GOLD ABE 分组
        if hospitalizations >= 1 or exacerbations >= 2:
            gold_group = "E 组 (高加重风险组)"
            if eos >= 300:
                med_rec = "首选三联吸入制剂: ICS + LABA + LAMA (如布地奈德/格隆溴铵/福莫特罗)"
            else:
                med_rec = "首选双支扩剂联合: LABA + LAMA (如噻托溴铵/奥达特罗、乌美溴铵/维兰特罗)"
        elif grade_val >= 2:
            gold_group = "B 组 (高症状/低加重风险组)"
            med_rec = "首选双联长效支扩剂: LABA + LAMA 吸入制剂；严禁单用短效茶碱缓释片"
        else:
            gold_group = "A 组 (低症状/低加重风险组)"
            med_rec = "起始推荐单一长效支气管舒张剂 (LAMA 或 LABA 吸入)"

        return {
            "calculator": "mMRC Dyspnea & GOLD ABE Assessment",
            "mmrcGrade": grade_val,
            "description": descriptions[grade_val],
            "goldGroup": gold_group,
            "treatmentRecommendation": med_rec,
            "grade": "1A",
            "guideline": "《慢性阻塞性肺疾病诊治指南（2021年修订版）》（SRC-CMA-RESP-2021-01）",
        }

    # -------------------------------------------------------------------------
    # 13. CRB-65: 基层门诊快速社区获得性肺炎严重度评分 (无需血生化BUN)
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_crb_65(p: Dict[str, Any]) -> Dict[str, Any]:
        has_confusion = bool(p.get("confusion") or p.get("altered_mental_status"))
        rr = int(p.get("rr", 0) or p.get("respiratory_rate", 0))
        sbp = int(p.get("sbp", 120))
        dbp = int(p.get("dbp", 80))
        age = int(p.get("age", 0))

        score = 0
        details = []

        if has_confusion:
            score += 1
            details.append("新发意识障碍 / 精神错乱 (+1)")
        if rr >= 30:
            score += 1
            details.append(f"呼吸频率 ≥ 30次/分 ({rr} bpm) (+1)")
        if (sbp < 90 and sbp > 0) or (dbp <= 60 and dbp > 0):
            score += 1
            details.append(f"低血压收缩压<90或舒张压≤60 ({sbp}/{dbp} mmHg) (+1)")
        if age >= 65:
            score += 1
            details.append(f"年龄 ≥ 65岁 ({age}岁) (+1)")

        if score == 0:
            stratum = "低危 (死亡率 < 1.2%)"
            place = "门诊口服抗菌药物治疗；居家密切观察症状变化。"
        elif score <= 2:
            stratum = "中危 (死亡率 约 8.2%)"
            place = "建议收住院治疗或急诊留观；密切复查胸片与血氧监测。"
        else:
            stratum = "高危 (死亡率高达 31.3%)"
            place = "【危重症预警】：必须紧急急诊住院；立即评估是否转入重症监护病房 (ICU)！"

        return {
            "calculator": "CRB-65 Outpatient Pneumonia Score",
            "score": score,
            "maxScore": 4,
            "riskStratum": stratum,
            "triageRecommendation": place,
            "positiveCriteria": details,
            "grade": "1A",
            "guideline": "《中国成人社区获得性肺炎诊断和治疗指南》（SRC-CMA-RESP-2016-02）",
        }

    # -------------------------------------------------------------------------
    # 14. BMI & Obesity: 中国成人超重与肥胖症诊断与BMI分级计算器 (2024年版)
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_bmi_obesity(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        中国成人超重与肥胖症诊断与BMI分级计算器
        依据国家卫生健康委办公厅《肥胖症诊疗指南（2024年版）》（国卫办医政函〔2024〕382号）
        """
        try:
            weight = float(p.get("weight") or p.get("weight_kg") or 0.0)
        except (ValueError, TypeError):
            weight = 0.0

        try:
            height = float(p.get("height") or p.get("height_cm") or 0.0)
        except (ValueError, TypeError):
            height = 0.0

        if height > 3.0:
            height_m = height / 100.0
        else:
            height_m = height

        try:
            waist = float(p.get("waist") or p.get("waist_cm") or p.get("waist_circumference") or 0.0)
        except (ValueError, TypeError):
            waist = 0.0

        gender = str(p.get("gender") or "男").strip()
        is_female = gender in ("女", "female", "F") or bool(p.get("is_female"))

        has_comorbidity = bool(
            p.get("htn") or p.get("hypertension") or p.get("高血压") or
            p.get("dm") or p.get("diabetes") or p.get("糖尿病") or
            p.get("dyslipidemia") or p.get("高脂血症") or p.get("血脂异常") or
            p.get("masld") or p.get("nafld") or p.get("脂肪肝") or
            p.get("hyperuricemia") or p.get("gout") or p.get("高尿酸血症") or p.get("痛风") or
            p.get("osas") or p.get("睡眠呼吸暂停") or p.get("cvd")
        )

        if height_m <= 0 or weight <= 0:
            bmi = 0.0
        else:
            bmi = round(weight / (height_m * height_m), 1)

        if bmi < 18.5:
            category = "UNDERWEIGHT"
            category_cn = "体重过低"
            severity = "NONE"
            severity_cn = "营养不良/肌少症风险"
        elif bmi < 24.0:
            category = "NORMAL"
            category_cn = "正常体重"
            severity = "NONE"
            severity_cn = "正常基线范围"
        elif bmi < 28.0:
            category = "OVERWEIGHT"
            category_cn = "超重"
            severity = "PRE_OBESE"
            severity_cn = "超重（肥胖前期）"
        elif bmi < 32.5:
            category = "OBESE"
            category_cn = "轻度肥胖（I度）"
            severity = "CLASS_1"
            severity_cn = "I度肥胖"
        elif bmi < 37.5:
            category = "OBESE"
            category_cn = "中度肥胖（II度）"
            severity = "CLASS_2"
            severity_cn = "II度肥胖"
        elif bmi < 42.5:
            category = "OBESE"
            category_cn = "重度肥胖（III度）"
            severity = "CLASS_3"
            severity_cn = "III度肥胖"
        else:
            category = "OBESE"
            category_cn = "极重度肥胖（IV度）"
            severity = "CLASS_4"
            severity_cn = "IV度极重度肥胖"

        central_obesity = False
        if waist > 0:
            if is_female:
                central_obesity = waist >= 85.0
            else:
                central_obesity = waist >= 90.0

        pharmacotherapy_indicated = (bmi >= 28.0) or (bmi >= 24.0 and (has_comorbidity or central_obesity))
        surgery_indicated = (bmi >= 37.5) or (bmi >= 32.5 and has_comorbidity)

        recommendations = []
        if category == "UNDERWEIGHT":
            recommendations.append("患者体重偏低，建议筛查甲亢、消化道慢性消耗等病因，加强平衡优质营养，禁用减重药物。")
        elif category == "NORMAL":
            if central_obesity:
                recommendations.append("患者BMI处于正常范围，但腰围超标提示中心型（腹型）肥胖，建议增加腰腹核心有氧训练，严禁滥用处方减重药物。")
            else:
                recommendations.append("患者体质指数处于正常基线范围，建议维持健康生活方式，严禁以非医学减重目的开具处方减重药。")
        elif category == "OVERWEIGHT":
            rec = "诊断为超重。基石干预：建议每日减少 500~1000 kcal 能量摄入，每周至少 150 分钟中等强度有氧运动。"
            if pharmacotherapy_indicated:
                rec += " 合并代谢异常或腹型肥胖，若强化生活方式干预 3 个月未达标，可在医师指导下谨慎评估联合口服奥利司他或GLP-1RA药物。"
            recommendations.append(rec)
        else:
            rec = f"诊断为{category_cn}（BMI: {bmi} kg/m²）。启动全程医学营养管理，以 3~6 个月减轻基线体重 5%~10% 为目标。"
            if surgery_indicated:
                rec += " 满足国家卫健委减重与代谢外科手术（LSG/LRYGB）评估指征，建议转诊普外与代谢MDT联合评估。"
            elif pharmacotherapy_indicated:
                rec += " 符合国家卫健委规范化处方药物减重指征（奥利司他胶囊或周制剂司美格鲁肽），用药前必须排除MTC/MEN2及胆汁淤积禁忌。"
            recommendations.append(rec)

        return {
            "calculator": "bmi_obesity",
            "name": "中国成人超重与肥胖症诊断与BMI分级计算器",
            "guideline": "《肥胖症诊疗指南（2024年版）》（国卫办医政函〔2024〕382号）",
            "bmi": bmi,
            "category": category,
            "category_cn": category_cn,
            "severity": severity,
            "severity_cn": severity_cn,
            "waist_cm": waist,
            "central_obesity": central_obesity,
            "pharmacotherapy_indicated": pharmacotherapy_indicated,
            "surgery_indicated": surgery_indicated,
            "recommendation": " ".join(recommendations),
        }

    # -------------------------------------------------------------------------
    # 15. ACT: 哮喘控制测试评分 (Asthma Control Test)
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_act_score(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        哮喘控制测试 (Asthma Control Test, ACT) 评分计算器
        依据《支气管哮喘防治指南（2020年版）》（SRC-CMA-RESP-2020-01）
        5项临床指标，每项 1~5 分，总分 5~25 分。
        """
        q1 = int(p.get("q1") or p.get("activity_limitation") or 5)
        q2 = int(p.get("q2") or p.get("shortness_of_breath") or 5)
        q3 = int(p.get("q3") or p.get("night_waking") or 5)
        q4 = int(p.get("q4") or p.get("reliever_usage") or 5)
        q5 = int(p.get("q5") or p.get("self_assessment") or 5)

        q1 = max(1, min(5, q1))
        q2 = max(1, min(5, q2))
        q3 = max(1, min(5, q3))
        q4 = max(1, min(5, q4))
        q5 = max(1, min(5, q5))

        total_score = q1 + q2 + q3 + q4 + q5

        if total_score == 25:
            control_status = "CONTROLLED"
            control_cn = "完全控制"
            recommendation = "哮喘达到完全控制（25分）。建议维持当前治疗方案；若持续完全控制达到 3 个月以上且肺功能稳定，可在医师指导下谨慎尝试梯度降级（如 ICS 剂量下调 25%～50%）。"
        elif total_score >= 20:
            control_status = "WELL_CONTROLLED"
            control_cn = "良好控制"
            recommendation = "哮喘达到良好控制（20～24分）。偶有轻微症状，大部分日常生活不受限；建议维持当前维持剂量方案，规律随访，定期每 1～3 个月评估肺功能与吸药技术。"
        else:
            control_status = "UNCONTROLLED"
            control_cn = "未控制"
            recommendation = "【预警】哮喘处于未控制状态（<20分）！存在急性加重高危风险。建议：①立即核查患者干粉吸入装置吸气深度与屏气技术；②核查规律吸药依从性与环境过敏原规避；③依从性良好者建议在呼吸专科指导下将治疗阶梯向上提升 1 级（Step-Up）；④若有突发严重喘憋立即启用急救平喘药物。"

        return {
            "calculator": "act_score",
            "name": "哮喘控制测试 (ACT) 评分",
            "score": total_score,
            "maxScore": 25,
            "minScore": 5,
            "controlStatus": control_status,
            "controlStatus_cn": control_cn,
            "subScores": {
                "activity_limitation": q1,
                "shortness_of_breath": q2,
                "night_waking": q3,
                "reliever_usage": q4,
                "self_assessment": q5,
            },
            "recommendation": recommendation,
            "guideline": "《支气管哮喘防治指南（2020年版）》（SRC-CMA-RESP-2020-01）",
        }

    # -------------------------------------------------------------------------
    # 14. Ganzoni 公式: 静脉补铁累积总缺铁量计算引擎
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_ganzoni_iron(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ganzoni 静脉补铁累积总缺铁量测算引擎
        依据《铁缺乏症和缺铁性贫血诊治和预防成人指南（2023年版）》（SRC-CMA-HEMA-2023-01）
        公式: 总缺铁量(mg) = 体重(kg) * (目标Hb - 实际Hb, g/dL) * 2.4 + 储存铁(mg)
        """
        try:
            weight = float(p.get("weight") or p.get("weight_kg") or 60.0)
        except (ValueError, TypeError):
            weight = 60.0

        raw_hb = p.get("hb") or p.get("current_hb") or p.get("hemoglobin") or 70.0
        try:
            raw_hb_val = float(raw_hb)
        except (ValueError, TypeError):
            raw_hb_val = 70.0

        # 支持 g/L 或 g/dL，如果 > 30 视为 g/L 转换为 g/dL
        if raw_hb_val > 30.0:
            actual_hb_g_dl = raw_hb_val / 10.0
            actual_hb_g_l = raw_hb_val
        else:
            actual_hb_g_dl = raw_hb_val
            actual_hb_g_l = raw_hb_val * 10.0

        raw_target = p.get("target_hb") or 15.0
        try:
            target_val = float(raw_target)
        except (ValueError, TypeError):
            target_val = 15.0

        if target_val > 30.0:
            target_hb_g_dl = target_val / 10.0
            target_hb_g_l = target_val
        else:
            target_hb_g_dl = target_val
            target_hb_g_l = target_val * 10.0

        # 储存铁计算 (成人通常设为 500 mg，体重 < 35kg 设为 15 mg/kg)
        if weight >= 35.0:
            default_depot = 500.0
        else:
            default_depot = round(15.0 * weight, 1)

        custom_depot = p.get("iron_depot") or p.get("iron_depot_mg")
        if custom_depot is not None:
            try:
                iron_depot_mg = float(custom_depot)
            except (ValueError, TypeError):
                iron_depot_mg = default_depot
        else:
            iron_depot_mg = default_depot

        hb_delta = max(0.0, target_hb_g_dl - actual_hb_g_dl)
        total_iron_deficit_mg = round(weight * hb_delta * 2.4 + iron_depot_mg, 1)

        # 换算常用静脉制剂支数
        # 1. 蔗糖铁注射液: 100 mg / 5 mL / 支
        ampoules_sucrose_100mg = math.ceil(total_iron_deficit_mg / 100.0) if total_iron_deficit_mg > 0 else 0
        # 2. 羧基麦芽糖铁注射液: 500 mg / 10 mL / 瓶
        vials_fcm_500mg = math.ceil(total_iron_deficit_mg / 500.0) if total_iron_deficit_mg > 0 else 0

        if actual_hb_g_l < 60.0:
            severity = "SEVERE"
            severity_cn = "重度贫血"
        elif actual_hb_g_l < 90.0:
            severity = "MODERATE"
            severity_cn = "中度贫血"
        else:
            severity = "MILD"
            severity_cn = "轻度贫血"

        recommendation = (
            f"患者体重 {weight} kg，实测 Hb {actual_hb_g_l:.1f} g/L（{severity_cn}），目标 Hb {target_hb_g_l:.1f} g/L。"
            f"依据 Ganzoni 公式，计算全疗程累积总需补元素铁 {total_iron_deficit_mg:.1f} mg（含机体储存铁 {iron_depot_mg:.0f} mg）。\n"
            f"静脉制剂换算推荐：\n"
            f"1. 蔗糖铁注射液（100mg/支）：全疗程需 {ampoules_sucrose_100mg} 支。每次 100～200 mg 加入生理盐水静脉缓慢滴注（不少于 15～30 分钟），每周 2～3 次，直至补足总量；\n"
            f"2. 羧基麦芽糖铁注射液（500mg/瓶）：全疗程需 {vials_fcm_500mg} 瓶。单次最大剂量可达 1000 mg，滴注 15 分钟，极大减少就诊输液频次；\n"
            f"3. 警戒底线：输液前备妥抢救设施，输注前 15 分钟密切监测过敏与生命体征；切勿超总量盲目补铁以防铁过载。"
        )

        return {
            "calculator": "ganzoni_iron",
            "name": "Ganzoni 公式静脉总缺铁量评估",
            "totalDeficitMg": total_iron_deficit_mg,
            "weightKg": weight,
            "actualHb_g_L": actual_hb_g_l,
            "targetHb_g_L": target_hb_g_l,
            "ironDepotMg": iron_depot_mg,
            "anemiaSeverity": severity,
            "anemiaSeverity_cn": severity_cn,
            "dosingEquivalents": {
                "iron_sucrose_100mg_ampoules": ampoules_sucrose_100mg,
                "ferric_carboxymaltose_500mg_vials": vials_fcm_500mg,
            },
            "recommendation": recommendation,
            "guideline": "《铁缺乏症和缺铁性贫血诊治和预防成人指南（2023年版）》（SRC-CMA-HEMA-2023-01）",
        }

    # -------------------------------------------------------------------------
    # 15. Burch-Wartofsky 甲状腺危象评分 (BWPS) 计算引擎
    # -------------------------------------------------------------------------
    @staticmethod
    def calc_burch_wartofsky_thyroid_storm(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        Burch-Wartofsky Point Scale (BWPS) 甲状腺危象量化评分引擎
        依据《中国甲状腺功能亢进症和其他原因所致甲状腺毒症诊治指南》（SRC-CMA-THY-2022-01）
        评估 7 个临床维度，总分 0~140 分。
        """
        # 1. 体温调节障碍 (Temperature °C)
        temp_val = None
        try:
            temp_val = float(p.get("temp") or p.get("temperature") or 37.0)
        except (ValueError, TypeError):
            temp_val = 37.0

        if temp_val >= 40.0:
            temp_score = 30
        elif temp_val >= 39.5:
            temp_score = 25
        elif temp_val >= 38.9:
            temp_score = 20
        elif temp_val >= 38.3:
            temp_score = 15
        elif temp_val >= 37.8:
            temp_score = 10
        elif temp_val >= 37.2:
            temp_score = 5
        else:
            temp_score = 0

        # 2. 中枢神经系统效应 (CNS effects)
        cns_raw = str(p.get("cns_effects") or p.get("cns") or "").strip().lower()
        if any(k in cns_raw for k in ["昏迷", "癫痫", "抽搐", "coma", "seizure"]):
            cns_score = 30
            cns_desc = "重度（癫痫发作、昏迷）"
        elif any(k in cns_raw for k in ["谵妄", "精神错乱", "极度嗜睡", "delirium", "psychosis"]):
            cns_score = 20
            cns_desc = "中度（谵妄、精神错乱、极度嗜睡）"
        elif any(k in cns_raw for k in ["烦躁", "焦虑", "激惹", "agitation", "mild"]):
            cns_score = 10
            cns_desc = "轻度（烦躁、焦虑、易激惹）"
        else:
            cns_score = int(p.get("cns_score") or 0)
            cns_desc = "无明显中枢神经系统异常"

        # 3. 胃肠道与肝功能障碍 (GI/Hepatic dysfunction)
        gi_raw = str(p.get("gi_dysfunction") or p.get("gi") or "").strip().lower()
        if any(k in gi_raw for k in ["黄疸", "jaundice"]):
            gi_score = 20
            gi_desc = "重度（不明原因明显黄疸）"
        elif any(k in gi_raw for k in ["腹泻", "恶心", "呕吐", "腹痛", "diarrhea", "vomiting"]):
            gi_score = 10
            gi_desc = "中度（腹泻、恶心、呕吐、腹痛）"
        else:
            gi_score = int(p.get("gi_score") or 0)
            gi_desc = "无胃肠道与肝功能异常"

        # 4. 心血管心动过速 (Heart Rate bpm)
        hr_val = 0
        try:
            hr_val = int(p.get("hr") or p.get("heart_rate") or 80)
        except (ValueError, TypeError):
            hr_val = 80

        if hr_val >= 140:
            hr_score = 25
        elif hr_val >= 130:
            hr_score = 20
        elif hr_val >= 120:
            hr_score = 15
        elif hr_val >= 110:
            hr_score = 10
        elif hr_val >= 90:
            hr_score = 5
        else:
            hr_score = 0

        # 5. 充血性心力衰竭 (CHF)
        chf_raw = str(p.get("chf_stage") or p.get("chf") or "").strip().lower()
        if any(k in chf_raw for k in ["肺水肿", "急性左心衰", "pulmonary edema", "severe"]):
            chf_score = 15
            chf_desc = "重度（急性肺水肿）"
        elif any(k in chf_raw for k in ["双肺底湿啰音", "啰音", "rales", "moderate"]):
            chf_score = 10
            chf_desc = "中度（双肺底湿啰音）"
        elif any(k in chf_raw for k in ["下肢水肿", "浮肿", "edema", "mild"]):
            chf_score = 5
            chf_desc = "轻度（双下肢凹陷性水肿）"
        else:
            chf_score = int(p.get("chf_score") or 0)
            chf_desc = "无心力衰竭体征"

        # 6. 心房颤动 (Atrial Fibrillation)
        af_present = bool(p.get("af") or p.get("atrial_fibrillation") or p.get("has_af"))
        af_score = 10 if af_present else 0

        # 7. 促发/诱发病史 (Precipitating event)
        precip_event = bool(p.get("precipitating_event") or p.get("precipitating_history") or p.get("has_trigger"))
        precip_score = 10 if precip_event else 0

        total_score = temp_score + cns_score + gi_score + hr_score + chf_score + af_score + precip_score

        if total_score >= 45:
            storm_status = "THYROID_STORM"
            storm_status_cn = "甲状腺危象 (确诊)"
            recommendation = (
                f"【危急抢救】BWPS 评分 {total_score} 分（≥45分），高度提示甲状腺危象！立即启动重症抢救：\n"
                f"1. 立即收入重症监护室（ICU）或急诊抢救室，密切监护心率、呼吸、体温与血压；\n"
                f"2. 丙硫氧嘧啶（PTU）首剂 500～1000 mg 口服或胃管注入，后 200 mg q4h；\n"
                f"3. 服用 PTU 1 小时后加用复方碘溶液（Lugol液）5～10 滴 q8h 封闭甲状腺释放；\n"
                f"4. 静脉滴注氢化可的松 100 mg q8h 拮抗应激反应并抑制外周 T4 转 T3；\n"
                f"5. 物理降温，严禁使用阿司匹林类退热药（竞争血浆蛋白结合致游离甲状腺素剧增）。"
            )
        elif total_score >= 25:
            storm_status = "IMPENDING_STORM"
            storm_status_cn = "临界危象 (即将发生危象)"
            recommendation = (
                f"【黄色预警】BWPS 评分 {total_score} 分（25～44分），提示即将发生甲状腺危象！\n"
                f"建议严密卧床监护，积极纠治发热或感染诱因，加大抗甲状腺药物与心脏高选择性 β 受体阻滞剂剂量，防范病情向暴发性危象恶化。"
            )
        else:
            storm_status = "UNLIKELY"
            storm_status_cn = "危象可能性小"
            recommendation = (
                f"BWPS 评分 {total_score} 分（<25分），发生甲状腺危象可能性极小。\n"
                f"继续维持门诊规范甲巯咪唑阶梯治疗，定期监测甲功三项与血常规白细胞计数。"
            )

        return {
            "calculator": "bwps",
            "name": "Burch-Wartofsky 甲状腺危象评分 (BWPS)",
            "score": total_score,
            "maxScore": 140,
            "minScore": 0,
            "stormStatus": storm_status,
            "stormStatus_cn": storm_status_cn,
            "subScores": {
                "thermoregulatory_score": temp_score,
                "cns_score": cns_score,
                "cns_description": cns_desc,
                "gi_hepatic_score": gi_score,
                "gi_hepatic_description": gi_desc,
                "tachycardia_score": hr_score,
                "chf_score": chf_score,
                "chf_description": chf_desc,
                "af_score": af_score,
                "precipitating_event_score": precip_score,
            },
            "recommendation": recommendation,
            "guideline": "《中国甲状腺功能亢进症和其他原因所致甲状腺毒症诊治指南》（SRC-CMA-THY-2022-01）",
        }

    # -------------------------------------------------------------------------
    # 16. Zero-Manual-Input EMR Hydration & Minimal Follow-up Engine (P3.1)
    # -------------------------------------------------------------------------
    CALCULATOR_SCHEMA_SPECS = {
        "cha2ds2_vasc": {
            "title": "CHA2DS2-VASc 房颤卒中风险评分",
            "fields": [
                {"key": "age", "label": "年龄 (岁)", "type": "number", "auto_from": ["age"]},
                {"key": "gender", "label": "性别", "type": "string", "auto_from": ["gender"]},
                {"key": "chf", "label": "充血性心力衰竭或 LVEF≤40%", "type": "boolean", "points": 1, "keywords": ["心力衰竭", "心衰", "chf", "lvef≤40", "心功能不全"]},
                {"key": "htn", "label": "高血压病史", "type": "boolean", "points": 1, "keywords": ["高血压", "htn", "原发性高血压"]},
                {"key": "dm", "label": "糖尿病史", "type": "boolean", "points": 1, "keywords": ["糖尿病", "2型糖尿病", "dm", "高血糖"]},
                {"key": "stroke", "label": "既往脑卒中 / TIA / 血栓栓塞史", "type": "boolean", "points": 2, "keywords": ["脑卒中", "脑梗", "脑梗死", "tia", "短暂性脑缺血", "血栓栓塞"]},
                {"key": "vascular", "label": "血管疾病 (心肌梗死/外周动脉疾病/主动脉斑块)", "type": "boolean", "points": 1, "keywords": ["心肌梗死", "心梗", "冠心病", "外周动脉", "主动脉斑块", "支架术后"]},
            ],
        },
        "has_bled": {
            "title": "HAS-BLED 抗凝出血风险评分",
            "fields": [
                {"key": "age", "label": "年龄 (岁)", "type": "number", "auto_from": ["age"]},
                {"key": "sbp", "label": "收缩压 (mmHg)", "type": "number", "auto_from": ["sbp"]},
                {"key": "renal_disease", "label": "肾功能异常 (透析/肾移植/Scr≥200μmol/L)", "type": "boolean", "points": 1, "keywords": ["肾功能不全", "尿毒症", "透析", "慢性肾脏病"]},
                {"key": "liver_disease", "label": "肝功能异常 (肝硬化/胆红素>2x/转氨酶>3x)", "type": "boolean", "points": 1, "keywords": ["肝硬化", "肝功能异常", "肝炎", "肝衰竭"]},
                {"key": "stroke_history", "label": "既往卒中史", "type": "boolean", "points": 1, "keywords": ["脑卒中", "脑梗", "脑出血"]},
                {"key": "bleeding_history", "label": "既往大出血史或出血倾向/贫血", "type": "boolean", "points": 1, "keywords": ["消化道出血", "出血史", "黑便", "呕血", "重度贫血"]},
                {"key": "labile_inr", "label": "INR 不稳定 (TTR<60%)", "type": "boolean", "points": 1, "keywords": ["inr不稳定", "inr波动"]},
                {"key": "drugs", "label": "合并使用抗血小板药或 NSAIDs", "type": "boolean", "points": 1, "keywords": ["阿司匹林", "氯吡格雷", "布洛芬", "塞来昔布", "双氯芬酸"]},
                {"key": "alcohol", "label": "长期酗酒 (≥8杯/周)", "type": "boolean", "points": 1, "keywords": ["酗酒", "大量饮酒", "酒精依赖"]},
            ],
        },
        "curb_65": {
            "title": "CURB-65 社区获得性肺炎严重度评分",
            "fields": [
                {"key": "confusion", "label": "新发意识障碍 / 精神错乱", "type": "boolean", "points": 1, "keywords": ["意识障碍", "神志不清", "谵妄", "嗜睡", "精神错乱", "昏迷"]},
                {"key": "bun", "label": "血尿素氮 BUN (mmol/L)", "type": "number", "auto_from": ["bun", "urea"]},
                {"key": "rr", "label": "呼吸频率 (次/分)", "type": "number", "auto_from": ["rr", "respiratory_rate"]},
                {"key": "sbp", "label": "收缩压 (mmHg)", "type": "number", "auto_from": ["sbp"]},
                {"key": "dbp", "label": "舒张压 (mmHg)", "type": "number", "auto_from": ["dbp"]},
                {"key": "age", "label": "年龄 (岁)", "type": "number", "auto_from": ["age"]},
            ],
        },
        "crb_65": {
            "title": "CRB-65 门诊肺炎快速评分",
            "fields": [
                {"key": "confusion", "label": "新发意识障碍 / 精神错乱", "type": "boolean", "points": 1, "keywords": ["意识障碍", "神志不清", "谵妄", "嗜睡", "精神错乱"]},
                {"key": "rr", "label": "呼吸频率 (次/分)", "type": "number", "auto_from": ["rr", "respiratory_rate"]},
                {"key": "sbp", "label": "收缩压 (mmHg)", "type": "number", "auto_from": ["sbp"]},
                {"key": "dbp", "label": "舒张压 (mmHg)", "type": "number", "auto_from": ["dbp"]},
                {"key": "age", "label": "年龄 (岁)", "type": "number", "auto_from": ["age"]},
            ],
        },
        "wells_pe": {
            "title": "Wells 肺栓塞 (PE) 临床概率评分",
            "fields": [
                {"key": "dvt_signs", "label": "下肢深静脉血栓 (DVT) 临床症状与体征 (单侧下肢肿胀+触痛)", "type": "boolean", "points": 3.0, "keywords": ["下肢肿胀", "单侧下肢水肿", "深静脉血栓", "dvt", "腓肠肌压痛"]},
                {"key": "pe_most_likely", "label": "肺栓塞可能性大于或等于其他鉴别诊断", "type": "boolean", "points": 3.0, "keywords": ["疑诊肺栓塞", "考虑肺栓塞", "高度怀疑肺栓塞"]},
                {"key": "hr", "label": "心率 (次/分)", "type": "number", "auto_from": ["hr", "heart_rate"]},
                {"key": "immobilization_or_surgery", "label": "近4周内手术史或连续卧床制动≥3天", "type": "boolean", "points": 1.5, "keywords": ["术后", "手术史", "长期卧床", "制动", "骨折石膏"]},
                {"key": "prior_dvt_pe", "label": "既往客观确诊的 DVT 或 PE 病史", "type": "boolean", "points": 1.5, "keywords": ["既往肺栓塞", "既往深静脉血栓", "肺栓塞史"]},
                {"key": "hemoptysis", "label": "咯血症状", "type": "boolean", "points": 1.0, "keywords": ["咯血", "痰中带血"]},
                {"key": "malignancy", "label": "活动性恶性肿瘤 (近6个月内治疗中或姑息治疗)", "type": "boolean", "points": 1.0, "keywords": ["恶性肿瘤", "肺癌", "胃癌", "结直肠癌", "乳腺癌", "化疗"]},
            ],
        },
        "alvarado": {
            "title": "Alvarado 急性阑尾炎临床危险评分",
            "fields": [
                {"key": "migration_pain", "label": "转移性右下腹痛", "type": "boolean", "points": 1, "keywords": ["转移性右下腹痛", "转移至右下腹"]},
                {"key": "anorexia", "label": "厌食 / 食欲减退", "type": "boolean", "points": 1, "keywords": ["厌食", "纳差", "食欲减退", "食欲不振"]},
                {"key": "nausea_vomiting", "label": "恶心或呕吐", "type": "boolean", "points": 1, "keywords": ["恶心", "呕吐"]},
                {"key": "rlq_tenderness", "label": "右下腹麦氏点压痛", "type": "boolean", "points": 2, "keywords": ["麦氏点压痛", "右下腹压痛"]},
                {"key": "rebound_pain", "label": "反跳痛", "type": "boolean", "points": 1, "keywords": ["反跳痛", "肌紧张"]},
                {"key": "temp", "label": "体温 (℃)", "type": "number", "auto_from": ["temp", "temperature"]},
                {"key": "wbc", "label": "白细胞计数 WBC (×10^9/L)", "type": "number", "auto_from": ["wbc"]},
                {"key": "neutrophil_shift", "label": "中性粒细胞左移 (N% > 75%)", "type": "boolean", "points": 1, "keywords": ["中性粒细胞升高", "核左移", "中性粒细胞比例升高"]},
            ],
        },
        "abcd2": {
            "title": "ABCD2 短暂性脑缺血发作 (TIA) 卒中风险评分",
            "fields": [
                {"key": "age", "label": "年龄 (岁)", "type": "number", "auto_from": ["age"]},
                {"key": "sbp", "label": "收缩压 (mmHg)", "type": "number", "auto_from": ["sbp"]},
                {"key": "dbp", "label": "舒张压 (mmHg)", "type": "number", "auto_from": ["dbp"]},
                {"key": "unilateral_weakness", "label": "单侧肢体无力", "type": "boolean", "points": 2, "keywords": ["单侧肢体无力", "偏瘫", "一侧肢体无力", "左侧肢体无力", "右侧肢体无力"]},
                {"key": "speech_impairment", "label": "言语障碍但无肢体无力", "type": "boolean", "points": 1, "keywords": ["言语不清", "失语", "构音障碍", "吐字不清"]},
                {"key": "duration_minutes", "label": "症状持续时间 (分钟)", "type": "number", "auto_from": ["duration_minutes"]},
                {"key": "diabetes", "label": "糖尿病病史", "type": "boolean", "points": 1, "keywords": ["糖尿病", "2型糖尿病"]},
            ],
        },
        "bmi_obesity": {
            "title": "中国成人超重与肥胖症诊断与BMI分级计算器",
            "fields": [
                {"key": "weight", "label": "体重 (kg)", "type": "number", "auto_from": ["weight", "weight_kg"]},
                {"key": "height", "label": "身高 (cm 或 m)", "type": "number", "auto_from": ["height", "height_cm"]},
                {"key": "waist", "label": "腰围 (cm)", "type": "number", "auto_from": ["waist", "waist_cm"]},
                {"key": "gender", "label": "性别", "type": "string", "auto_from": ["gender"]},
                {"key": "htn", "label": "高血压病史", "type": "boolean", "keywords": ["高血压", "htn"]},
                {"key": "dm", "label": "糖尿病史/糖代谢异常", "type": "boolean", "keywords": ["糖尿病", "高血糖", "dm", "t2dm"]},
                {"key": "dyslipidemia", "label": "血脂异常/高甘油三酯", "type": "boolean", "keywords": ["高脂血症", "血脂异常", "高甘油三酯"]},
                {"key": "masld", "label": "脂肪肝 (MASLD/NAFLD)", "type": "boolean", "keywords": ["脂肪肝", "masld", "nafld"]},
            ],
        },
        "act_score": {
            "title": "哮喘控制测试 (ACT) 评分",
            "fields": [
                {"key": "q1", "label": "工作/学习活动受限程度 (1~5)", "type": "number", "auto_from": ["q1", "activity_limitation"]},
                {"key": "q2", "label": "气短/喘息频率 (1~5)", "type": "number", "auto_from": ["q2", "shortness_of_breath"]},
                {"key": "q3", "label": "夜间憋醒/早醒频率 (1~5)", "type": "number", "auto_from": ["q3", "night_waking"]},
                {"key": "q4", "label": "急救药物使用频率 (1~5)", "type": "number", "auto_from": ["q4", "reliever_usage"]},
                {"key": "q5", "label": "哮喘控制自评 (1~5)", "type": "number", "auto_from": ["q5", "self_assessment"]},
            ],
        },
        "ganzoni_iron": {
            "title": "Ganzoni 公式静脉总缺铁量评估计算器",
            "fields": [
                {"key": "weight", "label": "体重 (kg)", "type": "number", "auto_from": ["weight", "weight_kg"]},
                {"key": "hb", "label": "实际血红蛋白 (g/L 或 g/dL)", "type": "number", "auto_from": ["hb", "hemoglobin", "hgb", "current_hb"]},
                {"key": "target_hb", "label": "目标血红蛋白 (g/dL, 默认15.0)", "type": "number", "auto_from": ["target_hb"]},
                {"key": "iron_depot", "label": "机体储存铁量 (mg, 默认500)", "type": "number", "auto_from": ["iron_depot", "iron_depot_mg"]},
            ],
        },
        "bwps": {
            "title": "Burch-Wartofsky 甲状腺危象评分 (BWPS)",
            "fields": [
                {"key": "temp", "label": "体温 (°C)", "type": "number", "auto_from": ["temp", "temperature"]},
                {"key": "hr", "label": "静息心率 (bpm)", "type": "number", "auto_from": ["hr", "heart_rate"]},
                {"key": "cns_effects", "label": "中枢神经系统症状 (轻度/中度/重度)", "type": "string", "keywords": ["谵妄", "昏迷", "烦躁", "精神错乱", "极度嗜睡"]},
                {"key": "gi_dysfunction", "label": "胃肠道与肝损害表现 (恶心/呕吐/腹泻/黄疸)", "type": "string", "keywords": ["黄疸", "腹泻", "恶心", "呕吐", "腹痛"]},
                {"key": "chf_stage", "label": "心力衰竭程度 (轻度/中度/重度肺水肿)", "type": "string", "keywords": ["肺水肿", "下肢水肿", "双肺底湿啰音"]},
                {"key": "af", "label": "合并心房颤动", "type": "boolean", "keywords": ["心房颤动", "房颤", "af"]},
                {"key": "precipitating_event", "label": "存在感染/手术/创伤/停药诱因", "type": "boolean", "keywords": ["感染", "手术", "创伤", "停药", "应激"]},
            ],
        },
    }

    @classmethod
    def hydrate_params_from_emr(cls, calculator_name: str, emr_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically extracts calculator input parameters from raw HIS/EMR context
        (vitals, lab results, demographics, chief complaint, present illness, physical exam, diagnoses)
        and returns a minimal list of follow-up questions for unconfirmed bedside items.
        """
        from tools.cdss.parameter_normalizer import ClinicalParameterNormalizer
        norm_p = ClinicalParameterNormalizer.normalize_patient(emr_context)
        name = calculator_name.strip().lower().replace("-", "_")
        if name in ("wells", "wells_score"):
            name = "wells_pe"
        elif name == "alvarado_score":
            name = "alvarado"
        elif name == "abcd2_score":
            name = "abcd2"

        text_corpus = " ".join([
            str(norm_p.get("chiefComplaint", "")),
            str(norm_p.get("presentIllness", "")),
            str(norm_p.get("physicalExam", "")),
            str(norm_p.get("history", "")),
            str(norm_p.get("medicalHistory", "")),
            str(norm_p.get("diagnosis", "")),
            " ".join(norm_p.get("normalized_diagnoses", [])),
            " ".join([str(m) for m in (norm_p.get("medications") or norm_p.get("concurrent_drugs") or [])]),
        ]).lower()

        hydrated: Dict[str, Any] = {}
        auto_extracted: List[str] = []
        missing_fields: List[str] = []
        follow_up_questions: List[Dict[str, Any]] = []

        # Copy all normalized direct keys first
        for k, v in norm_p.items():
            if not k.startswith("_") and v is not None:
                hydrated[k] = v

        spec = cls.CALCULATOR_SCHEMA_SPECS.get(name)
        if spec:
            for f in spec["fields"]:
                fkey = f["key"]
                ftype = f["type"]

                # Check if already present in hydrated via auto_from or direct key
                found_val = None
                for src_k in f.get("auto_from", [fkey]):
                    if norm_p.get(src_k) is not None:
                        found_val = norm_p.get(src_k)
                        break

                if found_val is not None:
                    hydrated[fkey] = found_val
                    auto_extracted.append(fkey)
                    continue

                # For boolean fields, try keyword extraction from clinical text
                if ftype == "boolean":
                    keywords = f.get("keywords", [])
                    import re as _re
                    negated = any(bool(_re.search(rf"(?:无|否认|未见|排除)[^，。；,\.;]{{0,15}}{_re.escape(kw)}", text_corpus)) for kw in keywords)
                    matched = any(kw in text_corpus for kw in keywords)
                    if matched and not negated:
                        hydrated[fkey] = True
                        auto_extracted.append(fkey)
                    elif negated:
                        hydrated[fkey] = False
                        auto_extracted.append(fkey)
                    else:
                        # Special derived logic for HAS-BLED renal/liver
                        if fkey == "renal_disease" and (norm_p.get("egfr_lt_30") or (norm_p.get("scr") and float(norm_p["scr"]) >= 200)):
                            hydrated[fkey] = True
                            auto_extracted.append(fkey)
                        elif fkey == "liver_disease" and norm_p.get("severe_liver_injury"):
                            hydrated[fkey] = True
                            auto_extracted.append(fkey)
                        else:
                            missing_fields.append(fkey)
                            follow_up_questions.append({
                                "field": fkey,
                                "label": f["label"],
                                "type": "boolean",
                                "pointsImpact": f.get("points", 1),
                            })
                else:
                    missing_fields.append(fkey)
                    follow_up_questions.append({
                        "field": fkey,
                        "label": f["label"],
                        "type": ftype,
                    })

        return {
            "calculator": name,
            "hydratedParams": hydrated,
            "autoExtractedFields": auto_extracted,
            "missingFields": missing_fields,
            "minimalFollowUpQuestions": follow_up_questions,
        }

    @classmethod
    def calculate_from_emr(cls, calculator_name: str, emr_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Zero-manual-input execution: hydrates parameters automatically from EMR context,
        runs the clinical calculator, and attaches autoExtractedFields and minimalFollowUpQuestions.
        """
        hydration = cls.hydrate_params_from_emr(calculator_name, emr_context)
        calc_result = cls.calculate(calculator_name, hydration["hydratedParams"])
        calc_result["emrHydration"] = {
            "autoExtractedFields": hydration["autoExtractedFields"],
            "missingFields": hydration["missingFields"],
            "minimalFollowUpQuestions": hydration["minimalFollowUpQuestions"],
            "isFullyHydrated": len(hydration["missingFields"]) == 0,
        }
        return calc_result

    @classmethod
    def recommend_calculators_for_encounter(cls, emr_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Inspects the patient's encounter context (chief complaint, diagnosis, labs)
        and automatically triggers and pre-computes relevant clinical scales for the doctor's sidebar.
        """
        from tools.cdss.parameter_normalizer import ClinicalParameterNormalizer
        norm_p = ClinicalParameterNormalizer.normalize_patient(emr_context)
        corpus = " ".join([
            str(norm_p.get("chiefComplaint", "")),
            str(norm_p.get("presentIllness", "")),
            str(norm_p.get("diagnosis", "")),
            " ".join(norm_p.get("normalized_diagnoses", [])),
        ]).lower()

        triggered_calcs: List[str] = []
        if any(k in corpus for k in ["房颤", "心房颤动", "af"]):
            triggered_calcs.extend(["cha2ds2_vasc", "has_bled"])
        if any(k in corpus for k in ["肺炎", "肺部感染", "cap"]):
            triggered_calcs.append("curb_65" if (norm_p.get("bun") is not None) else "crb_65")
        if any(k in corpus for k in ["肺栓塞", "深静脉血栓", "胸痛伴呼吸困难", "咯血", "dvt"]):
            triggered_calcs.append("wells_pe")
        if any(k in corpus for k in ["阑尾炎", "右下腹痛", "转移性腹痛"]):
            triggered_calcs.append("alvarado")
        if any(k in corpus for k in ["短暂性脑缺血", "tia", "一过性肢体无力"]):
            triggered_calcs.append("abcd2")
        if any(k in corpus for k in ["慢阻肺", "慢性阻塞性肺疾病", "copd"]):
            triggered_calcs.append("mmrc")
        if any(k in corpus for k in ["扁桃体炎", "急性咽峡炎", "咽痛"]):
            triggered_calcs.append("centor")
        if any(k in corpus for k in ["肥胖", "超重", "体质指数", "bmi", "减重"]):
            triggered_calcs.append("bmi_obesity")
        if any(k in corpus for k in ["哮喘", "支气管哮喘", "喘息", "哮鸣音", "asthma"]):
            triggered_calcs.append("act_score")
        if any(k in corpus for k in ["缺铁", "贫血", "ida", "血红蛋白低", "小细胞低色素", "铁蛋白", "乏力伴苍白"]):
            triggered_calcs.append("ganzoni_iron")
        if any(k in corpus for k in ["甲亢", "甲状腺功能亢进", "甲状腺毒症", "graves", "突眼伴心悸", "怕热多汗消瘦"]):
            triggered_calcs.append("bwps")
        if norm_p.get("scr") is not None and norm_p.get("age") is not None:
            triggered_calcs.append("renal_clearance")

        results = []
        seen = set()
        for cname in triggered_calcs:
            if cname in seen:
                continue
            seen.add(cname)
            try:
                results.append(cls.calculate_from_emr(cname, emr_context))
            except Exception:
                pass
        return results


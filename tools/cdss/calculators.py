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
            details.append("年龄 65~74岁 (+1)")
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
            recommendation = "重症高危肺炎，死亡率 15%~40%。必须收住院，若合并感染性休克或需机械通气应直接入住 ICU！"

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
            details.append("年龄 3~14岁 (链球菌高发年龄段) (+1)")
        elif age >= 45:
            score -= 1
            details.append("年龄 ≥ 45岁 (链球菌低发年龄段) (-1)")

        # Probability and guidance
        if score <= 1:
            gas_risk = "< 10%"
            recommendation = "A族链球菌感染概率低，病毒性自限可能大。对症支持治疗，严禁盲目开具抗生素！"
        elif score in (2, 3):
            gas_risk = "15% ~ 30%"
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
            adjustments.append("二甲双胍每日最大剂量严格限制在 500~1000mg 以内")
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
        bili = float(p.get("bili", 15.0) or p.get("bilirubin", 15.0))
        alb = float(p.get("alb", 40.0) or p.get("albumin", 40.0))
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
            details.append(f"总胆红素={bili} 在 34~51 μmol/L (+2)")
        else:
            score += 3
            details.append(f"总胆红素={bili} > 51 μmol/L (+3)")

        # 2. Albumin (g/L)
        if alb > 35.0:
            score += 1
            details.append(f"白蛋白={alb} > 35 g/L (+1)")
        elif alb >= 28.0:
            score += 2
            details.append(f"白蛋白={alb} 在 28~35 g/L (+2)")
        else:
            score += 3
            details.append(f"白蛋白={alb} < 28 g/L (+3)")

        # 3. INR
        if inr < 1.7:
            score += 1
            details.append(f"INR={inr} < 1.7 (+1)")
        elif inr <= 2.3:
            score += 2
            details.append(f"INR={inr} 在 1.7~2.3 (+2)")
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
            details.append("1~2级肝性脑病 (+2)")
        else:
            score += 3
            details.append("3~4级严重肝性脑病 (+3)")

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
        - dehydration: "mild" (3~5%) / "moderate" (6~9%) / "severe" (≥10%)
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
            degree = "轻度脱水 (丢失体重大约 3%~5%)"
            ors_rate = "首选低渗口服补液盐 (ORS-III)，前4小时按 50 mL/kg 少量多次口服"
        elif dehydration in ("moderate", "中度"):
            deficit_rate = 80.0  # ml/kg
            degree = "中度脱水 (丢失体重大约 6%~9%)"
            ors_rate = "首选 ORS-III 补液，前4小时按 80~100 mL/kg 口服；若频繁剧吐则转静脉补液"
        else:
            deficit_rate = 110.0  # ml/kg
            degree = "重度脱水 (丢失体重 ≥ 10%)"
            ors_rate = "【急危重症警告】：重度脱水常伴低血容量休克，绝对禁止单纯口服！立即建立静脉通路，首剂生理盐水 20 mL/kg 在 30~60 分钟内快速扩容！"

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

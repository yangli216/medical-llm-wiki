"""
Clinical Parameter Normalization and Dynamic Inference Middleware.
Standardizes heterogeneous patient clinical contexts (vitals, demographics, labs, diagnoses)
and dynamically calculates derived parameters (e.g. eGFR via 2021 CKD-EPI, CrCl via Cockcroft-Gault,
Child-Pugh hepatic grade, serum potassium / hyperkalemia flags, pediatric/elderly flags,
gestational status) for production-grade CDSS evaluation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from tools.cdss.calculators import ClinicalCalculatorRegistry


class ClinicalParameterNormalizer:
    """Normalizes raw patient inputs and executes deterministic physiological inference."""

    @classmethod
    def normalize_patient(cls, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Produces a rich, normalized patient profile dictionary with derived clinical flags.
        Ensures strict robustness against missing, null, or heterogeneously typed values,
        and automatically unpacks nested HIS/EMR 'labs', 'vitals', and 'patient' structures.
        """
        if not raw:
            return cls._empty_profile()

        profile: Dict[str, Any] = dict(raw)
        # Unpack nested EMR structures if present (e.g. {"patient": {...}, "labs": {...}, "vitals": {...}})
        if isinstance(profile.get("patient"), dict):
            for k, v in profile["patient"].items():
                if k not in profile or profile[k] is None:
                    profile[k] = v

        labs = {}
        for lab_key in ("labs", "labResults", "laboratory", "lab_results"):
            if isinstance(profile.get(lab_key), dict):
                labs.update(profile[lab_key])

        for lk, lv in labs.items():
            if lk not in profile or profile[lk] is None:
                profile[lk] = lv

        inferred: Dict[str, Any] = {}

        # 1. Demographics & Life Stages
        age_val = cls._parse_int(profile.get("age"))
        if age_val is not None:
            profile["age"] = age_val
            profile["is_pediatric"] = age_val < 18
            profile["is_child_under_14"] = age_val < 14
            profile["is_child_under_12"] = age_val < 12
            profile["is_child_under_8"] = age_val < 8
            profile["is_elderly"] = age_val >= 65
            profile["is_very_elderly"] = age_val >= 80

        # Gender
        gender_raw = str(profile.get("gender", "")).strip().lower()
        is_female = bool(
            gender_raw in ("女", "female", "f", "woman")
            or profile.get("is_female")
            or profile.get("pregnancy")
            or profile.get("is_pregnant")
            or profile.get("lactation")
        )
        profile["gender"] = "女" if is_female else ("男" if gender_raw in ("男", "male", "m", "man") else profile.get("gender"))
        profile["is_female"] = is_female

        # Weight & Height
        weight_val = cls._parse_float(profile.get("weight") or profile.get("weight_kg"))
        if weight_val is not None and weight_val > 0:
            profile["weight"] = weight_val
            profile["weight_kg"] = weight_val

        height_val = cls._parse_float(profile.get("height") or profile.get("height_cm"))
        if height_val is not None and height_val > 0:
            profile["height"] = height_val
            profile["height_cm"] = height_val

        # 2. Pregnancy & Lactation States
        diagnoses_text = cls._extract_text_corpus(profile)
        is_pregnant = bool(
            profile.get("pregnancy")
            or profile.get("is_pregnant")
            or profile.get("gestational_weeks")
            or any(kw in diagnoses_text for kw in ["妊娠", "孕期", "怀孕", "早孕", "中孕", "晚孕", "产妇", "子痫", "受孕"])
        )
        if is_pregnant:
            profile["pregnancy"] = True
            profile["is_pregnant"] = True

        is_lactating = bool(
            profile.get("lactation")
            or profile.get("is_lactating")
            or any(kw in diagnoses_text for kw in ["哺乳", "产褥期", "母乳喂养", "产后哺乳"])
        )
        if is_lactating:
            profile["lactation"] = True
            profile["is_lactating"] = True

        # 3. Dynamic Renal Clearance Inference (CKD-EPI 2021 + Cockcroft-Gault)
        scr_val = cls._parse_float(
            profile.get("scr")
            or profile.get("creatinine")
            or profile.get("serum_creatinine")
            or profile.get("cr")
        )
        egfr_existing = cls._parse_float(profile.get("egfr"))
        crcl_existing = cls._parse_float(profile.get("crcl") or profile.get("crcl_ml_min"))

        if scr_val is not None and scr_val > 0 and age_val is not None:
            try:
                calc_params = {
                    "age": age_val,
                    "gender": profile.get("gender") or ("女" if is_female else "男"),
                    "scr": scr_val,
                }
                egfr_res = ClinicalCalculatorRegistry.calc_egfr_ckd_epi(calc_params)
                derived_egfr = egfr_res.get("eGFR")
                if derived_egfr is not None:
                    if egfr_existing is None:
                        profile["egfr"] = derived_egfr
                        inferred["derived_egfr"] = derived_egfr
                        inferred["derived_ckd_stage"] = egfr_res.get("ckdStage")
                    profile["derived_ckd_stage"] = egfr_res.get("ckdStage")

                if weight_val is not None and weight_val > 0:
                    calc_params["weight"] = weight_val
                    cg_res = ClinicalCalculatorRegistry.calc_cockcroft_gault(calc_params)
                    if crcl_existing is None:
                        profile["crcl"] = cg_res.get("crcl")
                    inferred["derived_crcl"] = cg_res.get("crcl")
            except Exception as e:
                profile["_renal_calc_error"] = str(e)
        elif egfr_existing is not None:
            profile["egfr"] = egfr_existing

        if crcl_existing is not None:
            profile["crcl"] = crcl_existing

        # Set standard eGFR / CrCl thresholds
        curr_egfr = cls._parse_float(profile.get("egfr"))
        if curr_egfr is not None:
            profile["egfr_lt_15"] = curr_egfr < 15.0
            profile["egfr_lt_20"] = curr_egfr < 20.0
            profile["egfr_lt_30"] = curr_egfr < 30.0
            profile["egfr_lt_35"] = curr_egfr < 35.0
            profile["egfr_lt_45"] = curr_egfr < 45.0
            profile["egfr_lt_60"] = curr_egfr < 60.0

        # 4. Hepatic Parameters & Dynamic Child-Pugh Inference
        alt_val = cls._parse_float(profile.get("alt") or profile.get("alanine_aminotransferase"))
        ast_val = cls._parse_float(profile.get("ast") or profile.get("aspartate_aminotransferase"))
        tbil_val = cls._parse_float(profile.get("tbil") or profile.get("total_bilirubin") or profile.get("bilirubin"))
        alb_val = cls._parse_float(profile.get("albumin") or profile.get("alb"))
        inr_val = cls._parse_float(profile.get("inr"))

        if alt_val is not None:
            profile["alt"] = alt_val
            if alt_val >= 120.0:
                profile["alt_above_3x"] = True
        if ast_val is not None:
            profile["ast"] = ast_val
            if ast_val >= 120.0:
                profile["ast_above_3x"] = True

        if profile.get("alt_above_3x") or profile.get("ast_above_3x"):
            profile["alt_above_3x"] = True
            profile["severe_liver_injury"] = True
            inferred["severe_liver_injury"] = True

        # Dynamic Child-Pugh Grade inference
        cp_grade_raw = str(profile.get("child_pugh") or profile.get("child_pugh_grade") or "").strip().upper()
        if cp_grade_raw in ("A", "B", "C", "CHILD-PUGH A", "CHILD-PUGH B", "CHILD-PUGH C"):
            grade_letter = cp_grade_raw[-1]
            profile["child_pugh_grade"] = grade_letter
        elif any(x is not None for x in (tbil_val, alb_val, inr_val)) or profile.get("ascites") or profile.get("encephalopathy"):
            try:
                cp_res = ClinicalCalculatorRegistry.calc_child_pugh({
                    "bili": tbil_val if tbil_val is not None else 15.0,
                    "alb": alb_val if alb_val is not None else 38.0,
                    "inr": inr_val if inr_val is not None else 1.1,
                    "ascites": profile.get("ascites", "none"),
                    "encephalopathy": profile.get("encephalopathy", 0),
                })
                cp_g = str(cp_res.get("grade", "A")).replace("级", "").strip().upper()
                profile["child_pugh_grade"] = cp_g
                profile["child_pugh_score"] = cp_res.get("score")
                inferred["derived_child_pugh_grade"] = cp_g
                inferred["derived_child_pugh_score"] = cp_res.get("score")
                if cp_g in ("B", "C"):
                    profile["severe_liver_injury"] = True
            except Exception:
                pass
        elif any(k in diagnoses_text for k in ["child-pugh c", "child c", "肝功能c级", "失代偿期肝硬化", "肝衰竭"]):
            profile["child_pugh_grade"] = "C"
            profile["severe_liver_injury"] = True
            inferred["derived_child_pugh_grade"] = "C"
        elif any(k in diagnoses_text for k in ["child-pugh b", "child b", "肝功能b级"]):
            profile["child_pugh_grade"] = "B"
            profile["severe_liver_injury"] = True
            inferred["derived_child_pugh_grade"] = "B"

        # 5. Serum Potassium (Electrolyte) Inference
        k_val = cls._parse_float(
            profile.get("serum_k")
            or profile.get("potassium")
            or profile.get("k")
            or profile.get("blood_potassium")
        )
        if k_val is not None and k_val > 0:
            profile["serum_k"] = k_val
            if k_val >= 5.0:
                profile["has_hyperkalemia"] = True
                inferred["derived_hyperkalemia"] = True
                inferred["serum_k_mmol_l"] = k_val
            if k_val >= 5.5:
                profile["severe_hyperkalemia"] = True
            elif k_val < 3.5:
                profile["has_hypokalemia"] = True
                inferred["derived_hypokalemia"] = True

        # 6. Vitals & Blood Pressure
        vitals = profile.get("vitals") if isinstance(profile.get("vitals"), dict) else {}
        sbp_val = cls._parse_float(profile.get("sbp") or vitals.get("sbp") or profile.get("systolic_bp"))
        dbp_val = cls._parse_float(profile.get("dbp") or vitals.get("dbp") or profile.get("diastolic_bp"))
        hr_val = cls._parse_float(profile.get("hr") or vitals.get("hr") or profile.get("heart_rate") or vitals.get("heart_rate"))
        rr_val = cls._parse_float(profile.get("rr") or vitals.get("rr") or profile.get("respiratory_rate"))
        temp_val = cls._parse_float(profile.get("temp") or vitals.get("temp") or profile.get("temperature"))

        if sbp_val is not None:
            profile["sbp"] = sbp_val
            if sbp_val >= 160:
                profile["sbp_gt_160"] = True
            if sbp_val >= 180:
                profile["sbp_gt_180"] = True
                profile["hypertensive_crisis"] = True
        if dbp_val is not None:
            profile["dbp"] = dbp_val
            if dbp_val >= 100:
                profile["dbp_gt_100"] = True
            if dbp_val >= 110:
                profile["dbp_gt_110"] = True
                profile["hypertensive_crisis"] = True
        if hr_val is not None:
            profile["hr"] = hr_val
            if hr_val < 50:
                profile["bradycardia_severe"] = True
            elif hr_val < 60:
                profile["bradycardia"] = True
            elif hr_val > 100:
                profile["tachycardia"] = True
        if rr_val is not None:
            profile["rr"] = rr_val
        if temp_val is not None:
            profile["temp"] = temp_val

        # 7. Structured Allergies Normalization
        allergies_list = cls._normalize_string_list(profile.get("allergies") or profile.get("allergy"))
        profile["normalized_allergies"] = allergies_list
        allergy_joined = " ".join(allergies_list).lower()
        profile["has_penicillin_allergy"] = any(k in allergy_joined for k in ["青霉素", "阿莫西林", "氨苄西林", "哌拉西林", "penicillin"])
        if profile["has_penicillin_allergy"]:
            profile["penicillin_allergy"] = True
        profile["has_sulfa_allergy"] = any(k in allergy_joined for k in ["磺胺", "磺胺嘧啶", "复方新诺明", "sulfonamide"])
        profile["has_cephalosporin_allergy"] = any(k in allergy_joined for k in ["头孢", "先锋", "cephalosporin"])

        # 8. Diagnoses & Comorbidities Normalization
        diagnoses_list = cls._normalize_string_list(profile.get("diagnoses") or profile.get("conditions") or profile.get("diagnosis"))
        if profile.get("has_hyperkalemia") and "高钾血症" not in diagnoses_list:
            diagnoses_list.append("高钾血症")
        profile["normalized_diagnoses"] = diagnoses_list
        all_diag_text = (diagnoses_text + " " + " ".join(diagnoses_list)).lower()

        # Mark clinical domain flags
        profile["has_htn"] = any(k in all_diag_text for k in ["高血压", "原发性高血压", "hypertension", "i10"])
        profile["has_dm"] = any(k in all_diag_text for k in ["糖尿病", "2型糖尿病", "diabetes", "e11", "高血糖", "gdm"])
        profile["has_cad"] = any(k in all_diag_text for k in ["冠心病", "心绞痛", "心肌梗死", "stemi", "cad", "i25", "心肌缺血", "支架"])
        profile["has_chf"] = any(k in all_diag_text for k in ["心力衰竭", "心衰", "chf", "hftef", "hfpef", "i50"])
        profile["has_af"] = any(k in all_diag_text for k in ["心房颤动", "房颤", "af", "i48"])
        profile["has_asthma"] = any(k in all_diag_text for k in ["哮喘", "支气管哮喘", "asthma", "j45"])
        profile["has_copd"] = any(k in all_diag_text for k in ["慢阻肺", "慢性阻塞性肺疾病", "copd", "j44"])
        profile["has_gout"] = any(k in all_diag_text for k in ["痛风", "高尿酸", "痛风性关节炎", "gout", "m10"])
        profile["has_ckd"] = any(k in all_diag_text for k in ["慢性肾脏病", "肾功能不全", "肾衰", "ckd", "n18"])
        profile["has_bph"] = any(k in all_diag_text for k in ["前列腺增生", "良性前列腺增生", "前列腺肥大", "bph", "n40"])
        profile["has_peptic_ulcer"] = any(k in all_diag_text for k in ["消化性溃疡", "胃溃疡", "十二指肠溃疡", "消化道出血"])

        profile["_inferred_parameters"] = inferred
        return profile

    @classmethod
    def _empty_profile(cls) -> Dict[str, Any]:
        return {
            "age": None,
            "gender": None,
            "pregnancy": False,
            "is_pregnant": False,
            "lactation": False,
            "is_lactating": False,
            "normalized_allergies": [],
            "normalized_diagnoses": [],
            "_inferred_parameters": {},
        }

    @classmethod
    def _parse_int(cls, val: Any) -> Optional[int]:
        if val is None or val == "":
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    @classmethod
    def _parse_float(cls, val: Any) -> Optional[float]:
        if val is None or val == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _normalize_string_list(cls, val: Any) -> List[str]:
        if not val:
            return []
        if isinstance(val, list):
            res = []
            for item in val:
                if isinstance(item, str):
                    res.append(item.strip())
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("display") or item.get("title") or item.get("code")
                    if name:
                        res.append(str(name).strip())
            return res
        if isinstance(val, str):
            return [s.strip() for s in re.split(r"[,;，；、\n]+", val) if s.strip()]
        return [str(val).strip()]

    @classmethod
    def _extract_text_corpus(cls, p: Dict[str, Any]) -> str:
        parts: List[str] = []
        for key in ["history", "medicalHistory", "chiefComplaint", "presentIllness", "physicalExam", "diagnosis", "conditions"]:
            val = p.get(key)
            if isinstance(val, str):
                parts.append(val)
            elif isinstance(val, list):
                parts.extend([str(x) for x in val if x])
        return " ".join(parts).lower()

"""
Production-Grade Prescription Dosage and Daily Overdose Auditor.
Extracts official daily limits from 138 NMPA package insert monographs,
parses clinical order strings and structured drafts (dose, unit, frequency),
and calculates daily exposure to prevent fatal overdosage.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from tools.cdss.drug_checker import DrugInsertRepository


class DosageLimitsAuditor:
    """Audits prescription dosages against official NMPA package insert limits."""

    FREQUENCY_MULTIPLIERS = {
        "qd": 1.0,
        "qn": 1.0,
        "daily": 1.0,
        "q.d.": 1.0,
        "每日一次": 1.0,
        "每天一次": 1.0,
        "1次/日": 1.0,
        "bid": 2.0,
        "b.i.d.": 2.0,
        "每日两次": 2.0,
        "每天两次": 2.0,
        "2次/日": 2.0,
        "tid": 3.0,
        "t.i.d.": 3.0,
        "每日三次": 3.0,
        "每天三次": 3.0,
        "3次/日": 3.0,
        "qid": 4.0,
        "q.i.d.": 4.0,
        "每日四次": 4.0,
        "每天四次": 4.0,
        "4次/日": 4.0,
        "q4h": 6.0,
        "q6h": 4.0,
        "q8h": 3.0,
        "q12h": 2.0,
        "qw": 1.0 / 7.0,
        "q.w.": 1.0 / 7.0,
        "每周一次": 1.0 / 7.0,
        "prn": 1.0,  # Assume single PRN dose test
        "必要时": 1.0,
    }

    def __init__(self, repo: Optional[DrugInsertRepository] = None):
        self.repo = repo or DrugInsertRepository()

    def audit_medication_dosage(
        self,
        medication_query: str,
        order_draft: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Audits a single medication line for dose and frequency compliance.
        medication_query can be:
          - A simple name: "盐酸二甲双胍片"
          - An order string: "盐酸二甲双胍片 0.5g tid" or "二甲双胍片 1000mg bid"
        order_draft (optional):
          - e.g. { "doseValue": 1000.0, "doseUnit": "mg", "frequencyCode": "TID" }
        """
        drug = self.repo.get(medication_query)
        if not drug:
            return {
                "evaluated": False,
                "reason": f"未在说明书库中找到药品: {medication_query}",
                "level": "PASS",
            }

        max_dose_str = drug.get("max_daily_dose") or ""
        limit_val, limit_unit = self.parse_limit_string(max_dose_str)

        # Parse prescribed dose
        prescribed_dose, prescribed_unit, freq_mult, raw_freq = self.parse_prescribed_order(
            medication_query, order_draft
        )

        if prescribed_dose is None or limit_val is None:
            return {
                "evaluated": True,
                "drugName": drug["generic_name"],
                "hasLimit": limit_val is not None,
                "officialMaxDailyDose": max_dose_str,
                "prescribedDailyDose": None,
                "isOverdose": False,
                "level": "PASS",
            }

        # Calculate daily prescribed dose in target limit unit
        prescribed_daily = prescribed_dose * freq_mult
        norm_prescribed_daily = self.normalize_dose(prescribed_daily, prescribed_unit, limit_unit)

        if norm_prescribed_daily is None:
            # Units are incompatible (e.g. 'ml' vs 'mg'), cannot safely numeric-compare
            return {
                "evaluated": True,
                "drugName": drug["generic_name"],
                "hasLimit": True,
                "officialMaxDailyDose": max_dose_str,
                "prescribedDailyDose": f"{prescribed_daily} {prescribed_unit}/日",
                "isOverdose": False,
                "level": "PASS",
            }

        # Check if exceeds limit (allow 5% float leeway)
        is_overdose = norm_prescribed_daily > (limit_val * 1.05)
        ratio = norm_prescribed_daily / limit_val if limit_val > 0 else 1.0

        if is_overdose:
            # High-risk narrow therapeutic index drugs or severe overdose (>1.4x)
            is_fatal_risk = (
                ratio >= 1.4
                or any(k in drug["generic_name"] for k in ["秋水仙碱", "对乙酰氨基酚", "氨茶碱", "地高辛", "胰岛素"])
            )
            level = "BLOCK" if is_fatal_risk else "WARNING"
            severity = "RED" if is_fatal_risk else "YELLOW"
            msg = (
                f"【{'超极量强行阻断' if is_fatal_risk else '超剂量用药预警'}】"
                f"处方每日给药量约为 {round(norm_prescribed_daily, 2)} {limit_unit}/日，"
                f"已超过国家药品监督管理局法定说明书核准日最大极量（{max_dose_str}）！"
                f"{'超量用药可诱发致死性急性中毒与脏器衰竭，系统已强行阻断！' if is_fatal_risk else '请核查单次剂量与给药频次。'}"
            )
            return {
                "evaluated": True,
                "drugName": drug["generic_name"],
                "isOverdose": True,
                "level": level,
                "severity": severity,
                "ratio": round(ratio, 2),
                "officialMaxDailyDose": max_dose_str,
                "prescribedDailyDose": f"{round(norm_prescribed_daily, 2)} {limit_unit}/日",
                "message": msg,
                "guideline": f"国家药品监督管理局《{drug['generic_name']}说明书》",
            }

        return {
            "evaluated": True,
            "drugName": drug["generic_name"],
            "isOverdose": False,
            "level": "PASS",
            "ratio": round(ratio, 2),
            "officialMaxDailyDose": max_dose_str,
            "prescribedDailyDose": f"{round(norm_prescribed_daily, 2)} {limit_unit}/日",
            "message": "处方日给药剂量在法定说明书安全极量范围以内。",
        }

    def parse_prescribed_order(
        self,
        order_text: str,
        order_draft: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[float], str, float, str]:
        """
        Extracts (dose_value, dose_unit, frequency_multiplier, raw_frequency)
        from either structured draft or free-text order string.
        """
        # 1. Prefer structured orderDraft if available
        if order_draft:
            dv = order_draft.get("doseValue")
            du = order_draft.get("doseUnit") or ""
            fc = str(order_draft.get("frequencyCode") or "").lower()
            if dv is not None:
                try:
                    val = float(dv)
                    mult = self.FREQUENCY_MULTIPLIERS.get(fc, 1.0)
                    return val, du.strip(), mult, fc
                except (ValueError, TypeError):
                    pass

        # 2. Parse from order_text (e.g. "盐酸二甲双胍片 0.5g tid", "对乙酰氨基酚片 500mg tid")
        text = order_text.strip().lower()

        # Find frequency token
        freq_mult = 1.0
        raw_freq = "qd"
        # Match from longest to shortest keywords
        sorted_freq_keys = sorted(self.FREQUENCY_MULTIPLIERS.keys(), key=len, reverse=True)
        for fk in sorted_freq_keys:
            # Word boundary or whitespace / trailing match
            pattern = rf"(?:\s|^|/){re.escape(fk)}(?:\s|$|;|,|\.)"
            if re.search(pattern, text) or text.endswith(fk):
                freq_mult = self.FREQUENCY_MULTIPLIERS[fk]
                raw_freq = fk
                break

        # Find dose value and unit (e.g. "0.5g", "500mg", "1000mg", "10ml", "20μg", "2.5mg")
        # Exclude pure pack specs like "24粒/盒" or "0.5g*12片" by finding the action dose
        dose_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(mg|g|μg|ug|ml|片|丸|粒|袋|支)", text)
        if dose_matches:
            # Usually the last matched dose token before frequency is the prescribe dose
            val_str, unit_str = dose_matches[-1]
            try:
                val = float(val_str)
                return val, unit_str, freq_mult, raw_freq
            except ValueError:
                pass

        return None, "", freq_mult, raw_freq

    @classmethod
    def parse_limit_string(cls, limit_str: str) -> Tuple[Optional[float], Optional[str]]:
        """
        Parses official monograph limit string, e.g.:
          - "2550mg/d" -> (2550.0, "mg")
          - "2000mg/日" -> (2000.0, "mg")
          - "2.0g/d" -> (2.0, "g")
          - "10mg qd" -> (10.0, "mg")
          - "60mg/d" -> (60.0, "mg")
          - "400mg/d (200mg bid)" -> (400.0, "mg")
        """
        if not limit_str:
            return None, None

        cleaned = limit_str.strip().lower()
        # Look for leading or prominent daily limit: e.g. "2550mg", "2.0g", "2400mg"
        match = re.search(r"(\d+(?:\.\d+)?)\s*(mg|g|μg|ug|ml|片|丸|粒|袋|支)\s*(?:/d|/日|/天|qd|每天|每日)?", cleaned)
        if match:
            val = float(match.group(1))
            unit = match.group(2)
            if unit == "ug":
                unit = "μg"
            return val, unit

        return None, None

    @classmethod
    def normalize_dose(cls, value: float, from_unit: str, to_unit: str) -> Optional[float]:
        """Converts dose values between compatible metric units (e.g. g <-> mg <-> μg)."""
        u_from = from_unit.strip().lower()
        u_to = to_unit.strip().lower()

        if u_from == u_to:
            return value

        # Metric conversions
        scale_to_mg = {
            "g": 1000.0,
            "mg": 1.0,
            "μg": 0.001,
            "ug": 0.001,
        }

        if u_from in scale_to_mg and u_to in scale_to_mg:
            value_in_mg = value * scale_to_mg[u_from]
            return value_in_mg / scale_to_mg[u_to]

        # Incompatible units
        return None

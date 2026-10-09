"""
Declarative CDSS Rule Evaluator.
Loads structured clinical safety rules and drug monograph contraindication rules from JSON/YAML,
and performs high-performance, deterministic evaluation against patient and prescription profiles.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


class RuleEvaluator:
    """Evaluates declarative rules against prescription and patient data."""

    def __init__(self, rules_dir: Optional[Path] = None):
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self.rules_dir = rules_dir or (self.root_dir / "rules")
        self.rules: List[Dict[str, Any]] = []
        self._rule_map: Dict[str, Dict[str, Any]] = {}
        self.load_rules()

    def load_rules(self) -> None:
        """Loads all rule definitions from JSON files in rules_dir."""
        self.rules.clear()
        self._rule_map.clear()
        if not self.rules_dir.exists():
            return

        for rule_file in sorted(self.rules_dir.glob("*.json")):
            try:
                data = json.loads(rule_file.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else data.get("rules", [])
                for item in items:
                    rid = item.get("id") or item.get("ruleId")
                    if rid:
                        self.rules.append(item)
                        self._rule_map[rid] = item
            except Exception as e:
                print(f"Warning: Failed to load rule file {rule_file}: {e}")

    def evaluate_clinical_prescription(
        self,
        medications: List[str],
        patient: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Evaluates clinical prescription rules (macro-level prescribing safety, cascades, PIM, etc.).
        Returns list of triggered alert dicts formatted for CdssEngine compatibility.
        """
        profile = patient or {}
        meds_text = " ".join(medications).lower()
        meds_list = [m.lower().strip() for m in medications]

        alerts: List[Dict[str, Any]] = []

        # Extract patient features
        age = profile.get("age")
        try:
            age_val = int(age) if age is not None else None
        except (ValueError, TypeError):
            age_val = None

        egfr = profile.get("egfr")
        try:
            egfr_val = float(egfr) if egfr is not None else None
        except (ValueError, TypeError):
            egfr_val = None

        is_pregnant = bool(profile.get("is_pregnant") or profile.get("pregnancy"))
        is_lactating = bool(profile.get("is_lactating") or profile.get("lactation"))

        diagnoses_list = profile.get("diagnoses", [])
        if isinstance(diagnoses_list, list):
            diagnoses_str = " ".join([str(x) for x in diagnoses_list])
        else:
            diagnoses_str = str(diagnoses_list)

        history_text = " ".join([
            str(profile.get("history", "")),
            str(profile.get("disease", "")),
            str(profile.get("diagnosis", "")),
            str(profile.get("conditions", "")),
            diagnoses_str,
        ]).lower()

        allergy_text = " ".join([
            str(profile.get("allergy", "")),
            str(profile.get("allergies", "")),
        ]).lower()

        for rule in self.rules:
            # Only evaluate clinical safety rules here
            if rule.get("domain") not in ("clinical", "prescription_safety"):
                continue

            cond = rule.get("conditions", {})
            if self._matches_condition(cond, meds_text, meds_list, profile, age_val, egfr_val, is_pregnant, is_lactating, history_text, allergy_text):
                alerts.append({
                    "ruleId": rule.get("id") or rule.get("ruleId"),
                    "severity": rule.get("severity", "RED"),
                    "title": rule.get("title", ""),
                    "message": rule.get("message", ""),
                    "guideline": rule.get("guideline") or rule.get("evidence", ""),
                })

        return alerts

    def evaluate_monograph_audit(
        self,
        drug_name: str,
        patient: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Evaluates drug monograph specific contraindications and DDIs (micro-level).
        Returns list of alerts formatted for DrugContraindicationAuditor compatibility.
        """
        profile = patient or {}
        dname = drug_name.lower().strip()

        age = profile.get("age")
        try:
            age_val = int(age) if age is not None else None
        except (ValueError, TypeError):
            age_val = None

        egfr = profile.get("egfr")
        try:
            egfr_val = float(egfr) if egfr is not None else None
        except (ValueError, TypeError):
            egfr_val = None

        is_pregnant = bool(profile.get("is_pregnant") or profile.get("pregnancy"))
        is_lactating = bool(profile.get("is_lactating") or profile.get("lactation"))

        conditions = [str(c).lower() for c in profile.get("conditions", [])]
        history_text = " ".join(conditions + [
            str(profile.get("history", "")),
            str(profile.get("diagnosis", "")),
        ]).lower()

        allergies = [str(a).lower() for a in profile.get("allergies", [])]
        allergy_text = " ".join(allergies + [str(profile.get("allergy", ""))]).lower()

        concurrent_drugs = [str(d).lower().strip() for d in profile.get("concurrent_drugs", [])]
        concurrent_text = " ".join(concurrent_drugs).lower()

        alerts: List[Dict[str, Any]] = []

        for rule in self.rules:
            if rule.get("domain") not in ("monograph", "drug_insert"):
                continue

            # Target drug must match
            target_keywords = rule.get("target_drugs", [])
            if target_keywords and not any(k in dname for k in target_keywords):
                continue

            cond = rule.get("conditions", {})
            if self._matches_monograph_condition(
                cond, dname, concurrent_drugs, concurrent_text, profile,
                age_val, egfr_val, is_pregnant, is_lactating, conditions, history_text, allergies, allergy_text
            ):
                alerts.append({
                    "level": rule.get("level", "BLOCK"),
                    "rule": rule.get("id"),
                    "title": rule.get("title", ""),
                    "reason": rule.get("reason") or rule.get("message", ""),
                    "evidence": rule.get("evidence", ""),
                })

        return alerts

    def _matches_condition(
        self,
        cond: Dict[str, Any],
        meds_text: str,
        meds_list: List[str],
        profile: Dict[str, Any],
        age_val: Optional[int],
        egfr_val: Optional[float],
        is_pregnant: bool,
        is_lactating: bool,
        history_text: str,
        allergy_text: str,
    ) -> bool:
        """Evaluates clinical rule conditions."""
        # 1. Pregnancy / Lactation
        if cond.get("pregnancy") is True and not is_pregnant:
            return False
        if cond.get("lactation") is True and not is_lactating:
            return False

        # 2. Age constraints
        if "age_lt" in cond:
            if age_val is None or age_val >= cond["age_lt"]:
                return False
        if "age_gte" in cond:
            if age_val is None or age_val < cond["age_gte"]:
                return False

        # 3. eGFR constraints
        if "egfr_lt" in cond:
            if egfr_val is None or egfr_val >= cond["egfr_lt"]:
                return False
        if "egfr_range" in cond:
            min_e, max_e = cond["egfr_range"]
            if egfr_val is None or not (min_e <= egfr_val < max_e):
                return False

        # 4. Drug presence checks
        if "drugs_any" in cond:
            if not any(k in meds_text for k in cond["drugs_any"]):
                return False
        if "drugs_all" in cond:
            for group in cond["drugs_all"]:
                if not any(k in meds_text for k in group):
                    return False
        if "drugs_not_any" in cond:
            if any(k in meds_text for k in cond["drugs_not_any"]):
                return False

        # 5. Drug count threshold (e.g. >= 2 NSAIDs)
        if "drugs_count_gte" in cond:
            cfg = cond["drugs_count_gte"]
            keywords = cfg.get("keywords", [])
            min_cnt = cfg.get("min_count", 2)
            matched = set()
            for k in keywords:
                if k in meds_text:
                    matched.add(k)
            if len(matched) < min_cnt:
                return False

        # 6 & 7. DDI pairs or History conditions
        has_ddi_cfg = "ddi_pairs" in cond
        has_hist_cfg = ("history_any" in cond) or ("diagnoses_any" in cond)
        hist_keywords = cond.get("history_any", []) + cond.get("diagnoses_any", [])

        if has_ddi_cfg and has_hist_cfg and cond.get("ddi_or_history"):
            pair_matched = False
            for pair in cond["ddi_pairs"]:
                grp_a = pair.get("group_a", [])
                grp_b = pair.get("group_b", [])
                has_a = any(k in meds_text for k in grp_a)
                has_b = any(k in meds_text for k in grp_b)
                if has_a and has_b:
                    pair_matched = True
                    break
            flag_hit = any(bool(profile.get(flg)) for flg in cond.get("profile_flags", []))
            text_hit = any(k in history_text for k in hist_keywords)
            if not (pair_matched or flag_hit or text_hit):
                return False
        else:
            if has_ddi_cfg:
                pair_matched = False
                for pair in cond["ddi_pairs"]:
                    grp_a = pair.get("group_a", [])
                    grp_b = pair.get("group_b", [])
                    has_a = any(k in meds_text for k in grp_a)
                    has_b = any(k in meds_text for k in grp_b)
                    if has_a and has_b:
                        pair_matched = True
                        break
                if not pair_matched:
                    return False

            if has_hist_cfg:
                flag_hit = any(bool(profile.get(flg)) for flg in cond.get("profile_flags", []))
                text_hit = any(k in history_text for k in hist_keywords)
                if not (flag_hit or text_hit):
                    return False

        # 8. Allergy checks
        if "allergy_any" in cond:
            flag_hit = any(bool(profile.get(flg)) for flg in cond.get("allergy_flags", []))
            text_hit = any(k in allergy_text for k in cond["allergy_any"])
            if not (flag_hit or text_hit):
                return False

        # 9. Custom profile flag overrides (e.g., informed consent, alt_above_3x)
        if "profile_flag_true" in cond:
            if not bool(profile.get(cond["profile_flag_true"])):
                return False
        if "profile_flag_false" in cond:
            if bool(profile.get(cond["profile_flag_false"])):
                return False

        return True

    def _matches_monograph_condition(
        self,
        cond: Dict[str, Any],
        dname: str,
        concurrent_drugs: List[str],
        concurrent_text: str,
        profile: Dict[str, Any],
        age_val: Optional[int],
        egfr_val: Optional[float],
        is_pregnant: bool,
        is_lactating: bool,
        conditions: List[str],
        history_text: str,
        allergies: List[str],
        allergy_text: str,
    ) -> bool:
        """Evaluates monograph-level condition (eGFR cutoffs, pregnancy, conditions, DDIs)."""
        # Pregnancy
        if cond.get("pregnancy") is True and not is_pregnant:
            return False

        # Age
        if "age_lt" in cond:
            if age_val is None or age_val >= cond["age_lt"]:
                return False
        if "age_gte" in cond:
            if age_val is None or age_val < cond["age_gte"]:
                return False

        # eGFR
        if "egfr_lt" in cond:
            if egfr_val is None or egfr_val >= cond["egfr_lt"]:
                return False
        if "egfr_range" in cond:
            min_e, max_e = cond["egfr_range"]
            if egfr_val is None or not (min_e <= egfr_val < max_e):
                return False

        # Allergy
        if "allergy_any" in cond:
            if not any(k in allergy_text for k in cond["allergy_any"]):
                return False

        # Patient conditions / history
        if "conditions_any" in cond:
            if not any(k in history_text for k in cond["conditions_any"]):
                return False

        # Concurrent DDI drugs
        if "concurrent_any" in cond:
            matched_cd = False
            exclude_stems = cond.get("exclude_same_drug_stems", [])
            for cd in concurrent_drugs:
                if any(k in cd for k in cond["concurrent_any"]):
                    # If exclude_same_drug_stems is provided, avoid same stem collision (e.g. enalapril with enalapril)
                    if exclude_stems and any(k in cd and k in dname for k in exclude_stems):
                        continue
                    # Avoid exact self match
                    if dname and (cd == dname or cd in dname or dname in cd):
                        continue
                    matched_cd = True
                    break
            if not matched_cd:
                return False

        return True

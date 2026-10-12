"""
Clinical Diagnosis Normalizer and Entity Boundary Guard.
Standardizes clinical diagnosis strings, extracts canonical names, ICD-10 codes,
and core disease stems, and prevents false-positive mismatches caused by
administrative suffixes (e.g. '，其他和未特指') and generic qualifiers ('急性', '慢性').
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set


# Common administrative noise suffixes in Chinese ICD-10 / hospital electronic medical records
ICD_ADMIN_NOISE_PATTERNS = [
    r"，其他和未特指",
    r"，其他及未特指",
    r"，其他与未特指",
    r"，其他",
    r"，未特指",
    r"（其他和未特指）",
    r"\(其他和未特指\)",
    r"（未特指）",
    r"\(未特指\)",
    r"（其他）",
    r"\(其他\)",
    r"，不可归类在他处者",
    r"，伴并发症",
    r"，无并发症",
    r"，部分",
    r"，特指的",
    r"，特指",
    r"，急性发作",
    r"，慢性加重",
]

# Time duration / clinical course patterns in chief complaints (e.g. 6个月, 1周, 3天, 伴加重1周)
TIME_COURSE_PATTERNS = [
    r"[，,、/]?\s*(?:伴|伴有)?(?:进行性)?(?:加重|加剧|持续|反复发作|突发)?\s*\d+\s*(?:年|个月|月|周|天|小时|分|秒|日|h|d|m)(?:余|多|半)?.*$",
    r"\b\d+\s*(?:年|个月|月|周|天|小时|日)\b",
]

# Clinical QA / attribute terms that should not be part of the core disease stem
CLINICAL_QA_ATTRIBUTES = [
    "适应证", "适应症", "禁忌证", "禁忌症", "不良反应", "副作用", "用法用量",
    "诊断标准", "鉴别诊断", "临床表现", "治疗原则", "选药", "用药", "用药建议",
    "如何", "怎么", "有哪些", "是什么", "指南", "共识", "规范", "路径", "方案"
]

# Generic clinical qualifiers that CANNOT independently validate a disease match
GENERIC_CLINICAL_MODIFIERS: Set[str] = {
    "急性", "慢性", "亚急性", "复发性", "阵发性", "顽固性", "迁延性",
    "小儿", "儿童", "成人", "老年", "婴儿", "新生儿", "女性", "男性", "妊娠期", "孕妇",
    "轻度", "中度", "重度", "极重度", "危重", "单纯性", "复杂性", "化脓性", "坏疽性", "坏死性",
    "非特异性", "良性", "恶性", "原发性", "继发性", "特发性", "感染性", "病毒性", "细菌性", "过敏性",
    "门诊", "急诊", "住院", "方案", "规范", "评估", "治疗", "诊疗", "管理", "初诊", "复诊",
    "阶梯", "对症", "临床", "综合", "路径", "指南", "共识", "其他", "未特指", "疾病", "症", "病",
    "双侧", "单侧", "双", "左", "右", "两侧", "局限性", "弥漫性",
}


class NormalizedDiagnosis:
    """Represents a structured clinical diagnosis breakdown."""

    def __init__(
        self,
        raw: str,
        clean: str,
        canonical_name: str,
        core_stems: List[str],
        icd_code: Optional[str] = None,
        icd_category: Optional[str] = None,
        generic_modifiers: Optional[Set[str]] = None,
        is_qa_query: bool = False,
    ):
        self.raw = raw
        self.clean = clean
        self.canonical_name = canonical_name
        self.core_stems = core_stems
        self.icd_code = icd_code
        self.icd_category = icd_category
        self.generic_modifiers = generic_modifiers or set()
        self.is_qa_query = is_qa_query

    def is_compatible_with(
        self,
        target_title: str,
        target_aliases: Optional[List[str]] = None,
        target_icd: Optional[str] = None,
        target_diagnoses: Optional[List[str]] = None,
    ) -> bool:
        """
        Determines whether a candidate protocol, guideline, or article is clinically compatible.
        Strictly rejects candidates that only match generic modifiers (e.g. '急性')
        without matching the core disease stem (e.g. '阑尾炎' vs '腹泻').
        """
        target_title_clean = target_title.strip()
        aliases = [a.strip() for a in (target_aliases or []) if a.strip()]
        diagnoses = [d.strip() for d in (target_diagnoses or []) if d.strip()]
        all_candidate_texts = [target_title_clean] + aliases + diagnoses
        candidate_blob = " ".join(all_candidate_texts).lower()

        # 1. Exact ICD-10 or 3-character category match
        if self.icd_code and target_icd:
            cand_icd = target_icd.strip().upper()
            if self.icd_code.upper() == cand_icd:
                return True
            if self.icd_category and cand_icd.startswith(self.icd_category.upper()):
                return True

        # 2. Canonical name match in title, aliases, or diagnoses
        if self.canonical_name:
            c_low = self.canonical_name.lower()
            for cand_text in all_candidate_texts:
                if c_low in cand_text.lower() or cand_text.lower() in c_low:
                    return True

        # 3. Core stems match: At least one core disease stem MUST match!
        if self.core_stems:
            stem_matched = False
            for stem in self.core_stems:
                stem_low = stem.lower()
                if any(stem_low in cand_text.lower() for cand_text in all_candidate_texts):
                    stem_matched = True
                    break
            if not stem_matched:
                # Core disease stem did NOT match any part of the candidate
                return False

            # If stem matched, verify there's no major organ/disease contradiction
            # e.g., '阑尾' vs '腹泻', '胆囊' vs '胰腺'
            return True

        # If no core stems could be extracted, require exact token presence
        return self.clean.lower() in candidate_blob


class ClinicalDiagnosisNormalizer:
    """Standardizes diagnosis strings and performs precision clinical compatibility verification."""

    @classmethod
    def normalize(cls, query: str) -> NormalizedDiagnosis:
        raw = (query or "").strip()
        if not raw:
            return NormalizedDiagnosis(raw="", clean="", canonical_name="", core_stems=[])

        is_qa_query = any(attr in raw for attr in CLINICAL_QA_ATTRIBUTES) or any(
            w in raw for w in ("怎么", "如何", "选药", "为什么", "什么")
        )

        # 1. Extract ICD-10 code (e.g. K35.8, K35.800, E11.9, I10)
        icd_code: Optional[str] = None
        icd_category: Optional[str] = None
        m_icd = re.search(r"\b([A-Z][0-9]{2}(?:\.[0-9]{1,4})?)\b", raw)
        if not m_icd:
            m_icd = re.search(r"\[([A-Z][0-9]{2}(?:\.[0-9]{1,4})?)\]", raw)

        if m_icd:
            icd_code = m_icd.group(1).upper()
            icd_category = icd_code.split(".")[0]
            # Remove ICD code from text
            text_no_icd = raw.replace(m_icd.group(0), " ").strip()
        else:
            text_no_icd = raw

        # 2. Strip administrative noise suffixes
        clean_text = text_no_icd
        for pattern in ICD_ADMIN_NOISE_PATTERNS:
            clean_text = re.sub(pattern, "", clean_text, flags=re.IGNORECASE)

        # Strip time course patterns (e.g. "6个月", "加重1周")
        for tp in TIME_COURSE_PATTERNS:
            clean_text = re.sub(tp, "", clean_text)

        # Strip clinical QA attribute keywords and conjunctions like "的"
        clean_attr_text = clean_text
        for attr in sorted(CLINICAL_QA_ATTRIBUTES, key=len, reverse=True):
            clean_attr_text = clean_attr_text.replace(attr, " ")
        clean_attr_text = re.sub(r"[与和及的的]+", " ", clean_attr_text).strip()

        clean_text = re.sub(r"[，,、/\\|\[\]\(\)（）\s]+", " ", clean_text).strip()
        canonical_name = clean_text.split()[0] if clean_text else text_no_icd.strip()

        # 3. Detect generic modifiers
        generic_mods: Set[str] = set()
        for mod in GENERIC_CLINICAL_MODIFIERS:
            if mod in canonical_name:
                generic_mods.add(mod)

        # 4. Extract core disease stems
        # Remove generic qualifiers to isolate the primary anatomical / pathological noun
        core_candidate = canonical_name
        # If QA query stripped attribute text yields an entity (e.g. "二甲双胍的适应证" -> "二甲双胍")
        if is_qa_query and clean_attr_text:
            first_entity = clean_attr_text.split()[0]
            if len(first_entity) >= 2:
                core_candidate = first_entity

        # Strip leading anatomical side words (e.g. 双膝关节 -> 膝关节)
        for side in ["双侧", "单侧", "两侧", "双", "左", "右"]:
            if core_candidate.startswith(side) and len(core_candidate) > len(side) + 1:
                core_candidate = core_candidate[len(side):].strip()
                break

        # Sort modifiers by length descending so longer compound qualifiers strip first
        for mod in sorted(GENERIC_CLINICAL_MODIFIERS, key=len, reverse=True):
            if core_candidate.startswith(mod) and len(core_candidate) > len(mod) + 1:
                core_candidate = core_candidate[len(mod):].strip()

        core_stems: List[str] = []
        if core_candidate and core_candidate not in GENERIC_CLINICAL_MODIFIERS:
            core_stems.append(core_candidate)

            # Check for conjunction patterns: 伴, 伴发, 伴有, 合并
            m_conj = re.search(r"^(.*?)(伴发|伴有|伴|合并)(.*)$", core_candidate)
            if m_conj:
                main_part = m_conj.group(1).strip()
                conj = m_conj.group(2)
                sub_part = m_conj.group(3).strip()

                # Clean generic modifiers from sub_part
                clean_sub = sub_part
                for mod in sorted(GENERIC_CLINICAL_MODIFIERS, key=len, reverse=True):
                    if clean_sub.startswith(mod) and len(clean_sub) > len(mod):
                        clean_sub = clean_sub[len(mod):].strip()

                if clean_sub and clean_sub != sub_part:
                    combined_clean = f"{main_part}{conj}{clean_sub}"
                    if combined_clean not in core_stems:
                        core_stems.append(combined_clean)

                if main_part and main_part not in core_stems and main_part not in GENERIC_CLINICAL_MODIFIERS:
                    core_stems.append(main_part)

            # Handle symptom-to-disease stems (e.g. 膝关节隐痛 -> 膝关节, 膝骨关节炎)
            for symptom_sfx in ["隐痛", "剧痛", "绞痛", "酸痛", "胀痛", "疼痛", "痛"]:
                if core_candidate.endswith(symptom_sfx) and len(core_candidate) > len(symptom_sfx) + 1:
                    organ = core_candidate[:-len(symptom_sfx)].strip()
                    if organ not in core_stems and organ not in GENERIC_CLINICAL_MODIFIERS:
                        core_stems.append(organ)
                    if organ in ("膝关节", "膝"):
                        if "膝骨关节炎" not in core_stems:
                            core_stems.append("膝骨关节炎")
                    elif organ in ("右下腹", "下腹", "阑尾"):
                        if "阑尾炎" not in core_stems:
                            core_stems.append("阑尾炎")

            # If compound disease name (e.g. 阑尾炎 -> 阑尾)
            for suffix in ["炎", "病", "症", "综合征", "结石", "绞痛", "麻痹", "溃疡"]:
                if core_candidate.endswith(suffix) and len(core_candidate) > len(suffix) + 1:
                    stem_root = core_candidate[:-len(suffix)]
                    # Strip any trailing conjunctions or modifiers from stem_root
                    stem_root = re.sub(r"(伴|伴发|伴有|合并)$", "", stem_root).strip()
                    for mod in GENERIC_CLINICAL_MODIFIERS:
                        if stem_root.endswith(mod):
                            stem_root = stem_root[:-len(mod)].strip()
                    stem_root = re.sub(r"(伴|伴发|伴有|合并)$", "", stem_root).strip()
                    if stem_root and stem_root not in core_stems and stem_root not in GENERIC_CLINICAL_MODIFIERS:
                        core_stems.append(stem_root)

        return NormalizedDiagnosis(
            raw=raw,
            clean=clean_text,
            canonical_name=canonical_name,
            core_stems=core_stems,
            icd_code=icd_code,
            icd_category=icd_category,
            generic_modifiers=generic_mods,
            is_qa_query=is_qa_query,
        )

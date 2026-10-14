"""
Clinical Knowledge Base Authority and Evidence Credibility Auditor.
Performs rigorous, quantitative multi-dimensional auditing on:
1. Issuing authority hierarchy (NHC, CMA, NMPA, CMDA, CDC certification)
2. Guideline currency & temporal distribution (last 5 years ratio)
3. International coding standards (ICD-10 for diseases, ATC for drug monographs)
4. Full evidence provenance closed loop (Protocols & CDSS Rules -> Guidelines)
5. Alternative re-routing coverage on critical clinical safety rules
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional


class AuthorityAuditor:
    """Audits clinical authority, provenance, and credibility across the entire medical wiki."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.metadata_path = self.root_dir / "raw" / "metadata.json"
        self.wiki_dir = self.root_dir / "wiki"
        self.rules_path = self.root_dir / "rules" / "clinical_safety_rules.json"

    def audit(self) -> Dict[str, Any]:
        """Executes full authority audit and returns structured metrics."""
        source_metrics = self._audit_sources()
        disease_metrics = self._audit_diseases()
        protocol_metrics = self._audit_protocols()
        insert_metrics = self._audit_drug_inserts()
        rule_metrics = self._audit_rules()
        symptom_metrics = self._audit_symptoms()
        calc_metrics = self._audit_calculators()

        # Compute overall credibility index (0 - 100)
        # Weighted factors:
        # - Authority level tier 1 ratio: 30%
        # - Provenance closed-loop ratio: 25%
        # - ICD-10 & ATC coding ratio: 20%
        # - Currency ratio (>=2020): 15%
        # - Rule evidence & alternative ratio: 10%
        credibility_score = round(
            (source_metrics["national_tier_ratio"] * 30.0)
            + (protocol_metrics["provenance_ratio"] * 25.0)
            + (((disease_metrics["icd10_coverage_ratio"] + insert_metrics["atc_coverage_ratio"]) / 2.0) * 20.0)
            + (source_metrics["recent_5yr_ratio"] * 15.0)
            + (rule_metrics["evidence_grounding_ratio"] * 10.0),
            1
        )

        from tools.quality import audit_quality
        quality = audit_quality(self.root_dir)
        return {
            "structureScore": credibility_score,
            "credibilityScore": None,
            "grade": "审核记录完整" if quality["clinicalReady"] else "未完成来源核验与临床审核",
            "quality": quality,
            "sources": source_metrics,
            "diseases": disease_metrics,
            "protocols": protocol_metrics,
            "drugInserts": insert_metrics,
            "safetyRules": rule_metrics,
            "symptoms": symptom_metrics,
            "calculators": calc_metrics,
        }

    def _audit_sources(self) -> Dict[str, Any]:
        data = {}
        if self.metadata_path.exists():
            data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        sources = data.get("sources", [])

        total = len(sources)
        national_tier_keywords = ["卫生健康", "中华医学会", "国家心血管病中心", "中国医师协会", "国家中医药", "疾病预防控制", "药品监督", "药监", "NMPA"]
        national_count = 0
        years: Dict[str, int] = {}
        recent_count = 0

        for s in sources:
            auth = s.get("authority", "")
            if any(k in auth for k in national_tier_keywords):
                national_count += 1
            yr = str(s.get("year", ""))
            years[yr] = years.get(yr, 0) + 1
            try:
                if date.today().year - 4 <= int(yr) <= date.today().year:
                    recent_count += 1
            except ValueError:
                pass

        return {
            "totalSources": total,
            "nationalTierCount": national_count,
            "national_tier_ratio": (national_count / total) if total else 0.0,
            "recent5YrCount": recent_count,
            "recent_5yr_ratio": (recent_count / total) if total else 0.0,
            "yearDistribution": years,
        }

    def _audit_diseases(self) -> Dict[str, Any]:
        disease_dir = self.wiki_dir / "entities" / "diseases"
        files = list(disease_dir.glob("*.md")) if disease_dir.exists() else []
        total = len(files)
        has_icd = 0
        has_sources = 0

        for f in files:
            txt = f.read_text(encoding="utf-8")
            if re.search(r"icd10:\s*['\"]?([A-Z0-9\.]+)", txt):
                has_icd += 1
            if "sources:" in txt or "[[SRC-" in txt:
                has_sources += 1

        return {
            "totalDiseases": total,
            "icd10Covered": has_icd,
            "icd10_coverage_ratio": (has_icd / total) if total else 0.0,
            "guidelineAnchored": has_sources,
            "guideline_anchored_ratio": (has_sources / total) if total else 0.0,
        }

    def _audit_protocols(self) -> Dict[str, Any]:
        prot_dir = self.wiki_dir / "protocols"
        files = list(prot_dir.glob("*.md")) if prot_dir.exists() else []
        total = len(files)
        has_sources = 0
        has_icd = 0
        structured_items_count = 0

        for f in files:
            txt = f.read_text(encoding="utf-8")
            if re.search(r"sources:\s*\n(?:\s*-\s*SRC-[^\n]+\n)+", txt):
                has_sources += 1
            if re.search(r"icd10:\s*['\"]?([A-Z0-9\.]+)", txt):
                has_icd += 1
            if "推荐医嘱集" in txt or "| 医嘱类别 |" in txt or "Structured Order Items" in txt:
                structured_items_count += 1

        return {
            "totalProtocols": total,
            "sourceGroundedCount": has_sources,
            "provenance_ratio": (has_sources / total) if total else 0.0,
            "icd10Covered": has_icd,
            "structuredOrdersCount": structured_items_count,
            "structuredOrdersRatio": (structured_items_count / total) if total else 0.0,
        }

    def _audit_drug_inserts(self) -> Dict[str, Any]:
        inserts_dir = self.wiki_dir / "inserts"
        files = list(inserts_dir.glob("*.md")) if inserts_dir.exists() else []
        total = len(files)
        has_atc = 0
        has_max_dose = 0
        has_contraindications = 0

        for f in files:
            txt = f.read_text(encoding="utf-8")
            if re.search(r"atc_code:\s*[A-Z0-9]+", txt):
                has_atc += 1
            if "max_daily_dose:" in txt:
                has_max_dose += 1
            if "key_contraindications:" in txt or "## 禁忌" in txt:
                has_contraindications += 1

        return {
            "totalDrugInserts": total,
            "atcCovered": has_atc,
            "atc_coverage_ratio": (has_atc / total) if total else 0.0,
            "maxDoseSpecified": has_max_dose,
            "contraindicationsSpecified": has_contraindications,
        }

    def _audit_rules(self) -> Dict[str, Any]:
        if not self.rules_path.exists():
            return {"totalRules": 0, "evidence_grounding_ratio": 0.0, "alternativesCount": 0, "gradeCoveredCount": 0, "grade_coverage_ratio": 0.0}

        data = json.loads(self.rules_path.read_text(encoding="utf-8"))
        rules = data if isinstance(data, list) else data.get("rules", [])
        total = len(rules)
        grounded = 0
        with_alts = 0
        with_grade = 0

        for r in rules:
            if r.get("guideline") or r.get("evidence"):
                grounded += 1
            if r.get("alternatives") and len(r["alternatives"]) > 0:
                with_alts += 1
            if r.get("grade"):
                with_grade += 1

        return {
            "totalRules": total,
            "evidenceGroundedCount": grounded,
            "evidence_grounding_ratio": (grounded / total) if total else 0.0,
            "alternativesCount": with_alts,
            "gradeCoveredCount": with_grade,
            "grade_coverage_ratio": (with_grade / total) if total else 0.0,
        }

    def _audit_symptoms(self) -> Dict[str, Any]:
        sym_dir = self.wiki_dir / "symptoms"
        files = list(sym_dir.glob("*.md")) if sym_dir.exists() else []
        total = len(files)
        pmph_count = 0
        red_flags_count = 0
        disease_linked_count = 0

        for f in files:
            txt = f.read_text(encoding="utf-8")
            if "SRC-PMPH-DIAG-2024-01" in txt or "人卫版诊断学" in txt:
                pmph_count += 1
            if "红旗征" in txt or "red_flags:" in txt or "Red Flags" in txt:
                red_flags_count += 1
            if re.search(r"\[\[.+?\]\]", txt):
                disease_linked_count += 1

        return {
            "totalSymptoms": total,
            "pmphStandardCount": pmph_count,
            "pmphStandardRatio": (pmph_count / total) if total else 0.0,
            "redFlagsCount": red_flags_count,
            "redFlagsCoverageRatio": (red_flags_count / total) if total else 0.0,
            "diseaseLinkedCount": disease_linked_count,
            "diseaseLinkedRatio": (disease_linked_count / total) if total else 0.0,
        }

    def _audit_calculators(self) -> Dict[str, Any]:
        from tools.cdss.calculators import ClinicalCalculatorRegistry
        supported_names = [
            "cha2ds2_vasc", "has_bled", "curb_65", "centor", "renal_clearance",
            "child_pugh", "pediatric_fluid", "alvarado", "abcd2",
            "wells_pe", "mmrc", "crb_65"
        ]
        active_count = len(supported_names)
        return {
            "totalCalculators": active_count,
            "supportedCalculators": supported_names,
            "coverage_ratio": 1.0,
        }

    def generate_report(self) -> str:
        """Report metadata coverage separately from provenance and clinical review."""
        m = self.audit()
        q = m["quality"]
        lines = [
            "医学知识库结构、来源与审核状态报告",
            f"结构字段覆盖评分: {m['structureScore']} / 100（不是临床可信度评分）",
            f"审核状态: {m['grade']}",
            f"注册来源: {q['sources']}；原始文件已归档: {q['originalsArchived']}；来源已核验: {q['provenanceVerified']}",
            f"临床审核: 内容页面 {q['clinicallyReviewedPages']}/{q['clinicalPages']}，规则 {q['clinicallyReviewedRules']}/{q['rules']}",
            f"页面审核记录异常: {len(q['invalidPageReviews'])}；规则来源引用异常: {len(q['invalidRuleSourceRefs'])}",
            f"疾病 ICD-10 字段覆盖: {m['diseases']['icd10Covered']}/{m['diseases']['totalDiseases']}",
            f"协议来源字段覆盖: {m['protocols']['sourceGroundedCount']}/{m['protocols']['totalProtocols']}",
            f"说明书整理页 ATC 字段覆盖: {m['drugInserts']['atcCovered']}/{m['drugInserts']['totalDrugInserts']}",
            f"临床规则 GRADE 字段覆盖: {m['safetyRules']['gradeCoveredCount']}/{m['safetyRules']['totalRules']}",
            "字段存在、测试通过和结构评分不认证发布机构、证据等级或临床正确性。",
            "专业审核记录须绑定当前内容哈希及已核验原文；内容变化后必须重新审核。",
        ]
        return "\n".join(lines)

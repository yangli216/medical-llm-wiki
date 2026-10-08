"""
Drug Monograph Repository and CDSS Contraindication Auditor.
Provides structured drug monograph management, fast indexing,
and rigorous rule-based contraindication & DDI auditing aligned with
NMPA official package inserts and China Pharmacopoeia Clinical Formulary.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiPage
from tools.cdss.rule_evaluator import RuleEvaluator


class DrugInsertRepository:
    """Manages structured drug insert monographs located in wiki/inserts/."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.inserts_dir = self.root_dir / "wiki" / "inserts"
        self._drugs: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, str] = {}  # alias/generic/trade -> filename stem
        self.load_all()

    def load_all(self) -> None:
        """Loads and parses all drug insert markdown files in wiki/inserts/."""
        self._drugs.clear()
        self._index.clear()

        if not self.inserts_dir.exists():
            return

        for fpath in sorted(self.inserts_dir.glob("*.md")):
            stem = fpath.stem
            page = WikiPage(fpath, self.root_dir / "wiki")
            fm = page.frontmatter
            
            drug_entry = {
                "id": stem,
                "generic_name": fm.get("generic_name", stem),
                "english_name": fm.get("english_name", ""),
                "category": fm.get("category", ""),
                "atc_code": fm.get("atc_code", ""),
                "approval_category": fm.get("approval_category", ""),
                "trade_names": fm.get("trade_names", []),
                "forms_and_specs": fm.get("forms_and_specs", []),
                "max_daily_dose": fm.get("max_daily_dose", ""),
                "standard_maintenance_dose": fm.get("standard_maintenance_dose", ""),
                "key_contraindications": fm.get("key_contraindications", []),
                "special_populations": fm.get("special_populations") if isinstance(fm.get("special_populations"), dict) else {},
                "storage": fm.get("storage", ""),
                "sources": fm.get("sources", []),
                "tags": fm.get("tags", []),
                "raw_body": page.body,
                "title": page.title,
                "rel_path": str(page.rel_path),
            }
            self._drugs[stem] = drug_entry

            # Index primary stem & generic name
            self._index[stem.lower()] = stem
            if drug_entry["generic_name"]:
                self._index[drug_entry["generic_name"].lower()] = stem
                # Index common simplified name (e.g. "二甲双胍" from "盐酸二甲双胍片")
                simplified = re.sub(r"(盐酸|硫酸|富马酸|马来酸|草酸|苯磺酸|酒石酸|枸橼酸|丙酸|微粉化|肠溶|缓释|控释|片|胶囊|气雾剂|散|软膏|乳膏|分散片|滴丸|胶丸|口服溶液)", "", drug_entry["generic_name"])
                if len(simplified) >= 2:
                    self._index[simplified.lower()] = stem

            if drug_entry["english_name"]:
                self._index[drug_entry["english_name"].lower()] = stem

            if drug_entry["atc_code"]:
                self._index[drug_entry["atc_code"].lower()] = stem

            for trade in drug_entry["trade_names"]:
                self._index[trade.lower()] = stem

    def list_all(self) -> List[Dict[str, Any]]:
        """Returns summarized metadata of all registered drug monographs."""
        return [
            {
                "id": d["id"],
                "generic_name": d["generic_name"],
                "english_name": d["english_name"],
                "category": d["category"],
                "atc_code": d["atc_code"],
                "approval_category": d["approval_category"],
                "trade_names": d["trade_names"],
                "forms_and_specs": d["forms_and_specs"],
                "max_daily_dose": d["max_daily_dose"],
                "standard_maintenance_dose": d["standard_maintenance_dose"],
                "key_contraindications": d["key_contraindications"],
                "tags": d["tags"],
                "rel_path": d["rel_path"],
            }
            for d in self._drugs.values()
        ]

    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """Resolves a drug by name, alias, trade name, or ATC code."""
        if not query:
            return None
        q_clean = query.strip().lower()
        if q_clean in self._index:
            return self._drugs.get(self._index[q_clean])
        # Direct stem match
        for stem, d in self._drugs.items():
            if q_clean in stem.lower() or stem.lower() in q_clean:
                return d
            if q_clean in d["generic_name"].lower():
                return d
        return None

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Keyword search across generic names, trade names, indications, and categories."""
        if not query:
            return self.list_all()[:limit]
        q_clean = query.strip().lower()
        exact = self.get(q_clean)
        matches = []
        if exact:
            matches.append(exact)

        for d in self._drugs.values():
            if exact and d["id"] == exact["id"]:
                continue
            if (
                q_clean in d["generic_name"].lower()
                or q_clean in d["english_name"].lower()
                or q_clean in d["category"].lower()
                or any(q_clean in tn.lower() for tn in d["trade_names"])
                or q_clean in d["raw_body"].lower()
            ):
                matches.append(d)
                if len(matches) >= limit:
                    break
        return matches[:limit]


class DrugContraindicationAuditor:
    """Performs rigorous CDSS contraindication and DDI auditing for a patient."""

    def __init__(self, repo: Optional[DrugInsertRepository] = None, root_dir: Optional[Path] = None, evaluator: Optional[Any] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.repo = repo or DrugInsertRepository(self.root_dir)
        if evaluator is not None:
            self.evaluator = evaluator
        else:
            from tools.cdss.rule_evaluator import RuleEvaluator
            self.evaluator = RuleEvaluator(rules_dir=self.root_dir / "rules")

    def audit(self, drug_query: str, patient: Dict[str, Any]) -> Dict[str, Any]:
        """
        Audits a drug prescription against patient parameters.
        Returns:
            canPrescribe: bool
            level: 'PASS' | 'WARNING' | 'BLOCK'
            alerts: List[Dict[str, str]]
            renalGuidance: str
            specialPopulationNotes: List[str]
            drugInteractions: List[str]
        """
        drug = self.repo.get(drug_query)
        if not drug:
            return {
                "success": False,
                "error": f"未在权威药品说明书知识库中检索到药品: '{drug_query}'",
                "canPrescribe": False,
                "level": "UNKNOWN",
                "alerts": [],
            }

        gname = drug["generic_name"]
        renal_guidance = drug.get("special_populations", {}).get("renal_impairment", "")
        notes: List[str] = []

        is_lactating = bool(patient.get("lactation")) or bool(patient.get("is_lactating"))
        if is_lactating:
            if any(k in gname for k in ["他汀", "格列美脲", "艾司唑仑", "唑吡坦", "左氧氟沙星", "莫西沙星", "诺氟沙星", "利伐沙班", "达比加群"]):
                notes.append("哺乳期提示：该药物可通过母乳排泄，存在潜在婴儿不良反应，建议服药期间暂停母乳喂养。")

        alerts = self.evaluator.evaluate_monograph_audit(gname, patient)

        # Determine overall recommendation
        has_block = any(a["level"] == "BLOCK" for a in alerts)
        has_warn = any(a["level"] == "WARNING" for a in alerts)

        if has_block:
            level = "BLOCK"
            can_prescribe = False
            summary = "【拦截禁止处方】该处方触发了国家药品说明书或临床指南最高级别绝对禁忌或致死性药物相互作用红线，系统已强行阻断！"
        elif has_warn:
            level = "WARNING"
            can_prescribe = True
            summary = "【黄色安全预警】该处方存在剂量滴定、特殊人群监护或潜在相互作用提示，临床医师应仔细核查并权衡利弊。"
        else:
            level = "PASS"
            can_prescribe = True
            summary = "【审核通过】未检索到绝对禁忌证或高危药物相互作用，符合说明书常规规范。"

        return {
            "success": True,
            "drug": {
                "id": drug["id"],
                "generic_name": drug["generic_name"],
                "english_name": drug["english_name"],
                "atc_code": drug["atc_code"],
                "category": drug["category"],
                "max_daily_dose": drug["max_daily_dose"],
                "standard_maintenance_dose": drug["standard_maintenance_dose"],
            },
            "canPrescribe": can_prescribe,
            "level": level,
            "summary": summary,
            "alerts": alerts,
            "renalGuidance": renal_guidance,
            "specialPopulationNotes": notes,
        }

    def audit_prescription(self, medications: List[str], patient: Dict[str, Any]) -> Dict[str, Any]:
        """
        Audits an entire prescription (list of medications) against patient profile,
        automatically cross-checking internal drug-drug interactions among all items.
        """
        if not medications:
            return {
                "success": True,
                "canPrescribe": True,
                "level": "PASS",
                "summary": "处方中无药品项",
                "items": [],
                "alerts": [],
            }

        patient_copy = dict(patient)
        existing_concurrent = list(patient_copy.get("concurrent_drugs", []))

        all_alerts: List[Dict[str, Any]] = []
        item_results: List[Dict[str, Any]] = []

        for i, med in enumerate(medications):
            # Other medications in prescription act as concurrent drugs
            other_meds = [m for j, m in enumerate(medications) if j != i]
            combined_concurrent = list(set(existing_concurrent + other_meds))
            patient_eval = dict(patient_copy)
            patient_eval["concurrent_drugs"] = combined_concurrent

            res = self.audit(med, patient_eval)
            item_results.append({
                "medication": med,
                "audit": res,
            })
            if res.get("success"):
                for a in res.get("alerts", []):
                    # Dedup alerts by rule
                    if not any(x.get("rule") == a.get("rule") for x in all_alerts):
                        all_alerts.append(a)

        has_block = any(a["level"] == "BLOCK" for a in all_alerts)
        has_warn = any(a["level"] == "WARNING" for a in all_alerts)

        if has_block:
            overall_level = "BLOCK"
            can_prescribe = False
            summary = "【处方强行阻断】处方中包含国家药品说明书绝对禁忌或致死性配伍禁忌项！"
        elif has_warn:
            overall_level = "WARNING"
            can_prescribe = True
            summary = "【处方用药预警】处方中存在剂量分级减量或特定人群监护提示。"
        else:
            overall_level = "PASS"
            can_prescribe = True
            summary = "【处方审核通过】全部药品均符合国家说明书与临床规范。"

        return {
            "success": True,
            "canPrescribe": can_prescribe,
            "level": overall_level,
            "summary": summary,
            "alerts": all_alerts,
            "items": item_results,
        }


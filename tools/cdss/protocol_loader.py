"""
Protocol loader for Medical LLM Wiki CDSS.
Parses structured clinical decision protocols in wiki/protocols/
and extracts models aligned with the RHN outpatient AI contracts.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class ClinicalProtocolItem:
    def __init__(
        self,
        kind: str,
        name: str,
        spec: str,
        details: str,
        order_draft_raw: str,
        source_quote: str = "",
        origin: str = "SUGGESTED",
    ):
        self.kind = kind
        self.name = name
        self.spec = spec
        self.details = details
        self.order_draft_raw = order_draft_raw
        self.source_quote = source_quote
        self.origin = origin
        self.parsed_order = self._parse_order_draft()

    def _parse_order_draft(self) -> Dict[str, Any]:
        """Parses structured order attributes for RHN order draft."""
        res: Dict[str, Any] = {
            "type": self.kind,
            "name": self.name,
            "specification": self.spec if self.spec != "-" else None,
            "rationale": self.details,
            "orderDraft": None,
        }
        if self.kind == "MEDICATION" and self.order_draft_raw and self.order_draft_raw != "-":
            route = "PO"
            freq = "QD"
            dose_val = None
            dose_unit = "mg"
            duration_days = 30

            if "routeCode" in self.order_draft_raw or "frequencyCode" in self.order_draft_raw:
                m_route = re.search(r"routeCode[`:\s]+([^<\n,`]+)", self.order_draft_raw)
                m_freq = re.search(r"frequencyCode[`:\s]+([^<\n,`]+)", self.order_draft_raw)
                m_dose = re.search(r"doseValue[`:\s]+([\d\.]+)", self.order_draft_raw)
                m_unit = re.search(r"doseUnit[`:\s]+([^<\n,`]+)", self.order_draft_raw)
                m_dur = re.search(r"durationValue[`:\s]+(\d+)", self.order_draft_raw)
                if m_route:
                    route = m_route.group(1).strip()
                if m_freq:
                    freq = m_freq.group(1).strip()
                if m_dose:
                    try:
                        dose_val = float(m_dose.group(1))
                    except ValueError:
                        pass
                if m_unit:
                    dose_unit = m_unit.group(1).strip()
                if m_dur:
                    try:
                        duration_days = int(m_dur.group(1))
                    except ValueError:
                        pass
            else:
                parts = [p.strip() for p in self.order_draft_raw.split(",")]
                route = parts[0] if len(parts) > 0 else "PO"
                freq = parts[1] if len(parts) > 1 else "QD"
                dose_str = parts[2] if len(parts) > 2 else ""
                duration_str = parts[3] if len(parts) > 3 else "30天"

                if dose_str:
                    m = re.search(r"([\d\.]+)\s*([a-zA-Zμg]+)", dose_str)
                    if m:
                        try:
                            dose_val = float(m.group(1))
                            dose_unit = m.group(2)
                        except ValueError:
                            pass
                m_dur = re.search(r"(\d+)", duration_str)
                if m_dur:
                    duration_days = int(m_dur.group(1))

            if dose_val is None:
                m_det = re.search(r"每次\s*([\d\.]+)\s*([a-zA-Zμg片粒包袋吸贴]+)", self.details)
                if not m_det and self.spec:
                    m_det = re.search(r"([\d\.]+)\s*([a-zA-Zμg]+)", self.spec)
                if m_det:
                    try:
                        dose_val = float(m_det.group(1))
                        dose_unit = m_det.group(2)
                    except ValueError:
                        pass

            res["orderDraft"] = {
                "routeCode": route,
                "frequencyCode": freq,
                "doseValue": dose_val or 1.0,
                "doseUnit": dose_unit,
                "durationValue": duration_days,
                "quantity": 1,
                "instruction": self.details.split("；")[0] if "；" in self.details else self.details,
            }
        return res

    def to_rhn_intent_item(self) -> Dict[str, Any]:
        """Converts to com.rhn.ai.application.ClinicalAiModelGateway.PlanIntentItem format."""
        return {
            "kind": self.kind,
            "name": self.name,
            "sourceQuote": self.source_quote,
            "origin": self.origin,
            "details": self.details,
        }


class ClinicalProtocol:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.raw_text = file_path.read_text(encoding="utf-8")
        self.frontmatter: Dict[str, Any] = {}
        self.protocol_id: str = ""
        self.title: str = ""
        self.icd10: str = ""
        self.category: str = ""
        self.aliases: List[str] = []
        self.sources: List[str] = []
        self.summary: str = ""
        self.note_template: Dict[str, str] = {}
        self.items: List[ClinicalProtocolItem] = []
        self.rules: List[Dict[str, str]] = []
        self._parse()

    def _parse(self) -> None:
        self._parse_frontmatter()
        self._parse_summary()
        self._parse_note_template()
        self._parse_items()
        self._parse_rules()

    def _parse_frontmatter(self) -> None:
        if not self.raw_text.startswith("---"):
            return
        parts = self.raw_text.split("---", 2)
        if len(parts) < 3:
            return
        raw_yaml = parts[1]
        current_list_key = None
        for line in raw_yaml.splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            if clean.startswith("- ") and current_list_key:
                val = clean[2:].strip().strip('"').strip("'")
                if current_list_key in self.frontmatter and isinstance(self.frontmatter[current_list_key], list):
                    self.frontmatter[current_list_key].append(val)
                continue

            if ":" in clean:
                current_list_key = None
                key, val = clean.split(":", 1)
                k = key.strip()
                v = val.strip().strip('"').strip("'")
                if not v:
                    self.frontmatter[k] = []
                    current_list_key = k
                else:
                    self.frontmatter[k] = v

        self.protocol_id = str(self.frontmatter.get("protocol_id", self.file_path.stem))
        self.title = str(self.frontmatter.get("title", ""))
        self.icd10 = str(self.frontmatter.get("icd10", ""))
        self.category = str(self.frontmatter.get("category", ""))
        raw_aliases = self.frontmatter.get("aliases", [])
        if isinstance(raw_aliases, list):
            self.aliases = [str(a) for a in raw_aliases]
        elif isinstance(raw_aliases, str) and raw_aliases:
            self.aliases = [raw_aliases]
        raw_sources = self.frontmatter.get("sources", [])
        if isinstance(raw_sources, list):
            self.sources = [str(s) for s in raw_sources]
        elif isinstance(raw_sources, str) and raw_sources:
            self.sources = [raw_sources]

    def _parse_summary(self) -> None:
        m = re.search(r"## 1\. 临床方案概述.*?\n(.*?)(?=\n## 2\.|\Z)", self.raw_text, re.DOTALL)
        if m:
            self.summary = m.group(1).strip()

    def _parse_note_template(self) -> None:
        """Extracts the 6-part outpatient medical record template."""
        sections = {
            "chiefComplaint": r"### 主诉 \(chiefComplaint\)\s*\n(.*?)(?=\n###|\n##|\Z)",
            "presentIllness": r"### 现病史 \(presentIllness\)\s*\n(.*?)(?=\n###|\n##|\Z)",
            "medicalHistory": r"### 既往史 \(medicalHistory\)\s*\n(.*?)(?=\n###|\n##|\Z)",
            "physicalExam": r"### 体格检查 \(physicalExam\)\s*\n(.*?)(?=\n###|\n##|\Z)",
            "healthEducation": r"### 健康宣教 \(healthEducation\)\s*\n(.*?)(?=\n###|\n##|\Z)",
            "followUp": r"### (?:复诊与随访计划|随访计划|复诊随访计划) \(followUp\)\s*\n(.*?)(?=\n###|\n##|\Z)",
        }
        for key, pattern in sections.items():
            m = re.search(pattern, self.raw_text, re.DOTALL)
            if m:
                # Clean up formatting
                val = m.group(1).strip()
                self.note_template[key] = val

    def _parse_items(self) -> None:
        """Parses structured markdown table rows."""
        table_pattern = re.search(r"\| (?:类别 \(kind\)|类型).*?\n(.*?)(?=\n## 4\.|\Z)", self.raw_text, re.DOTALL)
        if not table_pattern:
            return
        table_body = table_pattern.group(1).strip()
        for line in table_body.splitlines():
            line = line.strip()
            if not line.startswith("|") or line.startswith("| :---"):
                continue
            # Protect escaped pipes \| from table column splitting
            safe_line = line.replace(r"\|", "__ESCAPED_PIPE__")
            cells = [c.replace("__ESCAPED_PIPE__", "|").strip() for c in safe_line.split("|")[1:-1]]
            if len(cells) >= 5:
                kind = re.sub(r"[\*\_]", "", cells[0]).strip()
                raw_name = cells[1].strip()
                # Clean wiki links [[Target|Alias]] -> Alias or Target
                clean_name = raw_name
                m_alias = re.search(r"\[\[.*?\|(.*?)\]\]", raw_name)
                if m_alias:
                    clean_name = m_alias.group(1).strip()
                else:
                    m_link = re.search(r"\[\[(.*?)\]\]", raw_name)
                    if m_link:
                        clean_name = m_link.group(1).strip()

                spec = cells[2].strip()
                if len(cells) >= 6:
                    usage = cells[3].strip()
                    order_draft = cells[4].strip()
                    rationale = cells[5].strip()
                    details = f"用法：{usage}；依据：{rationale}" if rationale and usage != "-" else (rationale or usage)
                else:
                    details = cells[3].strip()
                    order_draft = cells[4].strip()

                item = ClinicalProtocolItem(
                    kind=kind,
                    name=clean_name,
                    spec=spec,
                    details=details,
                    order_draft_raw=order_draft,
                    source_quote="",
                    origin="SUGGESTED",
                )
                self.items.append(item)

    def _parse_rules(self) -> None:
        """Extracts CDSS rules."""
        m = re.search(r"## 4\. CDSS 用药前置拦截与警戒规则.*?\n(.*?)(?=\n## 5\.|\Z)", self.raw_text, re.DOTALL)
        if not m:
            return
        rules_text = m.group(1).strip()
        # Parse numbered rule items
        rule_blocks = re.split(r"\n(?=\d+\.\s+\*\*)", rules_text)
        for block in rule_blocks:
            block = block.strip()
            if not block:
                continue
            title_match = re.search(r"^\d+\.\s+\*\*(.+?)\*\*:\s*\n?(.*)", block, re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()
                desc = title_match.group(2).strip()
                severity = "RED" if "阻断" in title or "禁忌" in title else "YELLOW"
                self.rules.append({
                    "title": title,
                    "description": desc,
                    "severity": severity,
                })

    def to_rhn_plan_intent(self) -> Dict[str, Any]:
        """Builds com.rhn.ai.application.ClinicalAiModelGateway.PlanIntent record structure."""
        kind_order = {
            "DIAGNOSIS": 1,
            "CONDITION": 2,
            "MEDICATION": 3,
            "LABORATORY": 4,
            "EXAMINATION": 5,
            "EDUCATION": 6,
            "FOLLOW_UP": 7,
        }
        sorted_items = sorted(self.items, key=lambda x: kind_order.get(x.kind, 99))
        narrative_parts = []
        for item in sorted_items:
            prefix = {
                "DIAGNOSIS": "诊断",
                "CONDITION": "适用条件",
                "MEDICATION": "用药",
                "LABORATORY": "检验",
                "EXAMINATION": "检查",
                "EDUCATION": "健康宣教",
                "FOLLOW_UP": "复诊与随访",
            }.get(item.kind, "其他")
            narrative_parts.append(f"{prefix}：{item.name}（{item.details}）")
        narrative = "\n".join(narrative_parts)

        return {
            "name": self.title,
            "description": f"依据国家权威指南建立的门诊标准化诊疗协议（ICD-10: {self.icd10}）",
            "noteTemplateContent": self.note_template,
            "items": [it.to_rhn_intent_item() for it in sorted_items],
            "referenceTemplateId": None,
            "narrative": narrative,
        }

    def to_rhn_plan_candidate(self, candidate_id: int = 1) -> Dict[str, Any]:
        """Builds com.rhn.ai.application.ClinicalAiModelGateway.PlanCandidate record structure."""
        diagnoses = [it.name for it in self.items if it.kind == "DIAGNOSIS"]
        medications = [f"{it.name} {it.spec}" for it in self.items if it.kind == "MEDICATION"]
        services = [it.name for it in self.items if it.kind in ("LABORATORY", "EXAMINATION")]
        tasks = [it.name for it in self.items if it.kind in ("EDUCATION", "FOLLOW_UP")]

        return {
            "id": candidate_id,
            "name": self.title,
            "description": f"{self.category}门诊规范指南路径方案 [ICD: {self.icd10}]",
            "diagnoses": diagnoses or [f"{self.title} [{self.icd10}]"],
            "medications": medications,
            "services": services,
            "tasks": tasks,
            "retrievalEvidence": [
                f"GUIDELINE:{s}" for s in self.sources
            ] + [f"ICD10:{self.icd10}", f"CATEGORY:{self.category}"],
        }

    def to_rhn_treatment_recommendations(self) -> List[Dict[str, Any]]:
        """Builds List<ClinicalAiTreatmentRecommendation> for the outpatient doctor panel."""
        recs = []
        for idx, it in enumerate(self.items):
            if it.kind in ("MEDICATION", "LABORATORY", "EXAMINATION"):
                item_dict = it.parsed_order
                recs.append({
                    "type": it.kind,
                    "catalogItemId": f"STD-{self.protocol_id}-{idx+1}",
                    "code": f"{self.icd10}-{it.kind[:3]}-{idx+1}",
                    "name": it.name,
                    "specification": it.spec if it.spec != "-" else None,
                    "rationale": it.details,
                    "orderDraft": item_dict.get("orderDraft"),
                })
        return recs


class ProtocolRepository:
    """Manages loading and indexing of all clinical decision protocols."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.protocols_dir = self.root_dir / "wiki" / "protocols"
        self.protocols: Dict[str, ClinicalProtocol] = {}
        self.load_all()

    def load_all(self) -> None:
        self.protocols.clear()
        if not self.protocols_dir.exists():
            return
        for md_path in sorted(self.protocols_dir.glob("*.md")):
            prot = ClinicalProtocol(md_path)
            self.protocols[prot.protocol_id] = prot

    def get(self, protocol_id: str) -> Optional[ClinicalProtocol]:
        return self.protocols.get(protocol_id)

    def list_all(self) -> List[ClinicalProtocol]:
        return list(self.protocols.values())

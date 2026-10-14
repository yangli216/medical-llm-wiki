"""KnowledgeApiMixin extracted from the HTTP entrypoint."""

import re
import urllib.parse
from typing import Any, Dict, List


class KnowledgeApiMixin:
    def _handle_knowledge_search(self, payload: Dict[str, Any]) -> None:
        """Adapts to RHN PmphaiClinicalKnowledgeGateway ProviderResult[] protocol."""
        query = payload.get("query") or ""
        limit = int(payload.get("limit", 5))
        hits = self.searcher.search(query, limit=limit)
        results = []
        for h in hits:
            sources = h.get("sources", [])
            lib_name = sources[0] if sources else "国家卫生健康委员会临床诊疗指南与规范"
            results.append({
                "id": h["id"],
                "name": h["title"],
                "content": h.get("snippet", ""),
                "score": round(float(h.get("score", 1.0)) / 100.0, 4),
                "resourcePos": h.get("rel_path", ""),
                "sourceInfo": {
                    "knowledgeLibName": lib_name,
                    "knowledgeLibId": f"LIB-{h['id'].upper()}",
                    "publishYear": "2024",
                },
                "aiAbstract": h.get("snippet", ""),
            })
        self._send_json(results)

    def _handle_wiki_doc(self, query_params: Dict[str, List[str]]) -> None:
        """
        Universal document retrieval endpoint for drug inserts, clinical guidelines,
        disease entities, and decision protocols.
        """
        raw_name = query_params.get("name", [""])[0].strip()
        raw_id = query_params.get("id", [""])[0].strip()
        raw_path = query_params.get("path", [""])[0].strip()
        doc_type = query_params.get("type", [""])[0].strip().lower()

        target = raw_id or raw_name or raw_path
        if not target:
            self._send_json({"error": "Missing query parameter 'id', 'name', or 'path'"}, status=400)
            return

        # 1. Try drug monograph if type is medication/drug/insert or (not specified and not starting with SRC- or PROT-)
        if doc_type in ("drug", "insert", "medication") or (doc_type == "" and not target.startswith("SRC-") and not target.startswith("PROT-")):
            candidates = [target]
            token0 = target.split()[0].strip() if " " in target else ""
            if token0 and token0 not in candidates:
                candidates.append(token0)
            token_paren = re.split(r'[（\(]', target)[0].strip()
            if token_paren and token_paren not in candidates:
                candidates.append(token_paren)
            token_cleaned = re.sub(r'[\s0-9\.\*gmg片粒盒袋/]+$', '', target).strip()
            if token_cleaned and token_cleaned not in candidates:
                candidates.append(token_cleaned)

            d = None
            for cand in candidates:
                d = self.drug_repo.get(cand)
                if d:
                    break

            if not d:
                for cand in candidates:
                    drug_matches = self.drug_repo.search(cand, limit=1)
                    if drug_matches:
                        d = drug_matches[0]
                        break

            if d:
                html_body = self._markdown_to_html(d["raw_body"])
                self._send_json({
                    "id": d["id"],
                    "title": d["title"],
                    "type": "MEDICATION",
                    "category": d["category"],
                    "genericName": d["generic_name"],
                    "englishName": d["english_name"],
                    "atcCode": d["atc_code"],
                    "approvalCategory": d["approval_category"],
                    "tradeNames": d["trade_names"],
                    "formsAndSpecs": d["forms_and_specs"],
                    "maxDailyDose": d["max_daily_dose"],
                    "standardMaintenanceDose": d["standard_maintenance_dose"],
                    "keyContraindications": d["key_contraindications"],
                    "specialPopulations": d["special_populations"],
                    "storage": d["storage"],
                    "sources": d["sources"],
                    "tags": d["tags"],
                    "relPath": d["rel_path"],
                    "markdown": d["raw_body"],
                    "html": html_body,
                })
                return
            elif doc_type in ("drug", "insert", "medication"):
                # If explicitly querying a drug monograph, do not fallback to unrelated wiki documents
                self._send_json({"error": "Drug monograph not found", "query": target}, status=404)
                return

        from tools.cdss.diagnosis_normalizer import ClinicalDiagnosisNormalizer
        norm = ClinicalDiagnosisNormalizer.normalize(target)

        # 2. Try protocol repository if type is protocol, guideline, or (not specified and not starting with SRC-)
        if doc_type in ("protocol", "guideline") or (doc_type == "" and not target.startswith("SRC-")):
            prot = self.cdss.repo.get(target) or self.cdss.repo.get(norm.canonical_name)
            if not prot and raw_name:
                matches = self.cdss.search_protocols(raw_name, limit=1)
                if matches:
                    prot = self.cdss.repo.get(matches[0]["protocolId"])
            if prot:
                html_body = self._markdown_to_html(prot.raw_text)
                self._send_json({
                    "id": prot.protocol_id,
                    "title": prot.title,
                    "type": "protocol",
                    "category": prot.category,
                    "icd10": prot.icd10,
                    "aliases": prot.aliases,
                    "sources": prot.sources,
                    "summary": prot.summary,
                    "relPath": f"protocols/{prot.file_path.name}",
                    "markdown": prot.raw_text,
                    "html": html_body,
                    "items": [it.to_rhn_intent_item() for it in prot.items],
                })
                return
            elif doc_type == "protocol":
                self._send_json({
                    "error": "该病种暂未收录临床方案",
                    "query": target,
                    "canonical": norm.canonical_name,
                    "not_found": True
                }, status=404)
                return

        # 3. Try WikiGraph (concepts, entities, sources)
        lookup_targets = [target]
        if norm.canonical_name and norm.canonical_name not in lookup_targets:
            lookup_targets.append(norm.canonical_name)
        if norm.clean and norm.clean not in lookup_targets:
            lookup_targets.append(norm.clean)

        page = None
        for cand_target in lookup_targets:
            resolved_link = self.graph.resolve_link(cand_target) or cand_target
            clean_id = re.sub(r"\.md$", "", resolved_link).split("/")[-1]
            resolved = self.graph.resolve_link(clean_id) or clean_id
            page = self.graph.pages.get(resolved) or self.graph.pages.get(cand_target)
            if not page:
                for sub in ("sources", "concepts", "entities/diseases", "entities"):
                    p_cand = self.root_dir / "wiki" / sub / f"{clean_id}.md"
                    if p_cand.exists():
                        from tools.compiler.compiler import WikiPage
                        page = WikiPage(p_cand, self.root_dir / "wiki")
                        break
            if page:
                break

        if page:
            html_body = self._markdown_to_html(page.raw_text)
            self._send_json({
                "id": page.file_path.stem,
                "title": page.title,
                "type": page.frontmatter.get("type", "wiki_page"),
                "category": page.frontmatter.get("category", ""),
                "frontmatter": page.frontmatter,
                "relPath": str(page.rel_path),
                "markdown": page.raw_text,
                "html": html_body,
            })
            return

        # 4. Search fallback: find closest matching article with strict clinical compatibility
        if doc_type in ("", "wiki", "concept", "source", "guideline"):
            search_query = norm.canonical_name or target
            search_hits = self.searcher.search(search_query, limit=3)
            compatible_page = None
            for hit in search_hits:
                hit_page = self.graph.pages.get(hit["id"])
                if not hit_page:
                    continue
                aliases = hit_page.frontmatter.get("aliases", [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                icd = hit_page.frontmatter.get("icd10")
                if norm.is_compatible_with(hit_page.title, aliases, icd):
                    compatible_page = hit_page
                    break

            if compatible_page:
                html_body = self._markdown_to_html(compatible_page.raw_text)
                self._send_json({
                    "id": compatible_page.file_path.stem,
                    "title": compatible_page.title,
                    "type": compatible_page.frontmatter.get("type", "wiki_page"),
                    "frontmatter": compatible_page.frontmatter,
                    "relPath": str(compatible_page.rel_path),
                    "markdown": compatible_page.raw_text,
                    "html": html_body,
                })
                return

        # Explicitly return 404 with clinical 'not_found' prompt if unindexed
        self._send_json({
            "error": "该病种暂未收录临床指南或诊疗方案",
            "query": target,
            "canonical": norm.canonical_name,
            "not_found": True
        }, status=404)

    def _handle_evidence_chain(self, payload: Dict[str, Any]) -> None:
        """
        Derives clinical evidence reasoning checklist, gap orders, and guideline citations.
        """
        diag_name = payload.get("diagnosis") or payload.get("diagnosisName") or payload.get("query") or ""
        diag_code = payload.get("diagnosisCode") or payload.get("code") or ""
        patient = payload.get("patient") or {}

        if not patient and ("vitals" in payload or "chiefComplaint" in payload):
            patient = {
                "age": payload.get("age"),
                "gender": payload.get("gender"),
                "chiefComplaint": payload.get("chiefComplaint"),
                "presentIllness": payload.get("presentIllness"),
                "physicalExam": payload.get("physicalExam"),
                "medicalHistory": payload.get("medicalHistory"),
                "vitals": payload.get("vitals", {}),
            }

        res = self.evidence_engine.evaluate(diag_name, diag_code, patient)
        self._send_json(res)

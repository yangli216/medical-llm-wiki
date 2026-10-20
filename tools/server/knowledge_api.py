"""KnowledgeApiMixin extracted from the HTTP entrypoint."""

import re
import urllib.parse
from typing import Any, Dict, List


class KnowledgeApiMixin:
    def _handle_knowledge_search(self, payload: Dict[str, Any]) -> None:
        """Adapts to RHN PmphaiClinicalKnowledgeGateway ProviderResult[] protocol with ICD priority."""
        query = payload.get("query") or ""
        limit = int(payload.get("limit", 5))
        icd_code = payload.get("icd10") or payload.get("icd") or payload.get("code")
        if not icd_code and query:
            from tools.cdss.icd_mapper import ICDMapper
            icd_code = ICDMapper.extract_icd(query)

        hits = self.searcher.search(query, limit=limit)
        results = []
        if icd_code:
            prot = self.cdss.repo.get_by_icd(icd_code)
            page = self.graph.resolve_by_icd(icd_code, type_hint="disease")
            matched_ids = set()
            if prot:
                matched_ids.add(prot.protocol_id)
                results.append({
                    "id": prot.protocol_id,
                    "name": prot.title,
                    "content": prot.summary or prot.raw_text[:200],
                    "score": 1.0,
                    "resourcePos": f"protocols/{prot.file_path.name}",
                    "sourceInfo": {
                        "knowledgeLibName": "国家卫生健康委员会临床路径与方案指南库",
                        "knowledgeLibId": f"LIB-{prot.protocol_id}",
                        "publishYear": "2024",
                    },
                    "aiAbstract": prot.summary or "",
                })
            if page and page.file_path.stem not in matched_ids:
                matched_ids.add(page.file_path.stem)
                results.append({
                    "id": page.file_path.stem,
                    "name": page.title,
                    "content": page.body[:200],
                    "score": 0.98,
                    "resourcePos": str(page.rel_path),
                    "sourceInfo": {
                        "knowledgeLibName": "国家临床医学知识库",
                        "knowledgeLibId": f"LIB-{page.file_path.stem.upper()}",
                        "publishYear": "2024",
                    },
                    "aiAbstract": page.body[:200],
                })
            for h in hits:
                if h["id"] not in matched_ids:
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
            results = results[:limit]
        else:
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
        Supports explicit and implicit ICD-10 prioritised retrieval.
        """
        raw_name = query_params.get("name", [""])[0].strip()
        raw_id = query_params.get("id", [""])[0].strip()
        raw_path = query_params.get("path", [""])[0].strip()
        raw_icd = (
            query_params.get("icd10", [""])[0].strip()
            or query_params.get("icd", [""])[0].strip()
            or query_params.get("code", [""])[0].strip()
        )
        doc_type = query_params.get("type", [""])[0].strip().lower()

        target = raw_name or raw_id or raw_path or raw_icd
        alt_target = raw_id if target == raw_name and raw_id else (raw_name if target == raw_id and raw_name else "")
        if not target:
            self._send_json({"error": "Missing query parameter 'id', 'name', 'path', or 'icd10'"}, status=400)
            return

        from tools.cdss.icd_mapper import ICDMapper
        if not raw_icd:
            raw_icd = ICDMapper.extract_icd(target) or (ICDMapper.extract_icd(alt_target) if alt_target else "")

        # 0. High priority ICD-10 resolution
        if raw_icd:
            if doc_type in ("protocol", "guideline"):
                prot = self.cdss.repo.get_by_icd(raw_icd)
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
            elif doc_type in ("disease", "concept", "wiki", "entity") or doc_type == "":
                page = self.graph.resolve_by_icd(raw_icd, type_hint="disease")
                if page:
                    html_body = self._markdown_to_html(page.raw_text)
                    self._send_json({
                        "id": page.file_path.stem,
                        "title": page.title,
                        "type": page.page_type,
                        "category": page.frontmatter.get("category", ""),
                        "icd10": page.icd10,
                        "aliases": page.aliases,
                        "tags": page.tags,
                        "sources": page.sources,
                        "relPath": str(page.rel_path),
                        "markdown": page.raw_text,
                        "html": html_body,
                    })
                    return
                prot = self.cdss.repo.get_by_icd(raw_icd)
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

        # 1. Try drug monograph if type is medication/drug/insert/prescription/medicine or (not specified and not starting with SRC- or PROT-)
        if doc_type in ("drug", "insert", "medication", "prescription", "medicine") or (doc_type == "" and not target.startswith("SRC-") and not target.startswith("PROT-")):
            query_targets = [t for t in [target, alt_target] if t]
            candidates: List[str] = []
            for t_item in query_targets:
                if t_item not in candidates:
                    candidates.append(t_item)
                t_no_prefix = re.sub(r'^[\[【(（][^\]】)）]+[\]】)）]', '', t_item).strip()
                if t_no_prefix and t_no_prefix not in candidates:
                    candidates.append(t_no_prefix)

                for base in ([t_item, t_no_prefix] if t_no_prefix else [t_item]):
                    token0 = base.split()[0].strip() if " " in base else ""
                    if token0 and token0 not in candidates:
                        candidates.append(token0)
                    token_paren = re.split(r'[（\(\[【]', base)[0].strip()
                    if token_paren and token_paren not in candidates:
                        candidates.append(token_paren)
                    token_cleaned = re.sub(r'[\s0-9\.\*gmg片粒盒袋支/]+$', '', base).strip()
                    if token_cleaned and token_cleaned not in candidates:
                        candidates.append(token_cleaned)
                    token_both = re.sub(r'[\s0-9\.\*gmg片粒盒袋支/]+$', '', token_paren).strip()
                    if token_both and token_both not in candidates:
                        candidates.append(token_both)

            d = None
            for cand in candidates:
                d = self.drug_repo.get(cand)
                if d:
                    break

            if not d and doc_type in ("drug", "insert", "medication", "prescription", "medicine"):
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
            elif doc_type in ("drug", "insert", "medication", "prescription", "medicine"):
                # If explicitly querying a drug monograph, do not fallback to unrelated wiki documents
                self._send_json({"error": "Drug monograph not found", "query": target}, status=404)
                return

        from tools.cdss.diagnosis_normalizer import ClinicalDiagnosisNormalizer
        norm = ClinicalDiagnosisNormalizer.normalize(target)

        # 2. Try protocol repository if type is protocol, guideline, or starting with PROT-
        if doc_type in ("protocol", "guideline") or target.startswith("PROT-"):
            prot = self.cdss.repo.get(target)
            if not prot and raw_icd:
                prot = self.cdss.repo.get_by_icd(raw_icd)
            if not prot and raw_name and doc_type in ("protocol", "guideline"):
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
        if raw_icd and raw_icd not in lookup_targets:
            lookup_targets.append(raw_icd)
        if alt_target and alt_target not in lookup_targets:
            lookup_targets.append(alt_target)
        if norm.canonical_name and norm.canonical_name not in lookup_targets:
            lookup_targets.append(norm.canonical_name)
        if norm.clean and norm.clean not in lookup_targets:
            lookup_targets.append(norm.clean)
        for stem in norm.core_stems:
            if stem and stem not in lookup_targets:
                lookup_targets.append(stem)

        for base in list(lookup_targets):
            # 1. Strip brackets prefix (e.g. [检验], 【放射】)
            cand_no_prefix = re.sub(r'^[\[【(（][^\]】)）]+[\]】)）]', '', base).strip()
            if cand_no_prefix and cand_no_prefix not in lookup_targets:
                lookup_targets.append(cand_no_prefix)
            # 2. Strip parentheses / brackets (e.g. 血常规（五分类） -> 血常规)
            cand_no_paren = re.sub(r'[（\(\[【].*?[）\)\]】]', '', base).strip()
            if cand_no_paren and cand_no_paren not in lookup_targets:
                lookup_targets.append(cand_no_paren)
            # 3. Synonym swap X线 <-> X射线, 摄影 <-> 摄片, 彩超 <-> 超声
            for src, dst in (("X线", "X射线"), ("X射线", "X线"), ("摄片", "摄影"), ("摄影", "摄片"), ("彩超", "超声")):
                if src in base:
                    swapped = base.replace(src, dst)
                    if swapped not in lookup_targets:
                        lookup_targets.append(swapped)

        page = None
        for cand_target in lookup_targets:
            resolved_link = self.graph.resolve_link(cand_target) or cand_target
            clean_id = re.sub(r"\.md$", "", resolved_link).split("/")[-1]
            resolved = self.graph.resolve_link(clean_id) or clean_id
            page = self.graph.pages.get(resolved) or self.graph.pages.get(cand_target)
            if not page:
                for sub in ("sources", "concepts", "entities/diseases", "entities/tests", "entities/examinations", "entities"):
                    p_cand = self.root_dir / "wiki" / sub / f"{clean_id}.md"
                    if p_cand.exists():
                        from tools.compiler.compiler import WikiPage
                        page = WikiPage(p_cand, self.root_dir / "wiki")
                        break
            if page:
                break

        # 3.1 Direct test & examination alias / title scanner fallback
        if not page and doc_type in ("test", "exam", "examination", "lab", "imaging", "laboratory", "service", ""):
            for cand_target in lookup_targets:
                cand_low = cand_target.lower()
                clean_cand = re.sub(r'[\s0-9\.\*gmgml粒片盒袋/支μuiiu瓶丸包次日mgkg]+$', '', cand_low).strip()
                for p_id, p_obj in self.graph.pages.items():
                    if p_obj.frontmatter.get("type") in ("test", "examination"):
                        p_aliases = [a.lower() for a in p_obj.aliases]
                        p_title = p_obj.title.lower()
                        if cand_low == p_title or cand_low in p_aliases:
                            page = p_obj
                            break
                        if clean_cand and (clean_cand == p_title or clean_cand in p_aliases):
                            page = p_obj
                            break
                        if any(cand_low in a or a in cand_low for a in p_aliases if len(a) >= 3):
                            page = p_obj
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
        if doc_type in ("", "wiki", "concept", "source", "guideline", "test", "exam", "examination", "lab", "imaging"):
            search_query = norm.canonical_name or target
            search_hits = self.searcher.search(search_query, limit=5)
            if not search_hits and norm.core_stems:
                for stem in norm.core_stems:
                    if len(stem) >= 2:
                        search_hits = self.searcher.search(stem, limit=5)
                        if search_hits:
                            break
            compatible_page = None
            for hit in search_hits:
                hit_page = self.graph.pages.get(hit["id"])
                if not hit_page:
                    continue
                page_type = hit_page.frontmatter.get("type", "")
                aliases = hit_page.frontmatter.get("aliases", [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                if page_type in ("test", "examination"):
                    clean_t = re.sub(r'[\(（].*?[\)）]', '', target).strip().lower()
                    if (target.lower() in hit_page.title.lower() or
                        any(target.lower() in a.lower() for a in aliases) or
                        (clean_t and (clean_t in hit_page.title.lower() or any(clean_t in a.lower() for a in aliases)))):
                        compatible_page = hit_page
                        break
                elif norm.is_compatible_with(hit_page.title, aliases, hit_page.frontmatter.get("icd10")):
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

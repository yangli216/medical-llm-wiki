"""
Local Interactive Web Explorer for Medical LLM Wiki.
Powered by Python standard library http.server and embedded Single Page Application (SPA).
Features interactive knowledge graph visualization, real-time search, and markdown reader.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiGraph
from tools.search.searcher import WikiSearcher
from tools.collector.collector import SourceCollector
from tools.collector.pdf_parser import ClinicalPdfParser
from tools.cdss.engine import CdssEngine
from tools.cdss.drug_checker import DrugInsertRepository, DrugContraindicationAuditor
from tools.cdss.evidence_chain import EvidenceChainEngine
from tools.cdss.calculators import ClinicalCalculatorRegistry
from tools.server.rendering import markdown_to_html
from tools.server.chat_api import ChatApiMixin
from tools.server.knowledge_api import KnowledgeApiMixin
from tools.server.ingestion import SourceIngestionMixin
from tools.quality import inventory, audit_quality, local_file, page_review_status, sha256_file


STATIC_DIR = Path(__file__).resolve().parent / "static"


class WikiHTTPHandler(SourceIngestionMixin, KnowledgeApiMixin, ChatApiMixin, BaseHTTPRequestHandler):
    """Custom HTTP Handler for serving the Medical LLM Wiki application and API."""

    root_dir: Path = Path(__file__).resolve().parent.parent.parent
    graph: WikiGraph = WikiGraph(root_dir)
    searcher: WikiSearcher = WikiSearcher(root_dir)
    collector: SourceCollector = SourceCollector(root_dir)
    cdss: CdssEngine = CdssEngine(root_dir)
    drug_repo: DrugInsertRepository = DrugInsertRepository(root_dir)
    drug_auditor: DrugContraindicationAuditor = DrugContraindicationAuditor(drug_repo)
    evidence_engine: EvidenceChainEngine = EvidenceChainEngine(root_dir)
    pdf_parser: Optional[ClinicalPdfParser] = None

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-RHN-Prompt-Version")
        self.end_headers()

    def do_GET(self) -> None:
        raw_path = self.path
        try:
            raw_path = raw_path.encode("latin-1").decode("utf-8")
        except Exception:
            pass
        parsed_url = urllib.parse.urlparse(raw_path)
        path = parsed_url.path.rstrip("/") if parsed_url.path != "/" else "/"
        query_params = urllib.parse.parse_qs(parsed_url.query)

        if path == "/" or path == "/index.html":
            self._send_html((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
        elif path in ("/static/styles.css", "/static/app.js"):
            name = path.rsplit("/", 1)[-1]
            content = (STATIC_DIR / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif path == "/api/inventory":
            self._send_json(inventory(self.root_dir))
        elif path == "/api/quality":
            self._send_json(audit_quality(self.root_dir))
        elif path == "/api/health":
            sym_dir = self.root_dir / "wiki" / "symptoms"
            symptoms_count = len(list(sym_dir.glob("*.md"))) if sym_dir.exists() else 0
            self._send_json({
                "status": "UP",
                "version": "1.9.0",
                "service": "Medical LLM Wiki & CDSS Intelligence Gateway",
                "protocols": len(self.cdss.repo.list_all()),
                "rules": sum(r.get("domain") == "clinical" for r in self.cdss.evaluator.rules),
                "monograph_rules": sum(r.get("domain") == "monograph" for r in self.cdss.evaluator.rules),
                "drug_inserts": len(self.drug_repo.list_all()),
                "guidelines": len(self.collector.list_sources()),
                "symptoms": symptoms_count,
                "articles": len(self.graph.pages),
            })
        elif path in ("/v1/models", "/models"):
            self._send_json({
                "object": "list",
                "data": [
                    {
                        "id": "medical-cdss-wiki",
                        "object": "model",
                        "created": 1728300000,
                        "owned_by": "medical-llm-wiki",
                        "permission": [],
                        "root": "medical-cdss-wiki",
                        "parent": None,
                    }
                ]
            })
        elif path == "/api/cdss/calculators":
            self._send_json({
                "calculators": [
                    {"name": "cha2ds2_vasc", "title": "CHA2DS2-VASc 房颤卒中风险评估与抗凝决策", "params": ["age", "gender", "chf", "htn", "dm", "stroke", "vascular"]},
                    {"name": "has_bled", "title": "HAS-BLED 房颤抗凝出血风险评估", "params": ["age", "sbp_gt_160", "renal_disease", "liver_disease", "stroke_history", "bleeding_history", "labile_inr", "antiplatelet", "alcohol_abuse"]},
                    {"name": "curb_65", "title": "CURB-65 社区获得性肺炎严重度与收治场所", "params": ["age", "confusion", "bun", "rr", "sbp", "dbp"]},
                    {"name": "centor", "title": "Centor-McIsaac 急性咽扁桃体炎链球菌概率与抗菌决策", "params": ["age", "tonsil_exudate", "tender_cervical_nodes", "temp", "no_cough"]},
                    {"name": "renal_clearance", "title": "eGFR (2021 CKD-EPI) 与 Cockcroft-Gault 肾清除率", "params": ["age", "gender", "scr", "weight"]},
                    {"name": "child_pugh", "title": "Child-Pugh 肝硬化肝功能储备评分与分级", "params": ["bili", "alb", "inr", "ascites", "encephalopathy"]},
                    {"name": "pediatric_fluid", "title": "儿童急性腹泻脱水补液量估算 (Holliday-Segar + ORS-III)", "params": ["weight_kg", "dehydration"]},
                    {"name": "alvarado", "title": "Alvarado 急性阑尾炎临床预测评分与外科探查", "params": ["migratory_pain", "anorexia", "nausea_vomiting", "rlq_tenderness", "rebound_pain", "temp_elevated", "leukocytosis", "neutrophilia_shift"]},
                    {"name": "abcd2", "title": "ABCD2 短暂性脑缺血发作 TIA 早期卒中风险量化分层", "params": ["age", "sbp", "dbp", "unilateral_weakness", "speech_impairment", "duration_minutes", "diabetes"]},
                    {"name": "wells_pe", "title": "Wells 肺栓塞 PE 临床预测概率评分与 CTPA 决策", "params": ["dvt_signs", "pe_most_likely", "hr", "recent_surgery", "prior_pe", "hemoptysis", "cancer"]},
                    {"name": "mmrc", "title": "mMRC 呼吸困难评分与慢阻肺 GOLD ABE 吸入阶梯决策", "params": ["grade", "exacerbations_last_year", "hospitalizations_last_year", "eos_count"]},
                    {"name": "crb_65", "title": "CRB-65 门诊社区获得性肺炎严重度与分诊决策 (无须BUN)", "params": ["confusion", "rr", "sbp", "dbp", "age"]},
                ]
            })
        elif path == "/api/graph":
            self.graph.load_graph()
            data = self.graph.to_json_graph()
            self._send_json(data)
        elif path == "/api/search":
            q = query_params.get("q", [""])[0]
            hits = self.searcher.search(q, limit=12)
            self._send_json(hits)
        elif path == "/api/page":
            pid = query_params.get("id", ["index"])[0]
            resolved = self.graph.resolve_link(pid) or pid
            page = self.graph.pages.get(resolved)
            if not page and resolved == "index":
                idx_path = self.root_dir / "wiki" / "index.md"
                if idx_path.exists():
                    from tools.compiler.compiler import WikiPage
                    page = WikiPage(idx_path, self.root_dir / "wiki")

            if page:
                html_body = self._markdown_to_html(page.raw_text)
                self._send_json({
                    "id": resolved,
                    "title": page.title,
                    "frontmatter": page.frontmatter,
                    "clinicalReview": page_review_status(self.root_dir, page),
                    "html": html_body,
                })
            else:
                self._send_json({"error": "Page not found", "id": pid}, status=404)
        elif path in ("/api/sources", "/api/knowledge/sources"):
            sources = self.collector.list_sources()
            self._send_json(sources)
        elif path.startswith("/api/sources/") and path.endswith("/original"):
            sid = urllib.parse.unquote(path[len("/api/sources/"):-len("/original")])
            source = self.collector.get_source_by_id(sid)
            artifact = local_file(self.root_dir, source.get("original_file", "")) if source else None
            if not artifact or not artifact.is_relative_to((self.root_dir / "raw/originals").resolve()):
                self._send_json({"error": "原始文件尚未归档", "source_id": sid}, status=404)
            elif sha256_file(artifact) != source.get("original_sha256"):
                self._send_json({"error": "原始文件哈希不匹配，请重新核验"}, status=409)
            else:
                content = artifact.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf" if artifact.suffix == ".pdf" else "application/octet-stream")
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(artifact.name))
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        elif path == "/api/cdss/protocols":
            protocols = self.cdss.repo.list_all()
            data = [{
                "protocolId": p.protocol_id,
                "title": p.title,
                "icd10": p.icd10,
                "category": p.category,
                "summary": p.summary,
            } for p in protocols]
            self._send_json(data)
        elif path.startswith("/api/cdss/protocols/"):
            pid = path[len("/api/cdss/protocols/"):]
            prot = self.cdss.repo.get(pid)
            if prot:
                self._send_json({
                    "protocolId": prot.protocol_id,
                    "title": prot.title,
                    "icd10": prot.icd10,
                    "category": prot.category,
                    "summary": prot.summary,
                    "planIntent": prot.to_rhn_plan_intent(),
                    "candidate": prot.to_rhn_plan_candidate(1),
                    "treatmentRecommendations": prot.to_rhn_treatment_recommendations(),
                    "rules": prot.rules,
                })
            else:
                self._send_json({"error": "Protocol not found", "id": pid}, status=404)
        elif path == "/api/cdss/recommend":
            q = query_params.get("q", [""])[0]
            matches = self.cdss.search_protocols(q, limit=5)
            self._send_json(matches)
        elif path == "/api/drugs":
            category = query_params.get("category", [""])[0]
            q = query_params.get("q", [""])[0]
            if q:
                drugs = self.drug_repo.search(q, limit=20)
                data = [{
                    "id": d["id"],
                    "genericName": d["generic_name"],
                    "englishName": d["english_name"],
                    "category": d["category"],
                    "atcCode": d["atc_code"],
                    "approvalCategory": d["approval_category"],
                    "tradeNames": d["trade_names"],
                    "standardDosage": d["standard_maintenance_dose"],
                    "maxDailyDose": d["max_daily_dose"],
                    "keyContraindications": d["key_contraindications"],
                    "relPath": d["rel_path"],
                } for d in drugs]
            else:
                all_drugs = self.drug_repo.list_all()
                if category:
                    all_drugs = [d for d in all_drugs if category in d["category"]]
                data = [{
                    "id": d["id"],
                    "genericName": d["generic_name"],
                    "englishName": d["english_name"],
                    "category": d["category"],
                    "atcCode": d["atc_code"],
                    "approvalCategory": d["approval_category"],
                    "tradeNames": d["trade_names"],
                    "standardDosage": d["standard_maintenance_dose"],
                    "maxDailyDose": d["max_daily_dose"],
                    "keyContraindications": d["key_contraindications"],
                    "relPath": d["rel_path"],
                } for d in all_drugs]
            self._send_json(data)
        elif path.startswith("/api/drugs/"):
            raw_id = path[len("/api/drugs/"):]
            drug_name = urllib.parse.unquote(raw_id)
            d = self.drug_repo.get(drug_name)
            if d:
                html_body = self._markdown_to_html(d["raw_body"])
                self._send_json({
                    "id": d["id"],
                    "genericName": d["generic_name"],
                    "englishName": d["english_name"],
                    "category": d["category"],
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
                    "title": d["title"],
                    "relPath": d["rel_path"],
                    "html": html_body,
                })
            else:
                self._send_json({"error": "Drug monograph not found", "query": drug_name}, status=404)
        elif path in ("/api/wiki/doc", "/api/knowledge/doc"):
            self._handle_wiki_doc(query_params)
        elif path == "/api/symptoms":
            q = query_params.get("q", [""])[0].strip()
            sym_dir = self.root_dir / "wiki" / "symptoms"
            symptoms_list = []
            if sym_dir.exists():
                for f in sorted(sym_dir.glob("*.md")):
                    txt = f.read_text(encoding="utf-8")
                    title_m = re.search(r"title:\s*(.+)", txt)
                    id_m = re.search(r"id:\s*(.+)", txt)
                    title = title_m.group(1).strip() if title_m else f.stem
                    sym_id = id_m.group(1).strip() if id_m else f.stem
                    
                    aliases = []
                    alias_m = re.search(r"aliases:\s*\n((?:\s*-\s*[^\n]+\n)+)", txt)
                    if alias_m:
                        aliases = [l.strip()[2:].strip() for l in alias_m.group(1).splitlines() if l.strip().startswith("- ")]
                    
                    red_flags = []
                    rf_section = re.search(r"## 二、[^\n]*\n(.*?)(?=\n## |\Z)", txt, re.DOTALL)
                    if rf_section:
                        rf_lines = re.findall(r"-\s*\*\*([^*]+)\*\*", rf_section.group(1))
                        red_flags = rf_lines if rf_lines else []
                    
                    if q:
                        if (q.lower() not in title.lower() and 
                            not any(q.lower() in a.lower() for a in aliases) and
                            q.lower() not in txt.lower()):
                            continue
                            
                    symptoms_list.append({
                        "id": sym_id,
                        "title": title,
                        "aliases": aliases,
                        "redFlags": red_flags[:5],
                        "relPath": f"wiki/symptoms/{f.name}",
                    })
            self._send_json({"total": len(symptoms_list), "symptoms": symptoms_list})
        elif path.startswith("/api/symptoms/"):
            sym_id_or_name = urllib.parse.unquote(path[len("/api/symptoms/"):])
            sym_dir = self.root_dir / "wiki" / "symptoms"
            matched_file = None
            if sym_dir.exists():
                for f in sym_dir.glob("*.md"):
                    if f.stem == sym_id_or_name or f.name == sym_id_or_name:
                        matched_file = f
                        break
                    txt = f.read_text(encoding="utf-8")
                    if f"id: {sym_id_or_name}" in txt or f"title: {sym_id_or_name}" in txt:
                        matched_file = f
                        break
            if matched_file:
                raw_text = matched_file.read_text(encoding="utf-8")
                html_body = self._markdown_to_html(raw_text)
                self._send_json({
                    "id": matched_file.stem,
                    "title": matched_file.stem,
                    "rawText": raw_text,
                    "html": html_body,
                })
            else:
                self._send_json({"error": "Symptom differential tree not found", "query": sym_id_or_name}, status=404)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON body"}, status=400)
            return

        if path in ("/v1/chat/completions", "/chat/completions"):
            self._handle_chat_completions(payload)
        elif path in ("/api/knowledge/search", "/v1/knowledge/pmphai/search"):
            self._handle_knowledge_search(payload)
        elif path in ("/api/cdss/evidence-chain", "/api/knowledge/evidence-chain"):
            self._handle_evidence_chain(payload)
        elif path in ("/api/cdss/calculate", "/api/calculator"):
            calc_name = payload.get("calculator") or payload.get("name") or ""
            params = payload.get("params") or payload.get("parameters") or payload
            try:
                res = ClinicalCalculatorRegistry.calculate(calc_name, params)
                self._send_json({"success": True, "data": res})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=400)
        elif path == "/api/cdss/compile-rhn-plan":
            query = payload.get("input") or payload.get("naturalInput") or payload.get("protocolId") or ""
            res = self.cdss.compile_rhn_plan(query)
            status_code = 200 if res.get("success") else 404
            self._send_json(res, status=status_code)
        elif path == "/api/cdss/recommend":
            query = payload.get("query") or payload.get("input") or ""
            limit = int(payload.get("limit", 5))
            matches = self.cdss.search_protocols(query, limit=limit)
            self._send_json(matches)
        elif path == "/api/cdss/audit":
            meds = payload.get("medications", [])
            patient = payload.get("patient", {})
            audit_res = self.cdss.audit_prescription(meds, patient)
            self._send_json(audit_res)
        elif path in ("/api/cdss/preflight-safety", "/api/cdss/preflight", "/api/preflight-safety", "/api/knowledge/preflight-safety"):
            meds = payload.get("medications") or payload.get("meds") or payload.get("items") or []
            patient = payload.get("patient") or payload.get("patientContext") or payload.get("profile") or {}
            res = self.cdss.audit_preflight_safety(meds, patient)
            self._send_json(res)
        elif path == "/api/knowledge/parse-pdf":
            self._handle_parse_pdf(payload)
        elif path in ("/api/knowledge/import-source", "/api/sources/import"):
            self._handle_import_source(payload)
        elif path == "/api/drugs/check-contraindications":
            meds = payload.get("medications") or []
            if isinstance(meds, str):
                meds = [meds]
            single_drug = payload.get("drug")
            if single_drug and not meds:
                meds = [single_drug]
            patient = payload.get("patient", {})
            if len(meds) == 1:
                res = self.drug_auditor.audit(meds[0], patient)
            else:
                res = self.drug_auditor.audit_prescription(meds, patient)
            self._send_json(res)
        else:
            self.send_response(404)
            self.end_headers()

    def _markdown_to_html(self, md_text: str) -> str:
        return markdown_to_html(md_text)

    def _send_html(self, html_content: str) -> None:
        encoded = html_content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, data: Any, status: int = 200) -> None:
        path = urllib.parse.urlparse(self.path).path
        clinical_paths = {"/api/cdss/compile-rhn-plan", "/api/cdss/audit", "/api/cdss/preflight-safety",
                          "/api/cdss/preflight", "/api/preflight-safety", "/api/knowledge/preflight-safety",
                          "/api/drugs/check-contraindications", "/api/cdss/evidence-chain",
                          "/api/knowledge/evidence-chain"}
        if isinstance(data, dict) and path in clinical_paths and status == 200:
            ready = audit_quality(self.root_dir)["clinicalReady"]
            data = {**data, "clinicalReview": {"status": "approved" if ready else "pending",
                                              "requiresClinicianReview": not ready}}
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)


def run_server(port: int = 8080) -> None:
    server_address = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(server_address, WikiHTTPHandler)
    print(f"🚀 Medical LLM Wiki Web Server is running on http://127.0.0.1:{port} (Multi-threaded)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server.")
        httpd.server_close()

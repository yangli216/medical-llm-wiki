"""SourceIngestionMixin extracted from the HTTP entrypoint."""

import hashlib
import re
import threading
import urllib.parse
from datetime import datetime
from typing import Any, Dict
from tools.collector.pdf_parser import ClinicalPdfParser


class SourceIngestionMixin:
    _import_lock = threading.Lock()

    def _handle_import_source(self, payload: Dict[str, Any]) -> None:
        with self._import_lock:
            self._import_source(payload)

    def _handle_parse_pdf(self, payload: Dict[str, Any]) -> None:
        """
        Receives base64-encoded PDF or file bytes, parses clinical text,
        and automatically infers title, authority, year, category, summary,
        and linked disease entities.
        """
        b64_data = payload.get("pdf_base64") or payload.get("data") or ""
        filename = payload.get("filename") or "document.pdf"
        if not b64_data:
            self._send_json({"success": False, "error": "缺少 PDF 文件数据 (pdf_base64)"}, status=400)
            return

        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]

        import base64
        try:
            pdf_bytes = base64.b64decode(b64_data)
        except Exception as e:
            self._send_json({"success": False, "error": f"Base64 解码异常: {e}"}, status=400)
            return

        if not self.pdf_parser:
            known_diseases = [p.title for p in self.graph.pages.values() if p.page_type == "disease"]
            self.pdf_parser = ClinicalPdfParser(known_diseases=known_diseases)

        try:
            res = self.pdf_parser.parse_pdf_bytes(pdf_bytes, filename=filename)
            self._send_json(res)
        except Exception as e:
            self._send_json({"success": False, "error": f"PDF 解析失败: {e}"}, status=500)

    def _import_source(self, payload: Dict[str, Any]) -> None:
        """
        Imports and compiles a newly discovered clinical guideline or medical standard:
        1. Validates and generates metadata in raw/metadata.json
        2. Archives raw document markdown in raw/docs/{source_id}.md
        3. Compiles structured wiki study guide in wiki/sources/{source_id}.md
        4. Updates master index wiki/index.md and audit log wiki/log.md
        5. Updates SQLite FTS5 search index and in-memory WikiGraph
        """
        title = (payload.get("title") or "").strip()
        if not title:
            self._send_json({"success": False, "error": "指南/标准官方全称 (title) 不能为空"}, status=400)
            return

        authority = (payload.get("authority") or "未核验发布机构").strip()
        category = (payload.get("category") or "临床医学综合").strip()
        try:
            year = int(payload.get("year") or datetime.now().year)
        except (ValueError, TypeError):
            self._send_json({"success": False, "error": "发布年份必须为整数"}, status=400)
            return
        summary = (payload.get("summary") or f"收录《{title}》，规范临床诊疗路径与合理用药。").strip()
        content = (payload.get("content") or "").strip()
        source_id = (payload.get("source_id") or "").strip().upper()
        raw_related = payload.get("related_diseases") or []
        if isinstance(raw_related, str):
            related_items = [d.strip() for d in re.split(r"[,，、;；]", raw_related) if d.strip()]
        else:
            related_items = list(raw_related)

        # Generate source_id if not given
        if not source_id:
            abbr = re.sub(r"[^A-Za-z0-9]", "", category)[:4].upper() or "CLIN"
            existing_ids = {s["id"] for s in self.collector.list_sources()}
            counter = 1
            source_id = f"SRC-USER-{abbr}-{year}-{counter:02d}"
            while source_id in existing_ids:
                counter += 1
                source_id = f"SRC-USER-{abbr}-{year}-{counter:02d}"

        if not re.fullmatch(r"SRC-[A-Z0-9]+(?:-[A-Z0-9]+)*", source_id):
            self._send_json({"success": False, "error": "来源 ID 仅允许 SRC- 开头的字母、数字和连字符"}, status=400)
            return
        if self.collector.get_source_by_id(source_id) or (self.root_dir / "raw" / "docs" / f"{source_id}.md").exists():
            self._send_json({"success": False, "error": "来源 ID 已存在，请使用新版本 ID，避免覆盖原始资料"}, status=409)
            return
        official_url = (payload.get("official_url") or "").strip()
        parsed_url = urllib.parse.urlparse(official_url)
        if official_url and (parsed_url.scheme not in ("http", "https") or not parsed_url.netloc):
            self._send_json({"success": False, "error": "官方链接须使用 http 或 https"}, status=400)
            return
        pdf_raw = None
        pdf_rel = ""
        pdf_b64 = payload.get("pdf_base64") or ""
        if pdf_b64:
            import base64
            try:
                pdf_raw = base64.b64decode(pdf_b64.split(",", 1)[-1], validate=True)
                if not pdf_raw.startswith(b"%PDF-"):
                    raise ValueError("上传内容不是 PDF")
                # Reject corrupt PDFs before writing any project files.
                from pypdf import PdfReader
                from io import BytesIO
                if not PdfReader(BytesIO(pdf_raw)).pages:
                    raise ValueError("PDF 无有效页面")
            except Exception as exc:
                self._send_json({"success": False, "error": f"原始 PDF 无效: {exc}"}, status=400)
                return
            pdf_rel = f"raw/originals/{source_id}.pdf"
        # A pasted body may differ from a PDF; do not claim it is a faithful extraction.
        content_kind = "unverified_text" if content else "curated_summary"
        if not content:
            content = f"# 《{title}》整理摘要\n\n发布机构（待核验）：{authority}\n发布年份：{year}\n\n{summary}\n"
        # Preserve pasted text exactly; normalizing compiled pages must not alter archives.
        archived_content = content + ("" if content.endswith("\n") else "\n")
        file_rel = f"raw/docs/{source_id}.md"
        raw_doc_path = self.root_dir / file_rel
        raw_doc_path.parent.mkdir(parents=True, exist_ok=True)
        raw_doc_path.write_text(archived_content, encoding="utf-8")
        if pdf_raw:
            original_path = self.root_dir / pdf_rel
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(pdf_raw)
        self.collector.register_source(
            source_id, title, authority, year, category, file_rel, summary,
            level="待核验来源",
            provenance={"content_kind": content_kind, "official_url": official_url,
                        "doi": payload.get("doi") or "", "retrieved_at": datetime.now().astimezone().isoformat(),
                        "original_file": pdf_rel, "original_sha256": hashlib.sha256(pdf_raw).hexdigest() if pdf_raw else "",
                        "content_sha256": hashlib.sha256(archived_content.encode()).hexdigest()},
        )

        # 3. Resolve related disease links safely (only [[link]] if page exists)
        related_links_list = []
        for item in related_items:
            resolved = self.graph.resolve_link(item)
            if resolved and resolved in self.graph.pages:
                related_links_list.append(f"- [[{item}]]")
            else:
                related_links_list.append(f"- {item}")

        if not related_links_list:
            related_links_list = ["- [[index]] (医学知识库主索引)"]
        else:
            related_links_list.append("- [[index]] (医学知识库主索引)")

        related_links_text = "\n".join(related_links_list)

        core_points_lines = [p.strip() for p in summary.split("\n") if p.strip()]
        core_points_text = "\n".join([f"- {p}" for p in core_points_lines]) if core_points_lines else f"- {summary}"

        clean_title = title.replace("《", "").replace("》", "")
        today_str = datetime.now().strftime("%Y-%m-%d")
        original_link = f"[下载归档原件](/api/sources/{source_id}/original)（来源待核验）" if pdf_raw else "尚未取得或归档"
        publisher_link = f"[登记的发布页]({official_url})（待核验）" if official_url else "尚未登记"

        wiki_source_content = f"""---
title: 《{clean_title}》研读导读
type: source
tags:
  - 医学指南/{category}
  - 权威指南/动态录入
aliases:
  - 《{clean_title}》
  - {clean_title}
sources:
  - {source_id}
last_updated: "{today_str}"
status: draft
---

# 《{clean_title}》研读导读

> [!WARNING] 资料待核验、临床内容待审核
> 上传与解析不代表官方来源已核验；本页尚无医师或药师审核记录。
>
> [!NOTE] 来源元数据
> - **来源标识代码 (ID)**: `{source_id}`
> - **制定发布机构**: {authority}
> - **发布年份**: {year} 年
> - **专科分类**: {category}
> - **原始文件**: {original_link}
> - **发布链接**: {publisher_link}

---

## 一、 指南/规范核心要点提炼
{core_points_text}

---

## 二、 临床诊疗路径指引
1. **诊断与风险分层**：严格参照本规范推荐的诊断切点与分层评估流程。
2. **规范化干预方案**：优先选择一线推荐治疗与药物方案，注意禁忌证与特殊人群监护。
3. **随访与健康宣教**：实施连续性健康管理，指导患者规律复诊与危险因素干预。

---

## 三、 知识网络关联与适用疾病
{related_links_text}
"""
        wiki_source_content = wiki_source_content.replace("~", "～")
        wiki_source_path = self.root_dir / "wiki" / "sources" / f"{source_id}.md"
        wiki_source_path.parent.mkdir(parents=True, exist_ok=True)
        wiki_source_path.write_text(wiki_source_content.strip() + "\n", encoding="utf-8")

        # 4. Update wiki/index.md (add to sources table)
        index_path = self.root_dir / "wiki" / "index.md"
        if index_path.exists():
            idx_text = index_path.read_text(encoding="utf-8")
            clean_summary = summary.replace("\n", " ")[:60].replace("~", "～")
            new_row = f"| [[{source_id}]] | 《{clean_title}》 | {authority} | {category} | {clean_summary}... |\n"

            section_marker = "### J. 临床在线动态录入权威标准 (动态扩充)"
            if section_marker in idx_text:
                header = section_marker + "\n| 来源 ID | 官方指南全称 | 发布机构 | 专科领域 | 核心导读 |\n| :--- | :--- | :--- | :--- | :--- |\n"
                idx_text = idx_text.replace(header, header + new_row)
            else:
                table_block = f"{section_marker}\n| 来源 ID | 官方指南全称 | 发布机构 | 专科领域 | 核心导读 |\n| :--- | :--- | :--- | :--- | :--- |\n{new_row}\n---\n\n"
                insert_target = "## 2. 疾病与健康主诉实体库 (Diseases & Conditions)"
                if insert_target in idx_text:
                    idx_text = idx_text.replace(insert_target, table_block + insert_target)
                else:
                    idx_text = idx_text.replace("## 2. 疾病与健康主诉实体库", table_block + "## 2. 疾病与健康主诉实体库")

            # Bump count in overview block if present
            current_count = len(self.collector.list_sources())
            idx_text = re.sub(r"├── 1\. 权威来源层 \(wiki/sources/\)\s+->\s+\d+\s+部",
                              f"├── 1. 权威来源层 (wiki/sources/)           -> {current_count} 部", idx_text)
            index_path.write_text(idx_text, encoding="utf-8")

        # 5. Append to wiki/log.md
        log_path = self.root_dir / "wiki" / "log.md"
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8")
            log_entry = f"\n- **[Web在线录入]**: 新增收录权威标准《{clean_title}》（`{source_id}`，{authority}，{year}年）。\n"
            log_path.write_text(log_text.rstrip() + log_entry, encoding="utf-8")

        # 6. Re-index SQLite FTS5 incrementally
        try:
            self.searcher.index_wiki(incremental=True)
        except Exception as e:
            print(f"Index update warning: {e}")

        # 7. Reload in-memory graph
        self.graph.load_graph()

        self._send_json({
            "success": True,
            "source_id": source_id,
            "page_id": source_id,
            "title": f"《{clean_title}》",
            "review_status": "pending",
            "content_kind": content_kind,
            "message": f"《{clean_title}》已作为待审核资料收录，已建立导读与检索索引。原文来源及临床内容仍需核验。"
        })

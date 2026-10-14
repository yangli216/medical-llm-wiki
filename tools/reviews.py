"""Record supplied provenance and professional reviews, never infer approval."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from tools.collector.collector import SourceCollector
from tools.compiler.compiler import WikiGraph
from tools.quality import local_file, page_digest, review_valid, rule_digest, sha256_file, source_evidence


def archive_source(root: Path, source_id: str, artifact: Path, official_url: str) -> dict:
    from urllib.parse import urlparse
    parsed = urlparse(official_url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ValueError("请提供官方发布页或原文下载链接")
    collector = SourceCollector(root)
    metadata = collector.load_metadata()
    source = next((s for s in metadata["sources"] if s["id"] == source_id), None)
    if not source:
        raise ValueError("来源 ID 未注册")
    if source.get("original_file"):
        raise ValueError("该来源已有原始归档；新版本请使用新来源 ID")
    if not artifact.is_file():
        raise ValueError("原始文件不存在")
    digest = sha256_file(artifact)
    # Only PDF and text artifacts can be attached by this local workflow.
    suffix = artifact.suffix.lower()
    if suffix not in (".pdf", ".md", ".txt", ".html"):
        raise ValueError("支持 PDF、Markdown、文本或 HTML 原文")
    if not artifact.stat().st_size:
        raise ValueError("原始文件不能为空")
    if suffix == ".pdf":
        from pypdf import PdfReader
        try:
            if not PdfReader(artifact).pages:
                raise ValueError("PDF 无有效页面")
        except Exception as exc:
            raise ValueError(f"PDF 无效: {exc}") from exc
    target = root / "raw" / "originals" / f"{source_id}-{digest[:12]}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and sha256_file(target) != digest:
        raise ValueError("归档文件冲突")
    if artifact.resolve() != target.resolve():
        shutil.copyfile(artifact, target)
    source.update({"official_url": official_url, "original_file": str(target.relative_to(root)),
                   "original_sha256": digest, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                   "provenance_review": {"decision": "pending"}})
    collector.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return source


def record_review(root: Path, record: dict) -> None:
    kind, subject = record.get("kind"), record.get("subject")
    review = record.get("review", {})
    collector = SourceCollector(root)
    metadata = collector.load_metadata()
    sources = {s["id"]: s for s in metadata["sources"]}
    if kind == "source":
        source = sources.get(subject)
        if not (source and source_evidence(root, source)["originalArchived"] and
                source.get("official_url") and review.get("reviewer", "").strip() and
                review.get("reviewed_at") and review.get("decision") == "approved" and
                review.get("artifact_sha256") == source.get("original_sha256")):
            raise ValueError("来源核验记录缺少原文件、官方链接、审核人、日期或匹配的原文件哈希")
        datetime.fromisoformat(review["reviewed_at"])
        source["provenance_review"] = review
        collector.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    if kind == "page":
        page = WikiGraph(root).pages.get(subject)
        if not page or not review_valid(review, page_digest(page), sources, root):
            raise ValueError("页面审核缺少有效专业审核记录、来源核验、原文定位或匹配的内容哈希")
        if any(ref["source_id"] not in page.sources for ref in review["evidence_refs"]):
            raise ValueError("审核引用必须属于页面登记的来源")
        path = root / "reviews" / "clinical_reviews.json"
        data = json.loads(path.read_text()) if path.exists() else {"version": 1, "pages": {}}
        data["pages"][subject] = review
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        text = page.raw_text
        import re
        frontmatter, body = text.split("---", 2)[1:]
        frontmatter = re.sub(r"(?m)^status:.*$", "status: verified", frontmatter)
        page.file_path.write_text("---" + frontmatter + "---" + body, encoding="utf-8")
        return
    if kind == "rule":
        for path in sorted((root / "rules").glob("*.json")):
            data = json.loads(path.read_text())
            rules = data if isinstance(data, list) else data.get("rules", [])
            rule = next((r for r in rules if r["id"] == subject), None)
            if rule:
                if not review_valid(review, rule_digest(rule), sources, root):
                    raise ValueError("规则审核记录无效或内容哈希不匹配")
                rule["clinical_review"] = review
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return
    raise ValueError("未知审核对象；kind 必须为 source、page 或 rule")

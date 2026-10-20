"""Inventory and evidence checks; structural validation is not clinical review."""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime
from collections import Counter
from pathlib import Path
from typing import Any

from tools.collector.collector import SourceCollector
from tools.compiler.compiler import WikiGraph

CLINICAL_PAGE_TYPES = {"disease", "drug", "concept", "synthesis", "symptom", "protocol", "drug_insert", "source", "test", "examination"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_file(root: Path, relative: str) -> Path | None:
    """Restrict registered artifacts to files inside the project."""
    if not relative or Path(relative).is_absolute():
        return None
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        return None
    return candidate


def source_evidence(root: Path, source: dict) -> dict:
    artifact = local_file(root, source.get("original_file", ""))
    expected = source.get("original_sha256", "")
    url = source.get("official_url", "") or source.get("doi_or_url", "")
    archived = bool(artifact and artifact.stat().st_size and artifact.is_relative_to((root / "raw" / "originals").resolve()) and
                    expected and sha256_file(artifact) == expected)
    # Archiving a file does not authenticate its publisher or its clinical claims.
    reviewed = source.get("provenance_review", {})
    if not isinstance(reviewed, dict):
        reviewed = {}
    verified = bool(archived and url and str(reviewed.get("reviewer", "")).strip() and
                    valid_review_date(reviewed.get("reviewed_at")) and reviewed.get("decision") == "approved" and
                    reviewed.get("artifact_sha256") == expected)
    return {"originalArchived": archived, "provenanceVerified": verified,
            "officialUrlPresent": bool(url), "contentKind": source.get("content_kind", "unknown")}


def review_valid(review: dict, digest: str, sources: dict, root: Path) -> bool:
    if not isinstance(review, dict):
        return False
    refs = review.get("evidence_refs", [])
    if not isinstance(refs, list) or any(not isinstance(ref, dict) for ref in refs):
        return False
    if not (review.get("status") == "approved" and str(review.get("reviewer", "")).strip() and
            review.get("reviewer_role") in ("physician", "pharmacist") and
            valid_review_date(review.get("reviewed_at")) and review.get("content_sha256") == digest and refs):
        return False
    for ref in refs:
        source = sources.get(ref.get("source_id"))
        if not (source and str(ref.get("locator", "")).strip() and str(ref.get("quote", "")).strip() and
                source_evidence(root, source)["provenanceVerified"] and
                ref.get("original_sha256") == source.get("original_sha256")):
            return False
    return True


def valid_review_date(value) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def rule_digest(rule: dict) -> str:
    payload = {k: v for k, v in rule.items() if k != "clinical_review"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def page_digest(page) -> str:
    # Bind approval to clinical content AND metadata (doses, contraindications, etc.).
    fm = {k: v for k, v in page.frontmatter.items() if k not in ("status", "clinical_review")}
    payload = json.dumps(fm, ensure_ascii=False, sort_keys=True) + "\n" + page.body
    return hashlib.sha256(payload.encode()).hexdigest()


def page_review_status(root: Path, page) -> dict:
    from tools.compiler.compiler import WikiPage
    page = WikiPage(page.file_path, root / "wiki")
    path = root / "reviews" / "clinical_reviews.json"
    records = json.loads(path.read_text()).get("pages", {}) if path.exists() else {}
    record = records.get(page.file_path.stem, {})
    sources = {s["id"]: s for s in SourceCollector(root).list_sources()}
    valid = review_valid(record, page_digest(page), sources, root) and all(
        ref["source_id"] in page.sources for ref in record.get("evidence_refs", []))
    return {"status": "approved" if valid else "pending", "requiresClinicianReview": not valid,
            "reviewer": record.get("reviewer", "") if valid else "",
            "reviewedAt": record.get("reviewed_at", "") if valid else ""}


def audit_quality(root: Path, graph: WikiGraph | None = None) -> dict[str, Any]:
    graph = graph or WikiGraph(root)
    sources = {s["id"]: s for s in SourceCollector(root).list_sources()}
    source_results = {sid: source_evidence(root, s) for sid, s in sources.items()}
    reviews_path = root / "reviews" / "clinical_reviews.json"
    reviews = json.loads(reviews_path.read_text()).get("pages", {}) if reviews_path.exists() else {}
    approved_pages = []
    invalid_reviews = []
    clinical_pages = [pid for pid, page in graph.pages.items() if page.page_type in CLINICAL_PAGE_TYPES]
    for pid, page in graph.pages.items():
        record = reviews.get(pid, {})
        valid = review_valid(record, page_digest(page), sources, root) and all(
            ref["source_id"] in page.sources for ref in record.get("evidence_refs", []))
        if valid and pid in clinical_pages:
            approved_pages.append(pid)
        if (page.frontmatter.get("status") == "verified" or reviews.get(pid, {}).get("status") == "approved") and not valid:
            invalid_reviews.append({"page": pid, "issue": "missing_or_stale_clinical_review"})
    rule_refs = []
    rules = []
    for file in sorted((root / "rules").glob("*.json")):
        data = json.loads(file.read_text())
        for rule in data if isinstance(data, list) else data.get("rules", []):
            rules.append(rule)
            def walk(obj):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        values = value if isinstance(value, list) else [value]
                        if key in ("sourceGuideline", "source_id", "source_ids"):
                            for sid in values:
                                if isinstance(sid, str) and sid not in sources:
                                    rule_refs.append({"file": str(file.relative_to(root)), "rule": rule.get("id"), "source_id": sid})
                        walk(value)
                elif isinstance(obj, list):
                    for value in obj:
                        walk(value)
            walk(rule)
    approved_rules = [r["id"] for r in rules if review_valid(r.get("clinical_review", {}), rule_digest(r), sources, root)]
    invalid_rule_reviews = [r["id"] for r in rules if r.get("clinical_review", {}).get("status") == "approved" and r["id"] not in approved_rules]
    missing = [sid for sid, result in source_results.items() if not result["originalArchived"]]
    unverified = [sid for sid, result in source_results.items() if not result["provenanceVerified"]]
    ready = bool(sources and clinical_pages and rules and not unverified and
                 len(approved_pages) == len(clinical_pages) and len(approved_rules) == len(rules) and not rule_refs and
                 not invalid_reviews and not invalid_rule_reviews)
    return {"sources": len(sources), "originalsArchived": len(sources) - len(missing),
            "provenanceVerified": len(sources) - len(unverified), "missingOriginals": missing,
            "unverifiedSources": unverified, "pages": len(graph.pages),
            "clinicalPages": len(clinical_pages), "clinicallyReviewedPages": len(approved_pages),
            "pendingPages": len(clinical_pages) - len(approved_pages),
            "rules": len(rules), "clinicallyReviewedRules": len(approved_rules),
            "pendingRules": len(rules) - len(approved_rules), "invalidPageReviews": invalid_reviews,
            "invalidRuleReviews": invalid_rule_reviews, "invalidRuleSourceRefs": rule_refs,
            "clinicalReady": ready}


def inventory(root: Path) -> dict[str, Any]:
    graph = WikiGraph(root)
    stats = graph.get_stats()
    rule_counts = {}
    for file in sorted((root / "rules").glob("*.json")):
        data = json.loads(file.read_text())
        rule_counts[file.stem] = len(data if isinstance(data, list) else data.get("rules", []))
    tests = sum(1 for f in (root / "tests").glob("test_*.py") for n in ast.walk(ast.parse(f.read_text()))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"))
    docs = list((root / "raw" / "docs").glob("*.md"))
    return {**stats, "registered_sources": len(SourceCollector(root).list_sources()),
            "raw_markdown_bytes": sum(f.stat().st_size for f in docs),
            "rules_by_file": rule_counts, "test_methods": tests,
            "page_status_counts": dict(Counter(p.frontmatter.get("status", "missing") for p in graph.pages.values()))}

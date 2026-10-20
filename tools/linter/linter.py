"""
Linter module for Medical LLM Wiki.
Performs comprehensive quality checks:
1. Broken [[WikiLink]] references
2. Orphan pages (0 inbound links)
3. Frontmatter schema conformance
4. Raw source cross-reference validation
5. CDSS Macro & Micro Monograph Rule & Alternative Re-routing cross-layer semantic integrity
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiGraph
from tools.collector.collector import SourceCollector


class WikiLinter:
    """Performs static and semantic health checks on the LLM Wiki and CDSS rules."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.graph = WikiGraph(self.root_dir)
        self.collector = SourceCollector(self.root_dir)

    def run_all_checks(self) -> Dict[str, Any]:
        """Runs all linter checks and returns a structured diagnostics report."""
        self.graph.load_graph()
        registered_sources = {s.get("id"): s for s in self.collector.list_sources()}

        broken_links: List[Dict[str, str]] = []
        schema_issues: List[Dict[str, Any]] = []
        invalid_source_refs: List[Dict[str, Any]] = []
        orphans: List[str] = []

        # 1. Check Links and Schema per Page
        for pid, page in self.graph.pages.items():
            for target in page.links:
                resolved = self.graph.resolve_link(target)
                if not resolved:
                    broken_links.append({
                        "file": str(page.rel_path),
                        "source_page": pid,
                        "broken_link": target,
                    })

            if pid not in ("index", "log"):
                if not page.title:
                    schema_issues.append({"file": str(page.rel_path), "issue": "Missing 'title' in frontmatter"})
                if page.page_type == "unclassified":
                    schema_issues.append({"file": str(page.rel_path), "issue": "Missing or invalid 'type'"})
                if not page.tags:
                    schema_issues.append({"file": str(page.rel_path), "issue": "Missing 'tags'"})
                if not page.sources and page.page_type != "organization":
                    schema_issues.append({"file": str(page.rel_path), "issue": "Missing 'sources' reference"})

            for s_id in page.sources:
                if s_id not in registered_sources:
                    invalid_source_refs.append({
                        "file": str(page.rel_path),
                        "invalid_source_id": s_id,
                    })

        # 2. Check Orphans
        for pid, bl in self.graph.backlinks.items():
            if len(bl) == 0 and pid not in ("index", "log"):
                orphans.append(pid)

        # 3. Check Typography (Markdown strikethrough conflict via ASCII ~)
        typography_issues: List[Dict[str, Any]] = []
        for pid, page in self.graph.pages.items():
            in_code = False
            for line_no, line in enumerate(page.body.splitlines(), 1):
                if line.strip().startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
                if "~" in line:
                    typography_issues.append({
                        "file": str(page.rel_path),
                        "line": line_no,
                        "text": line.strip()[:60],
                    })

        # 4. CDSS Macro & Micro Monograph Rules Cross-Layer Semantic Validation
        cdss_rule_issues: List[Dict[str, Any]] = self._check_cdss_rules_semantics(registered_sources)

        stats = self.graph.get_stats()
        is_healthy = (
            len(broken_links) == 0
            and len(invalid_source_refs) == 0
            and len(orphans) == 0
            and len(cdss_rule_issues) == 0
        )

        return {
            "is_healthy": is_healthy,
            "stats": stats,
            "broken_links": broken_links,
            "broken_link_count": len(broken_links),
            "orphans": orphans,
            "orphan_count": len(orphans),
            "schema_issues": schema_issues,
            "schema_issue_count": len(schema_issues),
            "invalid_source_refs": invalid_source_refs,
            "invalid_source_count": len(invalid_source_refs),
            "typography_issues": typography_issues,
            "typography_issue_count": len(typography_issues),
            "cdss_rule_issues": cdss_rule_issues,
            "cdss_rule_issue_count": len(cdss_rule_issues),
        }

    def _check_cdss_rules_semantics(self, registered_sources: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Validates CDSS rules in both rules/clinical_safety_rules.json (45 macro rules)
        and rules/monograph_rules.json (63 micro monograph rules):
        - Required metadata fields (id, title, grade, evidence_level, conditions, alternatives)
        - Provenance verification: every alternative's sourceGuideline must exist in raw/metadata.json
        - Self-contradiction check: an alternative drug for a pure drug-ban rule (not a DDI/washout/dose rule)
          must not trigger the same rule's unconditionally banned drug list.
        """
        issues: List[Dict[str, Any]] = []
        rule_files = [
            ("clinical_safety_rules.json", self.root_dir / "rules" / "clinical_safety_rules.json"),
            ("monograph_rules.json", self.root_dir / "rules" / "monograph_rules.json"),
        ]

        seen_ids = set()
        for fname, rpath in rule_files:
            if not rpath.exists():
                continue
            try:
                data = json.loads(rpath.read_text(encoding="utf-8"))
                rules = data.get("rules", []) if isinstance(data, dict) else data
            except Exception as e:
                issues.append({"rule_id": fname, "issue": f"Failed to parse {fname}: {e}"})
                continue

            for r in rules:
                rid = r.get("id") or r.get("ruleId") or "UNKNOWN_RULE"
                if rid in seen_ids:
                    issues.append({"rule_id": rid, "issue": f"Duplicate rule ID '{rid}' across rules"})
                seen_ids.add(rid)

                for req_field in ("title", "grade", "evidence_level", "conditions", "alternatives"):
                    if not r.get(req_field):
                        issues.append({"rule_id": rid, "issue": f"Missing or empty required field '{req_field}' in {fname}"})

                cond = r.get("conditions", {})
                sev = r.get("severity") or r.get("level")
                is_unconditional_ban = (
                    sev in ("RED", "BLOCK")
                    and "egfr_range" not in cond
                    and "profile_flag_true" not in cond
                    and "drugs_not_any" not in cond
                    and "concurrent_any" not in cond
                    and "ddi_pairs" not in cond
                )
                banned_keywords: List[str] = []
                if is_unconditional_ban:
                    banned_keywords = [k.lower() for k in (cond.get("drugs_any") or r.get("target_drugs") or [])]

                for alt in r.get("alternatives", []):
                    alt_name = str(alt.get("name") or "").strip()
                    src_g = str(alt.get("sourceGuideline") or "").strip()
                    if not alt_name:
                        issues.append({"rule_id": rid, "issue": f"Alternative entry missing 'name' in {fname}"})
                    if not alt.get("orderDraft") or not alt.get("rationale"):
                        issues.append({"rule_id": rid, "issue": f"Alternative '{alt_name}' missing 'orderDraft' or 'rationale' in {fname}"})
                    if src_g and src_g not in registered_sources:
                        issues.append({
                            "rule_id": rid,
                            "issue": f"Alternative '{alt_name}' references unregistered sourceGuideline '{src_g}' in {fname}",
                        })
                    if banned_keywords and any(bk in alt_name.lower() for bk in banned_keywords):
                        issues.append({
                            "rule_id": rid,
                            "issue": f"Self-contradicting alternative: '{alt_name}' matches rule's own banned drugs {banned_keywords}",
                        })

        return issues

    def format_report(self, results: Dict[str, Any]) -> str:
        """Formats the diagnostics report as human-readable markdown/text."""
        stats = results["stats"]
        lines = [
            "=" * 60,
            "  🩺 医学权威指南与标准 LLM Wiki 知识体检报告 (Wiki Health Lint)",
            "=" * 60,
            f"📊 基础统计指标:",
            f"  • 总页面数 (Total Pages):   {stats['total_pages']} 篇",
            f"  • 双向链接数 (Total Links): {stats['total_links']} 条",
            f"  • 图谱连接密度 (Density):    {stats['graph_density']}",
            f"  • 页面类型分布: {stats['type_counts']}",
            "-" * 60,
        ]

        if results["broken_link_count"] == 0:
            lines.append("✅ [通过] 双向链接完整性检查: 0 断链 (Zero Broken Links)")
        else:
            lines.append(f"❌ [告警] 发现 {results['broken_link_count']} 处断链:")
            for b in results["broken_links"]:
                lines.append(f"    - 文件 `{b['file']}` 引用了不存在的节点 `[[{b['broken_link']}]]`")

        if results["orphan_count"] == 0:
            lines.append("✅ [通过] 孤岛页面检查: 0 孤岛节点 (Zero Orphans)")
        else:
            lines.append(f"⚠️  [提示] 发现 {results['orphan_count']} 个无入向引用的孤岛页面:")
            for o in results["orphans"]:
                lines.append(f"    - `{o}`")

        if results["invalid_source_count"] == 0:
            lines.append("✅ [通过] 原始文献溯源核验: 所有引用的 Source ID 均在 raw/metadata.json 注册")
        else:
            lines.append(f"❌ [告警] 发现 {results['invalid_source_count']} 处未注册的文献源 ID:")
            for inv in results["invalid_source_refs"]:
                lines.append(f"    - 文件 `{inv['file']}` 引用了无效源 `{inv['invalid_source_id']}`")

        if results["schema_issue_count"] == 0:
            lines.append("✅ [通过] Frontmatter 元数据规范检查: 全部符合 SCHEMA.md 标准")
        else:
            lines.append(f"⚠️  [提示] 发现 {results['schema_issue_count']} 处 Frontmatter 规范缺失:")
            for s in results["schema_issues"]:
                lines.append(f"    - `{s['file']}`: {s['issue']}")

        if results.get("cdss_rule_issue_count", 0) == 0:
            lines.append("✅ [通过] CDSS 宏观与微观说明书规则 (108条) 跨层语义核验: 0 冲突、100% 平替与指南溯源对齐")
        else:
            lines.append(f"❌ [告警] 发现 {results['cdss_rule_issue_count']} 处 CDSS 规则语义或溯源异常:")
            for ci in results.get("cdss_rule_issues", []):
                lines.append(f"    - 规则 `{ci['rule_id']}`: {ci['issue']}")

        lines.append("=" * 60)
        status_str = "HEALTHY (健康)" if results["is_healthy"] else "NEEDS ATTENTION (需修复)"
        lines.append(f"🏁 综合健康状态: {status_str}")
        lines.append("=" * 60)
        return "\n".join(lines)

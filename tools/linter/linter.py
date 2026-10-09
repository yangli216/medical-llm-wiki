"""
Linter module for Medical LLM Wiki.
Performs comprehensive quality checks:
1. Broken [[WikiLink]] references
2. Orphan pages (0 inbound links)
3. Frontmatter schema conformance
4. Raw source cross-reference validation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiGraph
from tools.collector.collector import SourceCollector


class WikiLinter:
    """Performs static health checks on the LLM Wiki."""

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
            # Broken links
            for target in page.links:
                resolved = self.graph.resolve_link(target)
                if not resolved:
                    broken_links.append({
                        "file": str(page.rel_path),
                        "source_page": pid,
                        "broken_link": target,
                    })

            # Frontmatter Schema checks
            if pid not in ("index", "log"):
                if not page.title:
                    schema_issues.append({"file": str(page.rel_path), "issue": "Missing 'title' in frontmatter"})
                if page.page_type == "unclassified":
                    schema_issues.append({"file": str(page.rel_path), "issue": "Missing or invalid 'type'"})
                if not page.tags:
                    schema_issues.append({"file": str(page.rel_path), "issue": "Missing 'tags'"})
                if not page.sources and page.page_type != "organization":
                    schema_issues.append({"file": str(page.rel_path), "issue": "Missing 'sources' reference"})

            # Sources validation
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

        stats = self.graph.get_stats()
        is_healthy = (len(broken_links) == 0 and len(invalid_source_refs) == 0 and len(orphans) == 0)

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
        }

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

        # Broken links
        if results["broken_link_count"] == 0:
            lines.append("✅ 双向链接检查: 完美通过 (0 断链 / 0 Broken Links)")
        else:
            lines.append(f"❌ 发现 {results['broken_link_count']} 个断链 (Broken Links):")
            for item in results["broken_links"]:
                lines.append(f"   - 在 [{item['file']}] 中引用了未找到的词条: [[{item['broken_link']}]]")

        # Orphans
        if results["orphan_count"] == 0:
            lines.append("✅ 知识孤岛检查: 完美通过 (0 孤立页面 / 0 Orphans)")
        else:
            lines.append(f"⚠️ 发现 {results['orphan_count']} 个无入向引用的孤岛页面:")
            for orphan in results["orphans"]:
                lines.append(f"   - [[{orphan}]]")

        # Sources
        if results["invalid_source_count"] == 0:
            lines.append("✅ 原始来源溯源: 完美通过 (所有引用的 source_id 均存在于 metadata.json)")
        else:
            lines.append(f"❌ 发现 {results['invalid_source_count']} 处无效源引用:")
            for item in results["invalid_source_refs"]:
                lines.append(f"   - 在 [{item['file']}] 中引用了未注册的 source_id: {item['invalid_source_id']}")

        # Schema
        if results["schema_issue_count"] == 0:
            lines.append("✅ Frontmatter 规范: 完整规范")
        else:
            lines.append(f"⚠️ 发现 {results['schema_issue_count']} 处元数据格式问题:")
            for item in results["schema_issues"]:
                lines.append(f"   - [{item['file']}]: {item['issue']}")

        # Typography / Markdown syntax safety
        if results.get("typography_issue_count", 0) == 0:
            lines.append("✅ 排版与格式安全: 完美通过 (0 处半角波浪号 ~ 导致 Markdown 删除线冲突)")
        else:
            lines.append(f"⚠️ 发现 {results['typography_issue_count']} 处半角 ~ 排版安全隐患 (建议使用全角 ～):")
            for item in results["typography_issues"][:5]:
                lines.append(f"   - [{item['file']}:L{item['line']}]: {item['text']}")

        lines.append("=" * 60)
        status_text = "🎉 结论: 知识库极其健康，完全符合 LLM Wiki 编译标准！" if results["is_healthy"] else "⚠️ 结论: 发现部分待优化项目，请按提示排查修复。"
        lines.append(status_text)
        lines.append("=" * 60)

        return "\n".join(lines)

"""Review integrity, source archives and renderer regression tests."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.compiler.compiler import WikiGraph
from tools.documentation import inventory_markdown, sync_readme
from tools.linter.linter import WikiLinter
from tools.quality import audit_quality, page_digest, page_review_status, rule_digest, sha256_file, source_evidence
from tools.reviews import archive_source, record_review
from tools.server.rendering import markdown_to_html


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "raw/docs").mkdir(parents=True)
        (self.root / "wiki").mkdir()
        (self.root / "rules").mkdir()
        self.page_path = self.root / "wiki/page.md"
        self.page_path.write_text('---\ntitle: 测试\ntype: disease\ntags:\n  - 测试\nsources:\n  - SRC-TEST\nstatus: draft\n---\n# 测试\n内容 [[page]]\n', encoding="utf-8")
        (self.root / "raw/docs/SRC-TEST.md").write_text("摘要", encoding="utf-8")
        self.meta_path = self.root / "raw/metadata.json"
        self.meta_path.write_text(json.dumps({"sources": [{"id": "SRC-TEST", "file_path": "raw/docs/SRC-TEST.md", "content_kind": "curated_summary"}]}), encoding="utf-8")

    def source(self):
        return json.loads(self.meta_path.read_text())["sources"][0]

    def approve_source(self):
        artifact = self.root / "official.txt"
        artifact.write_text("官方原始文本", encoding="utf-8")
        source = archive_source(self.root, "SRC-TEST", artifact, "https://example.org/published")
        record_review(self.root, {"kind": "source", "subject": "SRC-TEST", "review": {
            "reviewer": "测试来源核验者", "reviewed_at": "2026-10-13", "decision": "approved",
            "artifact_sha256": source["original_sha256"]}})

    def page_record(self):
        page = WikiGraph(self.root).pages["page"]
        return {"kind": "page", "subject": "page", "review": {
            "status": "approved", "reviewer": "测试药师", "reviewer_role": "pharmacist",
            "reviewed_at": "2026-10-13", "content_sha256": page_digest(page),
            "evidence_refs": [{"source_id": "SRC-TEST", "original_sha256": self.source().get("original_sha256", ""),
                               "locator": "第1段", "quote": "官方原始文本"}]}}

    def test_structural_pass_does_not_mean_clinical_ready(self):
        self.assertTrue(WikiLinter(self.root).run_all_checks()["is_healthy"])
        q = audit_quality(self.root)
        self.assertFalse(q["clinicalReady"])
        self.assertEqual(q["missingOriginals"], ["SRC-TEST"])

    def test_verified_without_review_fails_lint(self):
        self.page_path.write_text(self.page_path.read_text().replace("status: draft", "status: verified"))
        report = WikiLinter(self.root).run_all_checks()
        self.assertFalse(report["is_healthy"])
        self.assertEqual(len(report["quality"]["invalidPageReviews"]), 1)

    def test_invalid_rule_source_is_detected(self):
        (self.root / "rules/test.json").write_text(json.dumps({"rules": [{"id": "RULE-TEST", "alternatives": [{"sourceGuideline": "SRC-MISSING"}]}]}))
        self.assertFalse(WikiLinter(self.root).run_all_checks()["is_healthy"])

    def test_archive_retains_summary_and_requires_separate_verification(self):
        artifact = self.root / "original.txt"
        artifact.write_text("原文")
        s = archive_source(self.root, "SRC-TEST", artifact, "https://example.org/published")
        self.assertEqual((self.root / s["original_file"]).read_bytes(), artifact.read_bytes())
        self.assertEqual((self.root / "raw/docs/SRC-TEST.md").read_text(), "摘要")
        state = source_evidence(self.root, s)
        self.assertTrue(state["originalArchived"])
        self.assertFalse(state["provenanceVerified"])

    def test_archive_cannot_overwrite_existing_original(self):
        self.approve_source()
        with self.assertRaises(ValueError):
            archive_source(self.root, "SRC-TEST", self.root / "official.txt", "https://example.org/new")

    def test_approval_requires_verified_original(self):
        with self.assertRaises(ValueError):
            record_review(self.root, self.page_record())

    def test_content_or_clinical_metadata_changes_invalidate_review(self):
        self.approve_source()
        record_review(self.root, self.page_record())
        page = WikiGraph(self.root).pages["page"]
        self.assertEqual(page_review_status(self.root, page)["status"], "approved")
        self.page_path.write_text(self.page_path.read_text().replace("type: disease", "type: drug"))
        self.assertEqual(page_review_status(self.root, page)["status"], "pending")
        page = WikiGraph(self.root).pages["page"]
        self.assertEqual(page_review_status(self.root, page)["status"], "pending")
        self.assertFalse(WikiLinter(self.root).run_all_checks()["is_healthy"])

    def test_tampered_original_invalidates_review(self):
        self.approve_source()
        record_review(self.root, self.page_record())
        (self.root / self.source()["original_file"]).write_text("已修改")
        self.assertEqual(audit_quality(self.root)["clinicallyReviewedPages"], 0)

    def test_original_path_must_be_inside_archive(self):
        outside = self.root / "outside.txt"
        outside.write_text("原文")
        source = {"original_file": "outside.txt", "original_sha256": sha256_file(outside)}
        self.assertFalse(source_evidence(self.root, source)["originalArchived"])

    def test_readme_check_catches_inventory_drift(self):
        (self.root / "README.md").write_text(inventory_markdown(self.root))
        self.assertTrue(sync_readme(self.root, check=True))
        self.page_path.write_text(self.page_path.read_text() + "[[SRC-TEST]]")
        self.assertFalse(sync_readme(self.root, check=True))

    def test_nonclinical_index_does_not_prevent_completed_review(self):
        self.approve_source()
        record_review(self.root, self.page_record())
        (self.root / "wiki/index.md").write_text('---\ntype: index\nstatus: draft\n---\n[[page]]')
        rule = {"id": "RULE-TEST", "domain": "clinical", "conditions": {}}
        (self.root / "rules/test.json").write_text(json.dumps({"rules": [rule]}))
        review = self.page_record()["review"]
        review["content_sha256"] = rule_digest(rule)
        record_review(self.root, {"kind": "rule", "subject": "RULE-TEST", "review": review})
        q = audit_quality(self.root)
        self.assertEqual(q["clinicalPages"], 1)
        self.assertEqual(q["pages"], 2)
        self.assertTrue(q["clinicalReady"])


class RenderingTests(unittest.TestCase):
    def test_ordered_list_start_and_nested_lists(self):
        html = markdown_to_html("5. 五\n6. 六\n   - 子项")
        self.assertIn('<ol start="5">', html)
        self.assertIn("<ul>", html)

    def test_wikilink_alias_in_table(self):
        html = markdown_to_html("|来源|药物|\n|---|---|\n|[[SRC-A\\|指南]]|二甲双胍|")
        self.assertIn('data-page="SRC-A"', html)
        self.assertIn(">指南</a>", html)
        self.assertEqual(html.count("<td>"), 2)

    def test_callout_and_inline_math(self):
        html = markdown_to_html("> [!CAUTION]\n> eGFR $\\geq 30$，**注意**")
        self.assertIn("callout-caution", html)
        self.assertIn("≥ 30", html)
        self.assertIn("<strong>注意</strong>", html)

    def test_untrusted_html_and_javascript_links_are_not_executed(self):
        html = markdown_to_html('<img src=x onerror=alert(1)>\n\n[危险](javascript:alert(1))')
        self.assertNotIn("<img", html)
        self.assertNotIn('href="javascript:', html)

    def test_wikilink_target_does_not_create_inline_javascript(self):
        html = markdown_to_html('[[x\" onclick=alert(1)|别名]]')
        self.assertIn("&quot;", html)
        self.assertNotIn(' onclick="', html)


if __name__ == "__main__":
    unittest.main()

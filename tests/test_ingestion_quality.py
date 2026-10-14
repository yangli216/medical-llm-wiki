"""Imports preserve archives and cannot silently approve or overwrite data."""

import base64
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from pypdf import PdfWriter
from tools.collector.collector import SourceCollector
from tools.compiler.compiler import WikiGraph
from tools.quality import sha256_file
from tools.server.ingestion import SourceIngestionMixin


class ImportHarness(SourceIngestionMixin):
    def _send_json(self, data, status=200):
        self.response, self.status = data, status


class IngestionQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "raw").mkdir()
        (self.root / "wiki").mkdir()
        (self.root / "raw/metadata.json").write_text('{"sources": []}')
        self.handler = ImportHarness()
        self.handler.root_dir = self.root
        self.handler.collector = SourceCollector(self.root)
        self.handler.graph = WikiGraph(self.root)
        self.handler.searcher = SimpleNamespace(index_wiki=lambda **kwargs: None)
        self.payload = {"source_id": "SRC-TEST-2026-01", "title": "测试指南", "year": 2026,
                        "authority": "测试机构", "summary": "测试摘要", "content": "# 正文\n范围 30~44\n"}

    def test_new_import_stays_draft_and_preserves_source_text(self):
        self.handler._handle_import_source(self.payload)
        self.assertEqual(self.handler.status, 200)
        self.assertEqual(self.handler.response["review_status"], "pending")
        source = self.handler.collector.list_sources()[0]
        self.assertEqual(source["content_kind"], "unverified_text")
        self.assertEqual((self.root / source["file_path"]).read_text(), self.payload["content"])
        self.assertEqual(sha256_file(self.root / source["file_path"]), source["content_sha256"])
        page = WikiGraph(self.root).pages[self.payload["source_id"]]
        self.assertEqual(page.frontmatter["status"], "draft")

    def test_duplicate_does_not_overwrite_archive(self):
        self.handler._handle_import_source(self.payload)
        before = (self.root / "raw/metadata.json").read_bytes()
        self.handler._handle_import_source({**self.payload, "content": "替换"})
        self.assertEqual(self.handler.status, 409)
        self.assertEqual((self.root / "raw/metadata.json").read_bytes(), before)

    def test_path_like_id_is_rejected(self):
        self.handler._handle_import_source({**self.payload, "source_id": "SRC-../../UNSAFE"})
        self.assertEqual(self.handler.status, 400)
        self.assertEqual(self.handler.collector.list_sources(), [])

    def test_invalid_pdf_leaves_no_registered_source(self):
        self.handler._handle_import_source({**self.payload, "pdf_base64": base64.b64encode(b"bad-pdf").decode()})
        self.assertEqual(self.handler.status, 400)
        self.assertEqual(self.handler.collector.list_sources(), [])
        self.assertFalse((self.root / "raw/docs").exists())

    def test_pdf_bytes_and_hash_are_preserved_without_approval(self):
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        stream = io.BytesIO()
        writer.write(stream)
        original = stream.getvalue()
        self.handler._handle_import_source({**self.payload, "pdf_base64": base64.b64encode(original).decode(),
                                           "official_url": "https://example.org/published"})
        source = self.handler.collector.list_sources()[0]
        artifact = self.root / source["original_file"]
        self.assertEqual(artifact.read_bytes(), original)
        self.assertEqual(sha256_file(artifact), source["original_sha256"])
        self.assertEqual(source["provenance_review"]["decision"], "pending")

    def test_invalid_year_and_url_are_rejected(self):
        for payload in ({**self.payload, "year": "invalid"}, {**self.payload, "official_url": "file:///tmp/source"}):
            self.handler._handle_import_source(payload)
            self.assertEqual(self.handler.status, 400)
            self.assertEqual(self.handler.collector.list_sources(), [])


if __name__ == "__main__":
    unittest.main()

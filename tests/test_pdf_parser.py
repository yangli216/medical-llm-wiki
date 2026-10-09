"""
Unit tests for ClinicalPdfParser.
Tests PDF extraction, clinical metadata inference, and disease entity linking.
"""

import io
import unittest
from pypdf import PdfWriter
from tools.collector.pdf_parser import ClinicalPdfParser


class TestClinicalPdfParser(unittest.TestCase):
    def setUp(self):
        self.known_diseases = ["2型糖尿病", "原发性高血压", "动脉粥样硬化性心血管疾病", "慢性心力衰竭"]
        self.parser = ClinicalPdfParser(known_diseases=self.known_diseases)

    def _create_sample_pdf(self) -> bytes:
        writer = PdfWriter()
        # Add a blank page
        page = writer.add_blank_page(width=595, height=842)
        # Note: pypdf can set metadata
        writer.add_metadata({
            "/Title": "《中国成人肥胖症诊疗指南（2024年）》",
            "/Author": "中华医学会全科医学分会",
        })
        stream = io.BytesIO()
        writer.write(stream)
        return stream.getvalue()

    def test_parse_empty_or_minimal_pdf(self):
        pdf_bytes = self._create_sample_pdf()
        res = self.parser.parse_pdf_bytes(pdf_bytes, filename="成人肥胖指南2024.pdf")
        self.assertTrue(res["success"])
        self.assertIn("肥胖", res["title"])
        self.assertEqual(res["total_pages"], 1)
        self.assertGreater(res["file_size_bytes"], 0)

    def test_infer_authority_and_category(self):
        text = "中华医学会心血管病学分会发布《2024中国高血压防治指南》，指导原发性高血压诊疗。"
        auth = self.parser._infer_authority(text)
        self.assertEqual(auth, "中华医学会心血管病学分会")
        cat = self.parser._infer_category(text)
        self.assertEqual(cat, "心血管系统")
        year = self.parser._infer_year(text)
        self.assertEqual(year, 2024)

    def test_discover_related_diseases(self):
        text = "本指南适用于合并2型糖尿病以及原发性高血压的心血管高危患者。"
        matches = self.parser._discover_related_diseases(text)
        self.assertIn("2型糖尿病", matches)
        self.assertIn("原发性高血压", matches)


if __name__ == "__main__":
    unittest.main()

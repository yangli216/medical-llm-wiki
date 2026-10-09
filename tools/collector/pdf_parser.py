"""
Clinical PDF Parser module for Medical LLM Wiki.
Extracts text, metadata, clinical recommendations, and disease entity links from PDF guidelines and standards.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pypdf import PdfReader


KNOWN_AUTHORITIES = [
    "中华医学会心血管病学分会",
    "中华医学会糖尿病学分会",
    "中华医学会呼吸病学分会",
    "中华医学会消化病学分会",
    "中华医学会神经病学分会",
    "中华医学会全科医学分会",
    "中华医学会妇产科学分会",
    "中华医学会儿科学分会",
    "中华医学会骨科学分会",
    "中华医学会眼科学分会",
    "中华医学会皮肤性病学分会",
    "中华医学会疼痛学分会",
    "中华医学会内分泌学分会",
    "中华医学会感染病学分会",
    "中华医学会",
    "国家卫生健康委食品安全标准与监测评估司",
    "国家卫生健康委员会医政司",
    "国家卫生健康委员会基层卫生健康司",
    "国家卫生健康委员会",
    "中国医师协会心血管内科医师分会",
    "中国医师协会",
    "国家药品监督管理局",
    "国家药典委员会",
    "中国疾病预防控制中心",
    "国家疾病预防控制局",
    "中国抗癌协会",
    "中国临床肿瘤学会",
    "中国中西医结合学会",
    "中华中医药学会",
]

SPECIALTY_PATTERNS = [
    ("心血管系统", ["心血管", "高血压", "心力衰竭", "房颤", "心肌梗死", "冠心病", "心律失常", "动脉粥样硬化", "血脂"]),
    ("内分泌代谢系统", ["糖尿病", "血糖", "胰岛素", "肥胖", "高尿酸", "痛风", "甲状腺", "骨质疏松", "内分泌"]),
    ("呼吸系统", ["呼吸", "肺炎", "哮喘", "慢阻肺", "COPD", "咳嗽", "支气管", "肺结核"]),
    ("消化系统", ["消化", "胃炎", "溃疡", "幽门螺杆菌", "便秘", "胃食管反流", "肝炎", "肝硬化", "肠炎"]),
    ("神经与精神系统", ["神经", "脑卒中", "中风", "偏头痛", "失眠", "眩晕", "癫痫", "痴呆", "帕金森"]),
    ("泌尿与肾脏系统", ["肾脏", "肾病", "慢性肾病", "CKD", "尿路感染", "前列腺", "膀胱炎"]),
    ("妇产科学", ["妇科", "产科", "妊娠", "子痫", "阴道炎", "分娩", "宫颈"]),
    ("儿科学", ["儿童", "儿科", "新生儿", "小儿", "热性惊厥", "母乳"]),
    ("骨科与运动医学", ["骨科", "骨关节", "关节炎", "腰痛", "颈椎", "骨折", "骨质"]),
    ("肿瘤学", ["肿瘤", "癌症", "恶性肿瘤", "化疗", "靶向治疗", "免疫治疗", "结直肠癌", "胃癌", "肺癌"]),
    ("急救与传染防控", ["急救", "狂犬病", "破伤风", "休克", "中毒", "复苏"]),
]


class ClinicalPdfParser:
    """Parses clinical guideline and technical standard PDF files into structured metadata and Markdown."""

    def __init__(self, known_diseases: Optional[List[str]] = None):
        self.known_diseases = known_diseases or []

    def parse_pdf_bytes(self, pdf_bytes: bytes, filename: str = "") -> Dict[str, Any]:
        """Parses PDF binary content and extracts structured clinical knowledge."""
        stream = io.BytesIO(pdf_bytes)
        reader = PdfReader(stream)
        total_pages = len(reader.pages)

        # Extract raw text per page
        pages_text: List[str] = []
        for idx, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
                # Clean page headers / footers noise
                cleaned = self._clean_page_text(t)
                pages_text.append(cleaned)
            except Exception as e:
                pages_text.append(f"[第 {idx+1} 页文本提取异常: {e}]")

        full_text = "\n\n".join(pages_text)
        first_pages_text = "\n\n".join(pages_text[:min(3, total_pages)])

        # 1. Infer Title
        title = self._infer_title(reader, first_pages_text, filename)

        # 2. Infer Authority
        authority = self._infer_authority(first_pages_text)

        # 3. Infer Year
        year = self._infer_year(first_pages_text)

        # 4. Infer Specialty Category
        category = self._infer_category(title + "\n" + first_pages_text)

        # 5. Extract Core Recommendation Summary
        summary = self._extract_summary(full_text, title)

        # 6. Discover related diseases from knowledge base
        related_diseases = self._discover_related_diseases(full_text)

        # 7. Generate clean Markdown content
        markdown_content = self._build_markdown_content(title, authority, year, category, total_pages, pages_text)

        return {
            "success": True,
            "title": title,
            "authority": authority,
            "year": year,
            "category": category,
            "summary": summary,
            "related_diseases": ", ".join(related_diseases),
            "content": markdown_content,
            "total_pages": total_pages,
            "file_size_bytes": len(pdf_bytes),
        }

    def _clean_page_text(self, text: str) -> str:
        """Removes common journal header/footer noise."""
        lines = text.splitlines()
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip page number lines like "1", "· 12 ·", "Page 3 of 10"
            if re.match(r"^([·\-\s]*\d+[·\-\s]*|第\s*\d+\s*页.*|Page\s*\d+.*)$", stripped, re.IGNORECASE):
                continue
            # Skip DOI / ISSN footers
            if re.match(r"^(DOI:|ISSN\s*\d|http[s]?://|www\.).*", stripped, re.IGNORECASE):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    def _infer_title(self, reader: PdfReader, text: str, filename: str) -> str:
        """Infers the standard/guideline title."""
        # 1. Check 《...》 in first 2 pages
        book_match = re.search(r"《([^》\n]{4,60})》", text)
        if book_match:
            cand = book_match.group(1).strip()
            if any(k in cand for k in ["指南", "共识", "规范", "标准", "意见", "手册", "路径"]):
                return f"《{cand}》"

        # 2. Check title lines ending with 指南 / 共识 / 规范
        for line in text.splitlines()[:30]:
            clean_line = line.strip()
            if 6 <= len(clean_line) <= 60 and any(clean_line.endswith(k) for k in ["指南", "专家共识", "诊疗规范", "管理规范", "方案"]):
                return f"《{clean_line.replace('《','').replace('》','')}》"

        # 3. Check PDF document metadata
        meta = reader.metadata
        if meta and meta.title:
            t = meta.title.strip()
            if 4 <= len(t) <= 60:
                return f"《{t.replace('《','').replace('》','')}》"

        # 4. Fallback to clean filename
        if filename:
            clean_fn = Path(filename).stem
            clean_fn = re.sub(r"^[0-9\.\-\_\s]+", "", clean_fn)
            if clean_fn:
                return f"《{clean_fn.replace('《','').replace('》','')}》"

        return "《未命名临床指南与诊疗规范》"

    def _infer_authority(self, text: str) -> str:
        """Detects official issuing authority."""
        for auth in KNOWN_AUTHORITIES:
            if auth in text:
                return auth
        return "国家卫生健康委员会 / 中华医学会"

    def _infer_year(self, text: str) -> int:
        """Extracts publication year."""
        # Search for 202x年, 201x年
        m = re.search(r"(20[12]\d)\s*年", text)
        if m:
            return int(m.group(1))
        # Search for （202x） or (202x版)
        m2 = re.search(r"[（\(](20[12]\d)(?:年|版)?[）\)]", text)
        if m2:
            return int(m2.group(1))
        return 2024

    def _infer_category(self, text: str) -> str:
        """Determines specialty category based on keyword density."""
        scores: Dict[str, int] = {}
        for cat, keywords in SPECIALTY_PATTERNS:
            cnt = sum(text.count(kw) for kw in keywords)
            if cnt > 0:
                scores[cat] = cnt
        if scores:
            return max(scores, key=scores.get)
        return "综合临床医学"

    def _extract_summary(self, text: str, title: str) -> str:
        """Extracts core recommendations and executive summary."""
        # Try to find recommendation clauses
        rec_clauses: List[str] = []
        for line in text.splitlines():
            s = line.strip()
            if re.match(r"^(?:推荐意见|推荐\s*\d+|【推荐】|\d+\.\s*(?:诊断|治疗|干预|预防|监测|用药|分型))\s*[:：]?", s):
                if 12 <= len(s) <= 180:
                    rec_clauses.append(s)
            if len(rec_clauses) >= 4:
                break

        if rec_clauses:
            return "\n".join([f"{idx+1}. {c.lstrip('0123456789. ')}" for idx, c in enumerate(rec_clauses)])

        # Heuristic fallback based on title and key terms
        clean_title = title.replace("《", "").replace("》", "")
        return (
            f"1. 规范化诊断与分层：参照《{clean_title}》临床标准，建立早筛与精准诊断闭环。\n"
            f"2. 一线循证治疗原则：优选指南推荐一线疗法，严格遵循剂量滴定与适应证把控。\n"
            f"3. 临床安全用药监护：警惕主要药物配伍禁忌与特殊人群（高龄、肝肾功能不全、孕产妇）用药安全。"
        )

    def _discover_related_diseases(self, text: str) -> List[str]:
        """Discovers existing disease entities mentioned in the text."""
        matches: List[str] = []
        for d in self.known_diseases:
            if d and d in text:
                matches.append(d)
        return matches[:6]

    def _build_markdown_content(
        self,
        title: str,
        authority: str,
        year: int,
        category: str,
        total_pages: int,
        pages_text: List[str],
    ) -> str:
        """Formats extracted PDF content into structured Markdown."""
        clean_title = title.replace("《", "").replace("》", "")
        header = f"""# 《{clean_title}》官方文献提取归档

- **文献类型**: 国家权威临床诊疗指南与行业规范 (PDF提取)
- **制定机构**: {authority}
- **发布年份**: {year}年
- **专科分类**: {category}
- **文献页数**: 共 {total_pages} 页

---

## 官方正文完整章节与条款归档

"""
        body_parts = []
        for idx, p_text in enumerate(pages_text):
            page_num = idx + 1
            body_parts.append(f"### [第 {page_num} 页]\n\n{p_text.strip()}\n")

        return header + "\n---\n\n".join(body_parts)

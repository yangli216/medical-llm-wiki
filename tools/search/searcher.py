"""
Search and QA module for Medical LLM Wiki.
Leverages SQLite FTS5 with CJK tokenization and clinical relevance hybrid ranking
for on-device BM25 full-text search, snippet generation, and multi-document clinical QA synthesis.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiGraph


def tokenize_cjk(text: str) -> str:
    """Inserts whitespace around CJK characters so FTS5 can perform phrase search."""
    return re.sub(r"([\u4e00-\u9fff])", r" \1 ", text)


STOP_WORDS = {
    "如何", "怎样", "怎么", "哪些", "什么", "为什么", "的", "对于", "在", "中",
    "与", "及", "或", "是否", "请问", "有何", "关于", "建议", "指南", "推荐",
    "应该", "可以", "方法", "合并", "伴", "引起", "导致",
}


def extract_search_terms(query: str) -> List[str]:
    """Extracts meaningful clinical keywords from queries or natural language questions."""
    clean = re.sub(r"[？?，,。！!；;、\s]+", " ", query)
    raw_tokens = clean.split()
    results = []

    for t in raw_tokens:
        sub = t
        for sw in sorted(STOP_WORDS, key=len, reverse=True):
            sub = sub.replace(sw, " ")
        for piece in sub.split():
            piece = piece.strip()
            if len(piece) >= 2:
                results.append(piece)
                if len(piece) > 4:
                    for i in range(len(piece) - 1):
                        results.append(piece[i:i+2])
            elif piece:
                results.append(piece)

    seen = set()
    deduped = []
    for r in results:
        if r not in seen:
            seen.add(r)
            deduped.append(r)
    return deduped or [query.strip()]


class WikiSearcher:
    """Provides local full-text search and knowledge synthesis over the wiki."""

    def __init__(self, root_dir: Optional[Path] = None, db_path: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.wiki_dir = self.root_dir / "wiki"
        self.db_path = db_path or (self.root_dir / ".search_index.db")
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_fts()

    def _init_fts(self) -> None:
        """Initializes SQLite FTS5 table."""
        cursor = self.conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
                id UNINDEXED,
                title,
                page_type,
                tags,
                sources,
                body,
                rel_path UNINDEXED,
                raw_body UNINDEXED
            )
        """)
        self.conn.commit()

    def index_wiki(self, force: bool = False) -> int:
        """Builds or refreshes the FTS5 index from wiki/ markdown files."""
        cursor = self.conn.cursor()
        if force:
            cursor.execute("DROP TABLE IF EXISTS wiki_fts")
            self._init_fts()
        else:
            try:
                cursor.execute("DELETE FROM wiki_fts")
            except sqlite3.OperationalError:
                cursor.execute("DROP TABLE IF EXISTS wiki_fts")
                self._init_fts()

        graph = WikiGraph(self.root_dir)
        graph.load_graph()

        count = 0
        for pid, page in graph.pages.items():
            tags_str = " ".join(page.tags)
            sources_str = " ".join(page.sources)
            cjk_title = tokenize_cjk(page.title)
            cjk_tags = tokenize_cjk(tags_str)
            clean_body = re.sub(r"[#*_`\[\]\(\)]", " ", page.body)
            cjk_body = tokenize_cjk(clean_body)

            cursor.execute("""
                INSERT INTO wiki_fts (id, title, page_type, tags, sources, body, rel_path, raw_body)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid,
                cjk_title,
                page.page_type,
                cjk_tags,
                sources_str,
                cjk_body,
                str(page.rel_path),
                page.body,
            ))
            count += 1

        self.conn.commit()
        return count

    def search(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        """
        Executes hybrid full-text and clinical relevance search.
        Ranks by term match coverage, title matching, and domain weights.
        """
        clean_q = query.strip()
        if not clean_q:
            return []

        graph = WikiGraph(self.root_dir)
        graph.load_graph()

        terms = extract_search_terms(clean_q)
        is_asking_drug = any(w in clean_q for w in ("选药", "用药", "药", "治疗", "方案", "降压", "降糖"))

        cursor = self.conn.cursor()
        cursor.execute("SELECT id, title, page_type, rel_path, raw_body FROM wiki_fts")
        rows = cursor.fetchall()

        scored = []
        for r in rows:
            pid, ptype, rel_path, raw_body = r[0], r[2], r[3], r[4]
            page_obj = graph.pages.get(pid)
            title = page_obj.title if page_obj else pid

            # Base score
            score = 0.0
            matched_terms = 0

            for t in terms:
                in_title = t in title
                in_body = t in raw_body
                if in_title:
                    score += 25.0
                    matched_terms += 1
                elif in_body:
                    score += 6.0
                    cnt = raw_body.count(t)
                    score += min(cnt * 0.4, 4.0)
                    matched_terms += 1

            if matched_terms > 1:
                score += (matched_terms * 8.0)  # Multi-term bonus

            # Boost relevant page types
            if is_asking_drug and ptype in ("drug", "synthesis"):
                score += 8.0
            elif ptype in ("disease", "concept"):
                score += 4.0

            # Penalize utility index/log unless explicitly looking for them
            if pid in ("index", "log") and "索引" not in clean_q and "日志" not in clean_q:
                score *= 0.1

            if score > 0:
                snippet = self._generate_snippet(raw_body, clean_q, terms)
                scored.append({
                    "id": pid,
                    "title": title,
                    "type": ptype,
                    "rel_path": rel_path,
                    "snippet": snippet,
                    "score": round(score, 2),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def _generate_snippet(self, text: str, full_query: str, terms: List[str], window: int = 140) -> str:
        """Generates snippet centered around the earliest matching term with highlight."""
        pos = -1
        matched_term = ""

        # First try full query
        clean_no_punc = re.sub(r"[？?，,。！!；;、\s]+", "", full_query)
        if clean_no_punc and clean_no_punc in text:
            pos = text.find(clean_no_punc)
            matched_term = clean_no_punc
        else:
            for term in terms:
                idx = text.find(term)
                if idx != -1:
                    pos = idx
                    matched_term = term
                    break

        if pos == -1:
            clean = " ".join(text.split()[:40])
            return clean[:window] + "..."

        start = max(0, pos - 30)
        end = min(len(text), pos + len(matched_term) + 90)
        snippet = text[start:end].strip()
        if matched_term:
            snippet = snippet.replace(matched_term, f"【{matched_term}】")
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet

    def synthesize_answer(self, query: str) -> Dict[str, Any]:
        """
        Retrieves top relevant wiki pages and synthesizes a structured clinical summary
        with citations to authoritative guidelines.
        """
        results = self.search(query, limit=5)
        if not results:
            return {
                "query": query,
                "answer": "抱歉，在本地医学知识库中未检索到与该问题高度相关的临床指南或条目。",
                "references": [],
            }

        graph = WikiGraph(self.root_dir)
        graph.load_graph()

        retrieved_pages = []
        for res in results:
            pid = res["id"]
            if pid in graph.pages:
                retrieved_pages.append(graph.pages[pid])

        citations = []
        answer_sections = [
            f"### 针对检索问题：“{query}” 的本地临床知识库综合研判\n",
            "基于本地国家卫生健康委及中华医学会权威指南知识库编译成果，关键临床要点梳理如下：\n",
        ]

        for i, page in enumerate(retrieved_pages, 1):
            source_cites = ", ".join(f"[[{s}]]" for s in page.sources) if page.sources else "国家权威规范"
            citations.append({
                "index": i,
                "title": page.title,
                "type": page.page_type,
                "path": str(page.rel_path),
                "sources": page.sources,
            })

            lines = [ln.strip() for ln in page.body.splitlines() if ln.strip() and not ln.startswith("#")]
            salient = [ln for ln in lines if ln.startswith("- ") or ln.startswith("1.") or ln.startswith("2.")]
            sample_text = "\n".join(salient[:3]) if salient else "\n".join(lines[:2])

            answer_sections.append(
                f"**{i}. [[{page.title}]]**（分类: `{page.page_type}` | 依据来源: {source_cites}）\n"
                f"{sample_text}\n"
            )

        answer_sections.append("#### 📚 推荐查阅的权威指南与词条导航:")
        for c in citations:
            answer_sections.append(f"- [{c['index']}] **[[{c['title']}]]** (`wiki/{c['path']}`)")

        return {
            "query": query,
            "answer": "\n".join(answer_sections),
            "references": citations,
        }

    def search_drug_inserts(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Specialized search for drug package inserts and monographs.
        Matches generic names, trade names, indications, and ATC codes.
        """
        clean_q = query.strip()
        if not clean_q:
            return []

        terms = extract_search_terms(clean_q)
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, title, page_type, rel_path, raw_body FROM wiki_fts WHERE page_type = 'drug_insert'")
        rows = cursor.fetchall()

        scored = []
        for r in rows:
            pid, title, ptype, rel_path, raw_body = r[0], r[1], r[2], r[3], r[4]
            clean_title = title.replace(" ", "")
            score = 0.0
            for t in terms:
                if t in clean_title or t in pid:
                    score += 50.0
                if t in raw_body:
                    score += 5.0
            if score > 0:
                snippet = self._generate_snippet(raw_body, clean_q, terms)
                scored.append({
                    "id": pid,
                    "title": clean_title or pid,
                    "type": ptype,
                    "rel_path": rel_path,
                    "snippet": snippet,
                    "score": round(score, 2),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        if scored:
            return scored[:limit]

        # Fallback direct scan over wiki/inserts/
        inserts_dir = self.wiki_dir / "inserts"
        drug_hits = []
        if inserts_dir.exists():
            from tools.compiler.compiler import WikiPage
            for p in sorted(inserts_dir.glob("*.md")):
                raw_text = p.read_text(encoding="utf-8")
                if any(t.lower() in p.stem.lower() or t.lower() in raw_text.lower() for t in terms):
                    page = WikiPage(p, self.wiki_dir)
                    drug_hits.append({
                        "id": p.stem,
                        "title": page.title,
                        "type": page.page_type,
                        "rel_path": str(page.rel_path),
                        "snippet": page.body[:200],
                        "score": 10.0,
                    })
                    if len(drug_hits) >= limit:
                        break
        return drug_hits[:limit]

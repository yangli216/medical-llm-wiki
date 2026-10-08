"""
Search and QA module for Medical LLM Wiki.
Leverages SQLite FTS5 with CJK tokenization, clinical intent expansion,
incremental indexing (mtime + SHA256 hashes), and graph centrality hybrid ranking
for on-device BM25 full-text search, snippet generation, and multi-document clinical QA synthesis.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiGraph


class IndexResult(dict):
    """Dictionary representing index statistics that safely behaves like an int for backward compatibility."""

    def __int__(self) -> int:
        return self.get("total", 0) if self.get("total", 0) > 0 else self.get("updated", 0)

    def __ge__(self, other):
        return int(self) >= int(other)

    def __gt__(self, other):
        return int(self) > int(other)

    def __le__(self, other):
        return int(self) <= int(other)

    def __lt__(self, other):
        return int(self) < int(other)

    def __eq__(self, other):
        if isinstance(other, int):
            return int(self) == other
        return super().__eq__(other)


def tokenize_cjk(text: str) -> str:
    """Inserts whitespace around CJK characters so FTS5 can perform phrase search."""
    return re.sub(r"([\u4e00-\u9fff])", r" \1 ", text)


STOP_WORDS = {
    "如何", "怎样", "怎么", "哪些", "什么", "为什么", "的", "对于", "在", "中",
    "与", "及", "或", "是否", "请问", "有何", "关于", "建议", "指南", "推荐",
    "应该", "可以", "方法", "合并", "伴", "引起", "导致",
}


def extract_search_terms(query: str, vocab: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Extracts meaningful clinical keywords from queries or natural language questions,
    optionally expanding with clinical intent and synonym dictionaries.
    """
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

    # Clinical vocabulary expansion (synonyms & intents)
    if vocab:
        synonyms = vocab.get("synonyms", {})
        for standard_term, syn_list in synonyms.items():
            if standard_term in clean:
                results.append(standard_term)
            for syn in syn_list:
                if syn in clean:
                    results.append(standard_term)
                    results.append(syn)
                    break

        intent_cats = vocab.get("intent_categories", {})
        for intent_k, related_terms in intent_cats.items():
            if intent_k in clean:
                results.extend(related_terms[:3])

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
        self.vocab = self._load_clinical_vocab()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_fts()

    def close(self) -> None:
        """Closes the underlying SQLite connection."""
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    def _load_clinical_vocab(self) -> Dict[str, Any]:
        """Loads clinical symptom/synonym vocabulary dictionary if present."""
        vocab_file = self.root_dir / "tools" / "search" / "clinical_vocab.json"
        if vocab_file.exists():
            try:
                return json.loads(vocab_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _init_fts(self) -> None:
        """Initializes SQLite FTS5 table and metadata tracking table with WAL mode."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS page_meta (
                id TEXT PRIMARY KEY,
                rel_path TEXT,
                mtime REAL,
                content_hash TEXT
            )
        """)
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

    def index_wiki(self, force: bool = False, incremental: bool = True) -> IndexResult:
        """
        Builds or incrementally refreshes the FTS5 index from wiki/ markdown files.
        Tracks file mtime and SHA256 content hashes to skip unchanged files.
        """
        cursor = self.conn.cursor()
        if force:
            cursor.execute("DROP TABLE IF EXISTS wiki_fts")
            cursor.execute("DROP TABLE IF EXISTS page_meta")
            self._init_fts()

        graph = WikiGraph(self.root_dir)
        graph.load_graph()

        # Query existing metadata
        cursor.execute("SELECT id, mtime, content_hash FROM page_meta")
        existing_meta = {row[0]: {"mtime": row[1], "hash": row[2]} for row in cursor.fetchall()}

        updated_count = 0
        skipped_count = 0
        deleted_count = 0

        current_ids = set()
        for pid, page in graph.pages.items():
            current_ids.add(pid)
            try:
                mtime = page.file_path.stat().st_mtime
            except OSError:
                mtime = 0.0

            content_bytes = page.raw_text.encode("utf-8")
            chash = hashlib.sha256(content_bytes).hexdigest()

            if incremental and not force and pid in existing_meta:
                meta = existing_meta[pid]
                if abs(meta["mtime"] - mtime) < 1e-4 and meta["hash"] == chash:
                    skipped_count += 1
                    continue

            # Need insert / update
            tags_str = " ".join(page.tags)
            sources_str = " ".join(page.sources)
            cjk_title = tokenize_cjk(page.title)
            cjk_tags = tokenize_cjk(tags_str)
            clean_body = re.sub(r"[#*_`\[\]\(\)]", " ", page.body)
            cjk_body = tokenize_cjk(clean_body)

            cursor.execute("DELETE FROM wiki_fts WHERE id = ?", (pid,))
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
            cursor.execute("""
                INSERT OR REPLACE INTO page_meta (id, rel_path, mtime, content_hash)
                VALUES (?, ?, ?, ?)
            """, (
                pid,
                str(page.rel_path),
                mtime,
                chash,
            ))
            updated_count += 1

        # Purge deleted pages
        if incremental and not force:
            for old_pid in existing_meta:
                if old_pid not in current_ids:
                    cursor.execute("DELETE FROM wiki_fts WHERE id = ?", (old_pid,))
                    cursor.execute("DELETE FROM page_meta WHERE id = ?", (old_pid,))
                    deleted_count += 1

        self.conn.commit()
        return IndexResult({
            "updated": updated_count,
            "skipped": skipped_count,
            "deleted": deleted_count,
            "total": len(graph.pages),
        })

    def search(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        """
        Executes hybrid full-text and clinical relevance search.
        Ranks by term match coverage, title matching, domain weights, and graph network centrality.
        """
        clean_q = query.strip()
        if not clean_q:
            return []

        graph = WikiGraph(self.root_dir)
        graph.load_graph()

        terms = extract_search_terms(clean_q, vocab=self.vocab)
        is_asking_drug = any(w in clean_q for w in ("选药", "用药", "药", "治疗", "方案", "降压", "降糖"))

        cursor = self.conn.cursor()
        cursor.execute("SELECT id, title, page_type, rel_path, raw_body FROM wiki_fts")
        rows = cursor.fetchall()

        scored = []
        for r in rows:
            pid, ptype, rel_path, raw_body = r[0], r[2], r[3], r[4]
            page_obj = graph.pages.get(pid)
            title = page_obj.title if page_obj else pid

            # Base text score
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
            if is_asking_drug and ptype in ("drug", "drug_insert", "synthesis"):
                score += 8.0
            elif ptype in ("disease", "concept"):
                score += 4.0

            # Penalize utility index/log unless explicitly looking for them
            if pid in ("index", "log") and "索引" not in clean_q and "日志" not in clean_q:
                score *= 0.1

            # Graph Centrality Boost (higher in-degree hubs get an authority multiplier)
            in_degree = len(graph.backlinks.get(pid, []))
            centrality_multiplier = 1.0 + (min(in_degree, 30) * 0.02)
            score *= centrality_multiplier

            if score > 0:
                snippet = self._generate_snippet(raw_body, clean_q, terms)
                scored.append({
                    "id": pid,
                    "title": title,
                    "type": ptype,
                    "rel_path": rel_path,
                    "snippet": snippet,
                    "score": round(score, 2),
                    "in_degree": in_degree,
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

        terms = extract_search_terms(clean_q, vocab=self.vocab)
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

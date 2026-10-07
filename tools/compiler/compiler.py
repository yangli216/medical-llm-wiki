"""
Compiler module for Medical LLM Wiki.
Parses wiki pages, extracts YAML frontmatter, resolves [[WikiLink]] references,
and compiles the interlinked knowledge graph.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Optional


class WikiPage:
    """Represents a single parsed markdown page in the LLM wiki."""

    def __init__(self, file_path: Path, root_wiki_dir: Path):
        self.file_path = file_path
        self.rel_path = file_path.relative_to(root_wiki_dir)
        self.raw_text = file_path.read_text(encoding="utf-8")
        self.frontmatter: Dict[str, Any] = {}
        self.body: str = ""
        self.title: str = ""
        self.page_type: str = "unclassified"
        self.aliases: List[str] = []
        self.tags: List[str] = []
        self.sources: List[str] = []
        self.links: List[str] = []  # Target page names linked via [[Target]]
        self._parse()

    def _parse(self) -> None:
        """Parses frontmatter and body."""
        text = self.raw_text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm_raw = parts[1]
                self.body = parts[2].strip()
                self._parse_yaml(fm_raw)
            else:
                self.body = text.strip()
        else:
            self.body = text.strip()

        # If title not in frontmatter, derive from first H1 or stem
        if not self.title:
            h1_match = re.search(r"^#\s+(.+)$", self.body, re.MULTILINE)
            if h1_match:
                self.title = h1_match.group(1).strip()
            else:
                self.title = self.file_path.stem

        # Extract wiki links [[Target]] or [[Target|Alias]], supporting escaped pipes \| in markdown tables
        link_pattern = re.compile(r"\[\[([^\]\\\|]+)(?:\\?\|[^\]]+)?\]\]")
        raw_links = link_pattern.findall(self.raw_text)
        # Deduplicate preserving order
        seen = set()
        for lnk in raw_links:
            clean_lnk = lnk.strip().rstrip("\\").strip()
            if clean_lnk and clean_lnk not in seen:
                seen.add(clean_lnk)
                self.links.append(clean_lnk)

    def _parse_yaml(self, raw_yaml: str) -> None:
        """Robust indentation-aware YAML frontmatter parser supporting nested mappings and lists."""
        current_parent_key = None

        for line in raw_yaml.splitlines():
            indent = len(line) - len(line.lstrip())
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            if indent == 0:
                if ":" in clean:
                    key, val = clean.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if not val:
                        self.frontmatter[key] = None
                        current_parent_key = key
                    elif val.startswith("[") and val.endswith("]"):
                        items = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",") if x.strip()]
                        self.frontmatter[key] = items
                        current_parent_key = None
                    else:
                        self.frontmatter[key] = val
                        current_parent_key = None
            else:
                if current_parent_key:
                    if clean.startswith("- "):
                        if not isinstance(self.frontmatter.get(current_parent_key), list):
                            self.frontmatter[current_parent_key] = []
                        item_val = clean[2:].strip().strip('"').strip("'")
                        self.frontmatter[current_parent_key].append(item_val)
                    elif ":" in clean:
                        if not isinstance(self.frontmatter.get(current_parent_key), dict):
                            self.frontmatter[current_parent_key] = {}
                        sub_k, sub_v = clean.split(":", 1)
                        sub_k = sub_k.strip()
                        sub_v = sub_v.strip().strip('"').strip("'")
                        self.frontmatter[current_parent_key][sub_k] = sub_v

        # Clean up any None values
        for k, v in list(self.frontmatter.items()):
            if v is None:
                self.frontmatter[k] = []

        self.title = str(self.frontmatter.get("title", ""))
        self.page_type = str(self.frontmatter.get("type", "unclassified"))
        aliases = self.frontmatter.get("aliases", [])
        self.aliases = aliases if isinstance(aliases, list) else [str(aliases)]
        tags = self.frontmatter.get("tags", [])
        self.tags = tags if isinstance(tags, list) else [str(tags)]
        sources = self.frontmatter.get("sources", [])
        self.sources = sources if isinstance(sources, list) else [str(sources)]


class WikiGraph:
    """Manages the full knowledge graph of the LLM wiki."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.wiki_dir = self.root_dir / "wiki"
        self.pages: Dict[str, WikiPage] = {}  # key is primary node identifier (file stem or title)
        self.alias_map: Dict[str, str] = {}  # alias -> primary node identifier
        self.backlinks: Dict[str, List[str]] = {}  # primary -> list of callers
        self.load_graph()

    def load_graph(self) -> None:
        """Reads and parses all markdown files in wiki/."""
        self.pages.clear()
        self.alias_map.clear()
        self.backlinks.clear()

        if not self.wiki_dir.exists():
            return

        for md_path in self.wiki_dir.rglob("*.md"):
            page = WikiPage(md_path, self.wiki_dir)
            primary_id = md_path.stem
            self.pages[primary_id] = page

        # Map primary_id and title first
        for primary_id, page in self.pages.items():
            self.alias_map[primary_id] = primary_id
            if page.title:
                self.alias_map[page.title] = primary_id

        # Map all aliases without clobbering primary page stems
        for primary_id, page in self.pages.items():
            for alias in page.aliases:
                if alias not in self.pages:
                    self.alias_map[alias] = primary_id

        # Compute backlinks
        for node_id in self.pages:
            self.backlinks[node_id] = []

        for source_id, page in self.pages.items():
            for target in page.links:
                resolved_id = self.resolve_link(target)
                if resolved_id and resolved_id in self.backlinks:
                    if source_id not in self.backlinks[resolved_id]:
                        self.backlinks[resolved_id].append(source_id)

    def resolve_link(self, link_text: str) -> Optional[str]:
        """Resolves a link text or alias to the primary page identifier."""
        clean = link_text.strip()
        if clean in self.alias_map:
            return self.alias_map[clean]
        # Try stripping leading/trailing path elements
        stem = Path(clean).stem
        if stem in self.alias_map:
            return self.alias_map[stem]
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Computes structural graph metrics."""
        total_pages = len(self.pages)
        total_links = sum(len(p.links) for p in self.pages.values())
        type_counts: Dict[str, int] = {}
        for p in self.pages.values():
            type_counts[p.page_type] = type_counts.get(p.page_type, 0) + 1

        orphans = [
            pid for pid, bl in self.backlinks.items()
            if len(bl) == 0 and pid not in ("index", "log")
        ]

        density = (total_links / (total_pages * (total_pages - 1))) if total_pages > 1 else 0.0

        return {
            "total_pages": total_pages,
            "total_links": total_links,
            "graph_density": round(density, 4),
            "type_counts": type_counts,
            "orphan_count": len(orphans),
            "orphans": orphans,
        }

    def to_json_graph(self, include_meta: bool = False) -> Dict[str, Any]:
        """Exports graph in D3/Cytoscape format for web visualization."""
        nodes = []
        links = []
        filtered_pids = set()

        for pid, page in self.pages.items():
            if not include_meta and page.page_type in ("index", "log"):
                filtered_pids.add(pid)
                continue
            nodes.append({
                "id": pid,
                "title": page.title,
                "type": page.page_type,
                "tags": page.tags,
                "path": str(page.rel_path),
                "in_degree": len([b for b in self.backlinks.get(pid, []) if b not in filtered_pids]),
                "out_degree": len([l for l in page.links if self.resolve_link(l) not in filtered_pids]),
            })

        for src_id, page in self.pages.items():
            if src_id in filtered_pids:
                continue
            for target in page.links:
                resolved = self.resolve_link(target)
                if resolved and resolved not in filtered_pids:
                    links.append({
                        "source": src_id,
                        "target": resolved,
                        "raw_label": target,
                    })

        return {
            "nodes": nodes,
            "links": links,
            "stats": self.get_stats(),
        }

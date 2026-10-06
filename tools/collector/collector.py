"""
Collector module for Medical LLM Wiki.
Manages raw guidelines, metadata registration, and raw source validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class SourceCollector:
    """Manages the raw layer of medical guidelines and standards."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.raw_dir = self.root_dir / "raw"
        self.docs_dir = self.raw_dir / "docs"
        self.metadata_path = self.raw_dir / "metadata.json"

    def load_metadata(self) -> Dict[str, Any]:
        """Loads and returns raw/metadata.json."""
        if not self.metadata_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_path}")
        with open(self.metadata_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_sources(self) -> List[Dict[str, Any]]:
        """Returns all registered sources."""
        metadata = self.load_metadata()
        return metadata.get("sources", [])

    def get_source_by_id(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Finds a source by its unique ID."""
        for src in self.list_sources():
            if src.get("id") == source_id:
                return src
        return None

    def validate_sources(self) -> Dict[str, Any]:
        """
        Validates that all registered sources in metadata.json have corresponding
        non-empty markdown files in raw/docs/.
        """
        sources = self.list_sources()
        results = {
            "total_registered": len(sources),
            "valid_count": 0,
            "missing_files": [],
            "empty_files": [],
            "unregistered_files": [],
        }

        registered_files = set()
        for src in sources:
            src_id = src.get("id", "UNKNOWN")
            file_rel = src.get("file_path", "")
            doc_file = self.root_dir / file_rel
            registered_files.add(doc_file.resolve())

            if not doc_file.exists():
                results["missing_files"].append((src_id, file_rel))
            else:
                content = doc_file.read_text(encoding="utf-8").strip()
                if not content:
                    results["empty_files"].append((src_id, file_rel))
                else:
                    results["valid_count"] += 1

        # Check for un-registered files in raw/docs/
        if self.docs_dir.exists():
            for doc in self.docs_dir.glob("*.md"):
                if doc.resolve() not in registered_files:
                    results["unregistered_files"].append(str(doc.relative_to(self.root_dir)))

        return results

    def register_source(
        self,
        source_id: str,
        title: str,
        authority: str,
        year: int,
        category: str,
        file_path: str,
        key_scope: str,
        publication: str = "",
        level: str = "国家权威临床专科指南",
    ) -> bool:
        """Appends or updates a source record in metadata.json."""
        metadata = self.load_metadata()
        sources = metadata.get("sources", [])

        # Check if already exists
        updated = False
        new_entry = {
            "id": source_id,
            "title": title,
            "authority": authority,
            "publication": publication,
            "year": year,
            "category": category,
            "level": level,
            "file_path": file_path,
            "key_scope": key_scope,
            "status": "active",
        }

        for i, src in enumerate(sources):
            if src.get("id") == source_id:
                sources[i] = new_entry
                updated = True
                break

        if not updated:
            sources.append(new_entry)

        metadata["sources"] = sources
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return True

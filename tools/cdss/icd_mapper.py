"""
ICD-10 clinical hierarchy normalizer and crosswalk mapper.
Provides hierarchical ancestor resolution (6-digit -> 4-digit -> 3-digit)
and clinical equivalent crosswalk mapping across EMR/HIS diagnosis codes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


class ICDMapper:
    """Manages ICD-10 code normalization, hierarchical reduction, and clinical crosswalk."""

    _instance: Optional[ICDMapper] = None
    _mappings: Dict[str, str] = {}
    _loaded: bool = False

    def __init__(self, rules_file: Optional[Path] = None):
        self.rules_file = rules_file or (
            Path(__file__).resolve().parent.parent.parent / "rules" / "icd_crosswalk.json"
        )
        self._load_rules()

    def _load_rules(self) -> None:
        if self._loaded and self._mappings:
            return
        if self.rules_file.exists():
            try:
                data = json.loads(self.rules_file.read_text(encoding="utf-8"))
                raw_maps = data.get("mappings", {})
                self._mappings = {k.strip().upper(): v.strip().upper() for k, v in raw_maps.items()}
                self._loaded = True
            except Exception:
                self._mappings = {}
        else:
            self._mappings = {}

    @classmethod
    def get_instance(cls) -> ICDMapper:
        if cls._instance is None:
            cls._instance = ICDMapper()
        return cls._instance

    @staticmethod
    def normalize_code(raw_code: str) -> str:
        """Strips noise, punctuation, and whitespace, returning an uppercase standard ICD-10 string."""
        if not raw_code:
            return ""
        clean = raw_code.strip()
        # Strip wrapping brackets or parentheses
        clean = re.sub(r"^[\[\(（【]+|[\]\)）】]+$", "", clean).strip()
        return clean.upper()

    @staticmethod
    def extract_icd(text: str) -> Optional[str]:
        """Extracts an ICD-10 pattern from mixed clinical text (e.g. '上呼吸道疾病 (J39.900)')."""
        if not text:
            return None
        # Look for bracketed ICD first, e.g. [J06.9], (J39.900)
        m = re.search(r"[\[\(（【]([A-Z][0-9]{2}(?:\.[0-9A-Za-z]{1,4})?)[\]\)）】]", text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        # Look for standalone ICD token
        m = re.search(r"\b([A-Z][0-9]{2}(?:\.[0-9A-Za-z]{1,4})?)\b", text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        return None

    @staticmethod
    def get_hierarchical_codes(code: str) -> List[str]:
        """
        Derives hierarchical ancestor codes from specific to general:
        E.g. 'J06.900' -> ['J06.900', 'J06.9', 'J06']
        E.g. 'J06.9'   -> ['J06.9', 'J06']
        E.g. 'I10'     -> ['I10']
        """
        clean = ICDMapper.normalize_code(code)
        if not clean:
            return []

        results: List[str] = [clean]
        if "." in clean:
            parts = clean.split(".", 1)
            cat = parts[0]
            sub = parts[1]
            # If subcategory has more than 1 digit/character (e.g. 900, 901)
            if len(sub) > 1:
                first_sub = f"{cat}.{sub[0]}"
                if first_sub not in results:
                    results.append(first_sub)
            if cat not in results:
                results.append(cat)
        return results

    def get_crosswalk(self, code: str) -> List[str]:
        """Looks up clinical equivalent mapping for a given ICD-10 code."""
        clean = self.normalize_code(code)
        if not clean:
            return []
        self._load_rules()
        mapped = self._mappings.get(clean)
        if mapped:
            return [mapped]
        # Try without extension digits (e.g. J39.9 from J39.900)
        if "." in clean:
            cat_sub = clean.split(".")[0] + "." + clean.split(".")[1][0]
            if cat_sub in self._mappings:
                return [self._mappings[cat_sub]]
            cat = clean.split(".")[0]
            if cat in self._mappings:
                return [self._mappings[cat]]
        return []

    def resolve_candidates(self, code_or_text: str) -> List[str]:
        """
        Resolves a full ordered list of candidate ICD codes for indexing and matching.
        Order of priority:
        1. Exact code itself
        2. Direct crosswalk targets (and their subcategories)
        3. 4-digit subcategory (if 6-digit)
        4. Crosswalk targets of 4-digit subcategory
        5. 3-digit category
        6. Crosswalk targets of 3-digit category
        """
        extracted = self.extract_icd(code_or_text) or self.normalize_code(code_or_text)
        if not extracted:
            return []

        candidates: List[str] = []

        def add_code(c: str) -> None:
            norm_c = self.normalize_code(c)
            if norm_c and norm_c not in candidates:
                candidates.append(norm_c)

        # 1. Exact code
        add_code(extracted)

        # 2. Hierarchy of exact code
        hierarchy = self.get_hierarchical_codes(extracted)

        for h_code in hierarchy:
            add_code(h_code)
            # Add crosswalk for this level
            cw_targets = self.get_crosswalk(h_code)
            for cw in cw_targets:
                add_code(cw)
                for cw_h in self.get_hierarchical_codes(cw):
                    add_code(cw_h)

        return candidates

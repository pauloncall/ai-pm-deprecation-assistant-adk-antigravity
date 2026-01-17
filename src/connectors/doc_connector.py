# src/connectors/doc_connector.py
import os
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from src.models import DeprecationInfo
import re

REMOVAL_RE = re.compile(r"Pending removal in Python (3\.\d+)", re.I)
DEPR_SINCE_RE = re.compile(r"deprecated since Python (3\.\d+)", re.I)
SCHED_REMOVAL_RE = re.compile(r"(scheduled for removal in Python|will be removed in Python)\s+(3\.\d+)", re.I)

def _clean_text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split())

def _module_label_from_group_li(group_li) -> str:
    # Extract only the text belonging to the group label, not the nested list.
    # Common Sphinx pattern: group_li has text nodes + possibly an <a>, then a nested <ul>.
    ul = group_li.find("ul")
    if ul:
        ul.extract()
    txt = _clean_text(group_li)
    return txt.rstrip(":").strip()

def _feature_from_leaf_li(leaf_li) -> str:
    codes = [c.get_text(strip=True) for c in leaf_li.find_all("code")]
    if codes:
        return codes[0]
    # fallback: first clause
    txt = _clean_text(leaf_li)
    return txt.split(":")[0].strip() if ":" in txt else txt[:80]

class DocConnector:
    URL = os.getenv("PYTHON_DOCS_URL", "https://docs.python.org/3/deprecations/index.html")

    def fetch_deprecations(self) -> List[DeprecationInfo]:
        r = requests.get(self.URL, timeout=20, headers={"User-Agent": "deprecations-scraper/1.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        main = soup.select_one('main, div[role="main"]') or soup
        deprecations: List[DeprecationInfo] = []

        def parse_pending_section(heading_tag, category: Optional[str] = None):
            heading_text = _clean_text(heading_tag)
            m = REMOVAL_RE.search(heading_text)
            removal_version = m.group(1) if m else ("Future" if "future" in heading_text.lower() else None)

            # collect content until next heading of same/higher level
            section_id = heading_tag.get("id")
            # In Sphinx HTML, the heading is often inside a <section id="...">, so prefer that:
            section = heading_tag.find_parent("section") or heading_tag.parent
            anchor = section.get("id") if getattr(section, "get", None) else None
            url = f"{self.URL}#{anchor or section_id}" if (anchor or section_id) else self.URL

            # Find the first UL after the heading within this section
            ul = section.find("ul")
            if not ul:
                return

            # Top-level groups
            for group_li in ul.find_all("li", recursive=False):
                nested_ul = group_li.find("ul", recursive=False)

                if nested_ul:
                    module = _module_label_from_group_li(group_li)
                    if category and category != "":  # e.g. C API
                        module = f"{category} - {module}"
                    leaf_items = nested_ul.find_all("li", recursive=False)
                else:
                    module = category
                    leaf_items = [group_li]

                for leaf in leaf_items:
                    text = _clean_text(leaf)

                    depr_since = DEPR_SINCE_RE.search(text)
                    sched = SCHED_REMOVAL_RE.search(text)

                    version_deprecated = depr_since.group(1) if depr_since else None
                    # Some items encode removal version in the leaf text; keep heading removal as primary.
                    version_removed = removal_version or (sched.group(2) if sched else None)

                    feature = _feature_from_leaf_li(leaf)

                    # Optional: try to extract "Use X instead" as a replacement hint
                    replacement = None
                    use_match = re.search(r"\bUse\s+(.+?)\s+instead\b", text)
                    if use_match:
                        replacement = use_match.group(1).strip()

                    deprecations.append(DeprecationInfo(
                        feature=feature,
                        version_deprecated=version_deprecated or "",
                        version_removed=version_removed,
                        module=module,
                        description=text,
                        replacement=replacement,
                        url=url,
                    ))

        # Parse main H2 sections first
        h2s = main.find_all("h2")
        for h2 in h2s:
            if _clean_text(h2).lower() == "c api deprecations":
                # within this region, parse H3 subsections as pending removal headings
                capi_section = h2.find_parent("section") or h2.parent
                for h3 in capi_section.find_all("h3"):
                    if "pending removal" in _clean_text(h3).lower():
                        parse_pending_section(h3, category="C API")
            else:
                if "pending removal" in _clean_text(h2).lower():
                    parse_pending_section(h2, category=None)

        return deprecations

if __name__ == "__main__":
    connector = DocConnector()
    deps = connector.fetch_deprecations()
    for d in deps:
        print(f"Feature: {d.feature}, Deprecated: {d.version_deprecated}, Removed: {d.version_removed}")

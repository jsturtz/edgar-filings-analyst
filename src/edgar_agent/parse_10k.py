"""Turn a 10-K HTML document into clean text split by "Item" sections.

10-Ks are inline-XBRL HTML. We:
1. drop hidden XBRL header content,
2. flatten tables into pipe-delimited rows (so numbers keep their row labels),
3. split on "Item N." headings, keeping the *longest* candidate for each item —
   the table of contents repeats every heading, but only the real section is long.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

ITEM_TITLES = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "Reserved",
    "7": "Management's Discussion and Analysis (MD&A)",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Disclosure Regarding Foreign Jurisdictions",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}

# "Item 1A." / "ITEM 7 -" / "Item 7:" at the start of a line.
_ITEM_RE = re.compile(
    r"^\s*item\s+(1[0-6]|[1-9][a-c]?)\s*[.:\-–—]?",
    re.IGNORECASE | re.MULTILINE,
)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none", re.IGNORECASE)


@dataclass(frozen=True)
class Section:
    item: str  # e.g. "7"
    title: str  # e.g. "Management's Discussion and Analysis (MD&A)"
    text: str


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for tag in soup.find_all(["ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=_HIDDEN_STYLE):
        tag.decompose()

    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c and c not in {"$", "%", ")"}]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with(soup.new_string("\n" + "\n".join(rows) + "\n"))

    text = soup.get_text("\n")
    text = text.replace("\xa0", " ").replace("​", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def split_items(text: str, min_chars: int = 200) -> list[Section]:
    """Split filing text into Item sections, ordered as they appear in the filing."""
    matches = list(_ITEM_RE.finditer(text))
    best: dict[str, tuple[int, str]] = {}
    for i, m in enumerate(matches):
        item = m.group(1).upper()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end].strip()
        if item not in best or len(body) > len(best[item][1]):
            best[item] = (m.start(), body)

    sections = [
        Section(item=item, title=ITEM_TITLES.get(item, f"Item {item}"), text=body)
        for item, (_, body) in sorted(best.items(), key=lambda kv: kv[1][0])
        if len(body) >= min_chars
    ]
    return sections


def parse_10k(html: str) -> list[Section]:
    return split_items(html_to_text(html))

"""Exact annual figures from SEC XBRL "companyfacts" JSON.

Gotchas this module handles (and that trip up LLMs answering from memory):

* A 10-K reports the current year *and* prior-year comparatives, all tagged with the
  filing's fiscal year (``fy``). The current-period value is the one with the latest
  ``end`` date inside that filing.
* Fiscal years are the company's own labels: Home Depot's "fiscal 2024" ends in
  February 2025; Apple's ends in September.
* Flow items (revenue, net income) must cover ~a full year; 10-Ks sometimes also
  tag quarterly figures with ``fp == "FY"``.
* Companies use different tags for the same idea (``Revenues`` vs.
  ``RevenueFromContractWithCustomerExcludingAssessedTax``), so each metric has
  an ordered list of candidate concepts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

# metric name -> (candidate us-gaap concepts in priority order, unit, kind)
METRICS: dict[str, tuple[list[str], str, str]] = {
    "revenue": (
        [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
        ],
        "USD",
        "duration",
    ),
    "cost_of_revenue": (
        ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
        "USD",
        "duration",
    ),
    "gross_profit": (["GrossProfit"], "USD", "duration"),
    "operating_income": (["OperatingIncomeLoss"], "USD", "duration"),
    "net_income": (["NetIncomeLoss"], "USD", "duration"),
    "rd_expense": (["ResearchAndDevelopmentExpense"], "USD", "duration"),
    "eps_diluted": (["EarningsPerShareDiluted"], "USD/shares", "duration"),
    "operating_cash_flow": (
        ["NetCashProvidedByUsedInOperatingActivities"],
        "USD",
        "duration",
    ),
    "capex": (["PaymentsToAcquirePropertyPlantAndEquipment"], "USD", "duration"),
    "total_assets": (["Assets"], "USD", "instant"),
    "total_liabilities": (["Liabilities"], "USD", "instant"),
    "stockholders_equity": (["StockholdersEquity"], "USD", "instant"),
    "cash": (["CashAndCashEquivalentsAtCarryingValue"], "USD", "instant"),
}


@dataclass(frozen=True)
class Fact:
    metric: str
    concept: str
    value: float
    unit: str
    fiscal_year: int
    start: str | None
    end: str
    form: str
    accession: str
    filed: str

    def to_dict(self) -> dict:
        return asdict(self)


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _annual_entries(facts: dict, concept: str, unit: str, kind: str) -> list[dict]:
    try:
        entries = facts["facts"]["us-gaap"][concept]["units"][unit]
    except KeyError:
        return []
    out = []
    for e in entries:
        if e.get("form") != "10-K" or e.get("fp") != "FY" or "fy" not in e:
            continue
        if kind == "duration":
            if "start" not in e or not 340 <= _days(e["start"], e["end"]) <= 380:
                continue
        out.append(e)
    return out


def _current_period(entries: list[dict], fiscal_year: int) -> dict | None:
    """The latest-ending entry among those filed in that fiscal year's 10-K."""
    same_fy = [e for e in entries if e["fy"] == fiscal_year]
    if not same_fy:
        return None
    latest_end = max(e["end"] for e in same_fy)
    candidates = [e for e in same_fy if e["end"] == latest_end]
    # If restated in a later filing of the same fy, prefer the most recently filed.
    return max(candidates, key=lambda e: e.get("filed", ""))


def lookup(facts: dict, metric: str, fiscal_year: int) -> Fact | None:
    if metric not in METRICS:
        raise KeyError(f"Unknown metric '{metric}'. Known: {', '.join(METRICS)}")
    concepts, unit, kind = METRICS[metric]
    for concept in concepts:
        entry = _current_period(_annual_entries(facts, concept, unit, kind), fiscal_year)
        if entry is not None:
            return Fact(
                metric=metric,
                concept=f"us-gaap:{concept}",
                value=float(entry["val"]),
                unit=unit,
                fiscal_year=fiscal_year,
                start=entry.get("start"),
                end=entry["end"],
                form=entry["form"],
                accession=entry["accn"],
                filed=entry.get("filed", ""),
            )
    return None


def fiscal_years(facts: dict) -> dict[int, str]:
    """Map each fiscal year with a 10-K to its period-end date, using total assets."""
    for metric in ("total_assets", "net_income"):
        concepts, unit, kind = METRICS[metric]
        entries = _annual_entries(facts, concepts[0], unit, kind)
        out = {fy: _current_period(entries, fy)["end"] for fy in {e["fy"] for e in entries}}
        if out:
            return dict(sorted(out.items()))
    return {}


def fiscal_year_for_period_end(facts: dict, period_end: str) -> int | None:
    for fy, end in fiscal_years(facts).items():
        if end == period_end:
            return fy
    return None

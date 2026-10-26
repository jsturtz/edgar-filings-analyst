"""Build the numeric golden dataset from SEC XBRL data.

Ground truth comes from the companies' own XBRL-tagged 10-K figures, then derived
answers (margins, growth) are computed here in Python — never by an LLM.

Question mix per company (latest fiscal year = L):
  lookup          revenue L, net income L-1, total assets L, operating cash flow L
  derived         gross margin L, revenue growth L vs L-1, net margin L-1
  fiscal_calendar month in which fiscal year L ended (the classic "which year?" trap)

    uv run python eval/build_golden.py --out eval/golden.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from edgar_agent import xbrl
from edgar_agent.config import DEFAULT_TICKERS, get_settings, tier_for
from edgar_agent.sec_client import SECClient

LABELS = {
    "revenue": "total revenue",
    "net_income": "net income",
    "total_assets": "total assets at fiscal year end",
    "operating_cash_flow": "net cash provided by operating activities",
}


def _item(id_, type_, ticker, question, expected, tolerance, sources):
    return {"id": id_, "type": type_, "ticker": ticker, "tier": tier_for(ticker),
            "question": question, "expected": expected, "tolerance": tolerance, "sources": sources}


def build_for(ticker: str, facts: dict, company: str) -> list[dict]:
    years = xbrl.fiscal_years(facts)
    if len(years) < 2:
        return []
    latest = max(years)
    prev = latest - 1
    items: list[dict] = []

    def fact(metric, fy):
        return xbrl.lookup(facts, metric, fy)

    for metric, fy in [("revenue", latest), ("net_income", prev),
                       ("total_assets", latest), ("operating_cash_flow", latest)]:
        f = fact(metric, fy)
        if f:
            items.append(_item(
                f"{ticker}-{metric}-{fy}", "lookup", ticker,
                f"What was {company}'s {LABELS[metric]} for fiscal year {fy}, as reported in its 10-K?",
                {"value": f.value, "unit": "USD"}, {"rel": 0.005},
                [{"concept": f.concept, "accession": f.accession, "period_end": f.end}],
            ))

    rev, gp = fact("revenue", latest), fact("gross_profit", latest)
    cogs = fact("cost_of_revenue", latest)
    if rev and (gp or cogs):
        gross = gp.value if gp else rev.value - cogs.value
        used = [rev] + ([gp] if gp else [cogs])
        items.append(_item(
            f"{ticker}-gross_margin-{latest}", "derived", ticker,
            f"What was {company}'s gross margin (gross profit as a percentage of revenue) "
            f"for fiscal year {latest}?",
            {"value": round(gross / rev.value * 100, 4), "unit": "percent"}, {"abs_pp": 0.3},
            [{"concept": f.concept, "accession": f.accession, "period_end": f.end} for f in used],
        ))

    rev_prev = fact("revenue", prev)
    if rev and rev_prev:
        items.append(_item(
            f"{ticker}-revenue_growth-{latest}", "derived", ticker,
            f"By what percentage did {company}'s total revenue change in fiscal year {latest} "
            f"compared with fiscal year {prev}?",
            {"value": round((rev.value - rev_prev.value) / rev_prev.value * 100, 4), "unit": "percent"},
            {"abs_pp": 0.3},
            [{"concept": f.concept, "accession": f.accession, "period_end": f.end} for f in (rev, rev_prev)],
        ))

    ni_prev = fact("net_income", prev)
    if rev_prev and ni_prev:
        items.append(_item(
            f"{ticker}-net_margin-{prev}", "derived", ticker,
            f"What was {company}'s net profit margin (net income as a percentage of revenue) "
            f"for fiscal year {prev}?",
            {"value": round(ni_prev.value / rev_prev.value * 100, 4), "unit": "percent"}, {"abs_pp": 0.3},
            [{"concept": f.concept, "accession": f.accession, "period_end": f.end} for f in (ni_prev, rev_prev)],
        ))

    end = date.fromisoformat(years[latest])
    items.append(_item(
        f"{ticker}-fiscal_calendar-{latest}", "fiscal_calendar", ticker,
        f"In which calendar month did {company}'s fiscal year {latest} end?",
        {"month": end.month, "period_end": years[latest]}, {}, [{"period_end": years[latest]}],
    ))
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--out", default="eval/golden.jsonl")
    args = parser.parse_args()

    settings = get_settings()
    client = SECClient(settings.sec_user_agent, settings.cache_dir)
    rows: list[dict] = []
    for ticker in args.tickers:
        try:
            cik, title = client.cik_for(ticker)
        except KeyError:
            print(f"SKIP {ticker}: not in the SEC ticker list (delisted or renamed?)")
            continue
        facts = client.companyfacts(cik)
        company = facts.get("entityName") or title
        built = build_for(ticker.upper(), facts, company)
        rows.extend(built)
        print(f"{ticker}: {len(built)} questions")

    out = Path(args.out)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"Wrote {len(rows)} golden questions to {out}")


if __name__ == "__main__":
    main()

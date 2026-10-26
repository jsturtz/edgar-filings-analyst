"""Tools the agent can call. Each returns a string (what the LLM sees)."""

from __future__ import annotations

import json
from functools import lru_cache

from langchain_core.tools import tool

from . import xbrl
from .calculator import evaluate
from .config import get_settings
from .sec_client import SECClient
from .store import build_filter, get_store


@lru_cache(maxsize=1)
def _client() -> SECClient:
    settings = get_settings()
    return SECClient(settings.sec_user_agent, settings.cache_dir)


@lru_cache(maxsize=64)
def _facts(ticker: str) -> tuple[dict, str]:
    cik, company = _client().cik_for(ticker)
    return _client().companyfacts(cik), company


@tool
def get_financial_metric(ticker: str, metric: str, fiscal_year: int) -> str:
    """Exact annual figure as reported in a company's 10-K (SEC XBRL data).

    Use this for any "how much / what was" question about a standard financial figure.
    `fiscal_year` is the COMPANY'S fiscal year label (e.g. Apple's fiscal 2024 ended
    Sept 2024; Home Depot's fiscal 2024 ended Feb 2025) — call list_fiscal_years if unsure.
    metric must be one of: revenue, cost_of_revenue, gross_profit, operating_income,
    net_income, rd_expense, eps_diluted, operating_cash_flow, capex, total_assets,
    total_liabilities, stockholders_equity, cash.
    Values are in base units (whole US dollars; EPS in dollars per share).
    """
    facts, company = _facts(ticker.upper())
    try:
        fact = xbrl.lookup(facts, metric, int(fiscal_year))
    except KeyError as exc:
        return f"ERROR: {exc}"
    if fact is None:
        return (
            f"No reported {metric} found for {ticker.upper()} fiscal {fiscal_year}. "
            "The company may tag it differently; try search_filings on Item 8."
        )
    return json.dumps({"ticker": ticker.upper(), "company": company, **fact.to_dict()})


@tool
def list_fiscal_years(ticker: str) -> str:
    """List the fiscal years with a 10-K on file for a company and the date each one ended."""
    facts, company = _facts(ticker.upper())
    years = xbrl.fiscal_years(facts)
    return json.dumps({"ticker": ticker.upper(), "company": company,
                       "fiscal_year_end_dates": {str(k): v for k, v in years.items()}})


@tool
def search_filings(
    query: str,
    ticker: str | None = None,
    fiscal_year: int | None = None,
    item: str | None = None,
) -> str:
    """Semantic search over the text of indexed 10-K filings.

    Use for "why / how / what risks / what did management say" questions, and as a fallback
    for figures not covered by get_financial_metric. Filter whenever you know them:
    ticker (e.g. "AAPL"), fiscal_year (company's label), item ("7" = MD&A, "1A" = Risk
    Factors, "1" = Business, "8" = Financial Statements, "7A" = Market Risk).
    Each result shows its source; cite them.
    """
    settings = get_settings()
    docs = get_store().similarity_search(
        query, k=settings.top_k, filter=build_filter(ticker, fiscal_year, item)
    )
    if not docs:
        return "No matching passages. Try removing a filter or rephrasing."
    blocks = []
    for i, d in enumerate(docs, 1):
        m = d.metadata
        blocks.append(
            f"[{i}] {m['ticker']} FY{m['fiscal_year']} 10-K, Item {m['item']} ({m['section']}) "
            f"— {m['url']}\n{d.page_content}"
        )
    return "\n\n".join(blocks)


@tool
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression (+ - * / ** and parentheses). Always use this for
    margins, growth rates, ratios and unit conversions instead of mental math.
    Example: (211915 - 198270) / 198270 * 100"""
    try:
        return f"{evaluate(expression):.6g}"
    except (ValueError, SyntaxError, ZeroDivisionError) as exc:
        return f"ERROR: {exc}"


TOOLS = [get_financial_metric, list_fiscal_years, search_filings, calculate]

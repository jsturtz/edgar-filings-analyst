import importlib.util
from pathlib import Path

from edgar_agent.config import DEFAULT_TICKERS, TICKER_TIERS, tier_for

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def test_tiers():
    assert tier_for("aapl") == "mega"
    assert tier_for("JOUT") == "small"
    assert tier_for("ACME") == "custom"
    assert len(DEFAULT_TICKERS) == len(set(DEFAULT_TICKERS)) == sum(map(len, TICKER_TIERS.values()))


def _row(system, ticker, correct, type_="lookup", tier=None):
    row = {"system": system, "ticker": ticker, "type": type_, "correct": correct, "latency_s": 1.0, "id": ticker}
    if tier:
        row["tier"] = tier
    return row


def test_summary_tables_by_type_and_tier():
    rows = [
        _row("agent", "AAPL", True, tier="mega"), _row("baseline", "AAPL", True, tier="mega"),
        _row("agent", "JOUT", True, tier="small"), _row("baseline", "JOUT", False, tier="small"),
        _row("agent", "COST", True),  # saved before tiers existed -> labeled from ticker
    ]
    out = run_eval.summarize(rows, "test-model", 3)
    assert "### Accuracy by market-cap tier" in out
    assert "| mega | 1/1 (100%) | 1/1 (100%) |" in out
    assert "| small | 1/1 (100%) | 0/1 (0%) |" in out
    assert "| custom | 1/1 (100%) | – |" in out
    assert "large" not in out  # tiers with no rows are omitted

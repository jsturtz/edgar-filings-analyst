import json
from pathlib import Path

import pytest

from edgar_agent import xbrl

FACTS = json.loads((Path(__file__).parent / "fixtures" / "companyfacts_acme.json").read_text())


def test_current_period_not_prior_year_comparative():
    fact = xbrl.lookup(FACTS, "revenue", 2024)
    assert fact.value == 1120e6
    assert fact.end == "2024-09-28"
    assert fact.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def test_quarterly_values_inside_10k_are_ignored():
    assert xbrl.lookup(FACTS, "revenue", 2024).start == "2023-10-01"


def test_restatement_prefers_latest_filed():
    assert xbrl.lookup(FACTS, "net_income", 2024).value == 230e6


def test_instant_metric():
    assert xbrl.lookup(FACTS, "total_assets", 2023).value == 4500e6


def test_missing_metric_returns_none():
    assert xbrl.lookup(FACTS, "rd_expense", 2024) is None


def test_unknown_metric_raises():
    with pytest.raises(KeyError):
        xbrl.lookup(FACTS, "vibes", 2024)


def test_fiscal_year_mapping():
    assert xbrl.fiscal_years(FACTS) == {2023: "2023-09-30", 2024: "2024-09-28"}
    assert xbrl.fiscal_year_for_period_end(FACTS, "2024-09-28") == 2024

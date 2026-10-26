from edgar_agent.grading import grade

USD = {"type": "lookup", "expected": {"value": 391_035_000_000, "unit": "USD"}, "tolerance": {"rel": 0.005}}
PCT = {"type": "derived", "expected": {"value": 46.2077, "unit": "percent"}, "tolerance": {"abs_pp": 0.3}}
MONTH = {"type": "fiscal_calendar", "expected": {"month": 9}}


def test_usd_within_tolerance():
    assert grade(USD, 391_000_000_000, "USD").correct


def test_usd_in_millions_is_wrong():
    # A model that answers "391,035" (millions) without converting is wrong.
    assert not grade(USD, 391_035, "USD").correct


def test_percent():
    assert grade(PCT, 46.2, "percent").correct
    assert not grade(PCT, 0.462, "percent").correct


def test_missing_value():
    assert not grade(USD, None, None).correct


def test_month_by_value_or_name():
    assert grade(MONTH, 9, "month").correct
    assert grade(MONTH, None, "text", "Apple's fiscal 2024 ended in September 2024.").correct
    assert not grade(MONTH, None, "text", "It ended in December.").correct
    # naming two months is ambiguous -> wrong
    assert not grade(MONTH, None, "text", "Between September and October.").correct

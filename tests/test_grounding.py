from edgar_agent.grounding import check, extract_numbers


def test_extract_numbers():
    assert extract_numbers("Net sales | 391,035 | 383,285 and 12.5%") == [391035.0, 383285.0, 12.5]


def test_matches_exact_xbrl_value():
    evidence = ['{"value": 391035000000.0, "unit": "USD"}']
    assert check(391_035_000_000, "USD", evidence).grounded


def test_matches_table_in_millions():
    evidence = ["(in millions) | 2024\nNet sales | 391,035"]
    assert check(391_035_000_000, "USD", evidence).grounded


def test_matches_calculator_output():
    assert check(46.21, "percent", ["46.2077"]).grounded


def test_rejects_unsupported_number():
    result = check(400_000_000_000, "USD", ['{"value": 391035000000.0}'])
    assert not result.grounded
    assert "does not match" in result.reason


def test_rejects_number_without_evidence():
    assert not check(1.0, "USD", []).grounded


def test_non_numeric_answers_pass():
    assert check(None, "text", []).grounded
    assert check(9, "month", []).grounded

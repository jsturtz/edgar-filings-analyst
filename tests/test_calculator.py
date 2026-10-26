import pytest

from edgar_agent.calculator import evaluate


def test_arithmetic():
    assert evaluate("(1120 - 1000) / 1000 * 100") == pytest.approx(12.0)
    assert evaluate("391,035 / 1000") == pytest.approx(391.035)
    assert evaluate("-2 ** 2") == -4


@pytest.mark.parametrize("expr", ["__import__('os')", "a + 1", "open('x')", "[1, 2]"])
def test_rejects_non_arithmetic(expr):
    with pytest.raises((ValueError, SyntaxError)):
        evaluate(expr)

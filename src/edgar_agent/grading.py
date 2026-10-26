"""Grade a structured answer against a golden item. Pure functions, no LLM involved."""

from __future__ import annotations

import calendar
from dataclasses import dataclass

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}


@dataclass(frozen=True)
class Grade:
    correct: bool
    detail: str


def grade(item: dict, value: float | None, unit: str | None, answer_text: str = "") -> Grade:
    expected = item["expected"]
    kind = item["type"]

    if kind == "fiscal_calendar":
        want = expected["month"]
        if value is not None and int(round(value)) == want:
            return Grade(True, f"month {want}")
        text = answer_text.lower()
        named = [m for name, m in MONTHS.items() if name in text]
        if named == [want]:
            return Grade(True, f"month {want} named in text")
        return Grade(False, f"expected month {want}, got value={value} text={answer_text[:60]!r}")

    if value is None:
        return Grade(False, "no numeric value returned")

    want = expected["value"]
    tol = item.get("tolerance", {})
    if expected["unit"] == "percent":
        abs_pp = tol.get("abs_pp", 0.3)
        ok = abs(value - want) <= abs_pp
        return Grade(ok, f"expected {want:.2f}%, got {value:.2f}% (±{abs_pp}pp)")

    rel = tol.get("rel", 0.01)
    ok = abs(value - want) <= abs(want) * rel
    return Grade(ok, f"expected {want:,.0f}, got {value:,.0f} (±{rel:.1%})")

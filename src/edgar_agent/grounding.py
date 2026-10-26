"""Deterministic grounding check: is the answer's headline number backed by evidence?

The agent may only report a number that appeared in a tool result (an XBRL value,
a calculator output, or a figure in retrieved filing text). This catches the classic
failure where a model retrieves the right document and then "remembers" a different
number anyway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NUM = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?")
_SCALES = (1.0, 1e3, 1e6, 1e9)  # filing tables are often "in millions"/"in thousands"


@dataclass(frozen=True)
class GroundingResult:
    grounded: bool
    reason: str


def extract_numbers(text: str) -> list[float]:
    nums = []
    for raw in _NUM.findall(text):
        try:
            nums.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return nums


def check(value: float | None, unit: str | None, evidence: list[str], rel_tol: float = 0.005) -> GroundingResult:
    if value is None or unit in ("month", "text"):
        return GroundingResult(True, "no numeric claim to verify")
    if not evidence:
        return GroundingResult(False, "numeric answer but no tool results were used")

    candidates = [n for text in evidence for n in extract_numbers(text)]
    scales = _SCALES + ((100.0,) if unit == "percent" else ())  # ratio 0.462 -> 46.2%
    for n in candidates:
        for scale in scales:
            target = n * scale
            if target == 0 and value == 0:
                return GroundingResult(True, "matched 0")
            if target and abs(value - target) <= abs(target) * rel_tol:
                return GroundingResult(True, f"matched evidence value {n:g} (x{scale:g})")
    return GroundingResult(
        False,
        f"value {value:g} does not match any number in {len(evidence)} tool result(s); "
        "use the calculate tool for derived figures and report only retrieved or computed numbers",
    )

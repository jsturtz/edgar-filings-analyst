import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
FACTS = json.loads((ROOT / "tests" / "fixtures" / "companyfacts_acme.json").read_text())

_spec = importlib.util.spec_from_file_location("build_golden", ROOT / "eval" / "build_golden.py")
build_golden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_golden)


def test_builds_expected_questions():
    items = {i["id"]: i for i in build_golden.build_for("ACME", FACTS, "Acme Corp")}
    assert items["ACME-revenue-2024"]["expected"] == {"value": 1120e6, "unit": "USD"}
    assert items["ACME-net_income-2023"]["expected"]["value"] == 180e6
    assert items["ACME-total_assets-2024"]["expected"]["value"] == 5000e6
    # derived answers are computed in Python, not by a model
    assert items["ACME-gross_margin-2024"]["expected"]["value"] == round(500 / 1120 * 100, 4)
    assert items["ACME-revenue_growth-2024"]["expected"]["value"] == 12.0
    assert items["ACME-net_margin-2023"]["expected"]["value"] == 18.0
    assert items["ACME-fiscal_calendar-2024"]["expected"]["month"] == 9


def test_every_item_has_sources():
    for item in build_golden.build_for("ACME", FACTS, "Acme Corp"):
        assert item["sources"], item["id"]

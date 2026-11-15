"""Phase 10: the Power BI Control Tower definition is valid offline. Every field a visual uses exists in the
semantic model (a measure or a Gold column), every page has charts (not only cards) and visuals stay on the page."""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import fabric_powerbi as PB  # noqa: E402

TABLES_DIR = REPO / "powerbi" / "MIZAN Control Tower Model.SemanticModel" / "definition" / "tables"


def _gold_columns() -> dict[str, set[str]]:
    return {f.stem: set(re.findall(r"^\tcolumn (\w+)$", f.read_text(encoding="utf-8"), re.M))
            for f in TABLES_DIR.glob("*.tmdl")}


def test_every_report_field_exists_in_the_model():
    cols = _gold_columns()
    parts = PB.report_parts("00000000-0000-0000-0000-000000000000")
    seen = 0
    for path, body in parts.items():
        if not path.endswith("visual.json"):
            continue
        for ref in re.findall(r'"queryRef": "([^"]+)"', body):
            table, field = ref.split(".", 1)
            assert field in cols[table] or PB.MEASURE_TABLE.get(field) == table, ref
            seen += 1
    assert seen > 50


def test_pages_have_charts_slicers_and_fit_the_canvas():
    kinds_by_page = {}
    for pid, _title, _sub, visuals in PB.PAGES:
        kinds_by_page[pid] = {v[0] for v in visuals}
        for _kind, _roles, (x, y, w, h), _t in visuals:
            assert x >= 0 and y >= 0 and x + w <= 1280 and y + h <= 720, (pid, x, y, w, h)
    for kinds in kinds_by_page.values():
        assert {"card", "slicer", "tableEx"} <= kinds
        assert kinds & {"lineChart", "clusteredBarChart", "clusteredColumnChart", "donutChart"}


def test_report_parts_are_json():
    for path, body in PB.report_parts("x").items():
        if path.endswith((".json", ".pbir")):
            json.loads(body)


def test_report_registers_the_mizan_night_theme():
    parts = PB.report_parts("x")
    report = json.loads(parts["definition/report.json"])
    assert report["themeCollection"]["customTheme"]["name"] == PB.THEME_FILE
    theme = json.loads(parts[f"StaticResources/RegisteredResources/{PB.THEME_FILE}"])
    assert theme["background"] == PB.PANEL and theme["dataColors"][0] == PB.EMERALD


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
        for spec in visuals:                              # a spec may carry a 5th element: opts
            x, y, w, h = spec[2]
            assert x >= 0 and y >= 0 and x + w <= 1280 and y + h <= 720, (pid, x, y, w, h)
    for kinds in kinds_by_page.values():
        assert {"card", "slicer", "tableEx"} <= kinds
        assert kinds & {"lineChart", "clusteredBarChart", "clusteredColumnChart", "donutChart",
                        "treemap", "gauge", "lineStackedColumnComboChart"}


def _visuals() -> dict[str, dict]:
    parts = PB.report_parts("00000000-0000-0000-0000-000000000000")
    return {p.split("/")[-2]: json.loads(b) for p, b in parts.items() if p.endswith("visual.json")}


def _category_fills(container: dict) -> dict[str, str]:
    """{category value: hex} for the per-category dataPoint rules on one visual."""
    out = {}
    for rule in container["visual"].get("objects", {}).get("dataPoint", []):
        scope = rule.get("selector", {}).get("data", [{}])[0].get("scopeId", {})
        value = scope.get("Comparison", {}).get("Right", {}).get("Literal", {}).get("Value", "").strip("'")
        if value:
            out[value] = rule["properties"]["fill"]["solid"]["color"]["expr"]["Literal"]["Value"].strip("'")
    return out


def test_status_colours_never_depend_on_palette_order():
    """Green must mean a real pass, everywhere.

    Power BI hands out theme dataColors in whatever order categories happen to sort. That once painted
    SPLIT_RECOMMENDED (26 of 33 NDMO checks) in the pass colour and PASS in amber, and painted a
    CONFIRMED_REJECTION cyan. Every status category is now pinned explicitly.
    """
    fills = {k: v for c in _visuals().values() for k, v in _category_fills(c).items()}
    assert fills, "no per-category colours were emitted"
    assert fills["PASS"] == PB.EMERALD
    assert fills["REPORTED"] == PB.EMERALD
    assert fills["SPLIT_RECOMMENDED"] == PB.AMBER
    assert fills["CONFIRMED_REJECTION"] == PB.CRIT
    assert fills["TOP_SECRET"] == PB.CRIT
    # nothing that means trouble may wear the pass colour
    for bad in ("SPLIT_RECOMMENDED", "CONFIRMED_REJECTION", "FAIL"):
        assert fills.get(bad) != PB.EMERALD, f"{bad} must never be green"


def test_classification_donut_excludes_rows_that_have_no_tier():
    """The six DATA_QUALITY checks carry no table_classification; counting them produced a "(Blank)"
    slice on a chart titled "Tables by NDMO classification"."""
    # Only charts that GROUP BY the tier, not the detail table that merely lists the column.
    charts = [c for c in _visuals().values()
              if c["visual"]["visualType"] != "tableEx"
              and "table_classification" in json.dumps(
                  c["visual"].get("query", {}).get("queryState", {}).get("Category", {}))]
    assert charts, "the classification donut is missing"
    for c in charts:
        cfg = json.dumps(c.get("filterConfig", {}))        # filterConfig sits beside "visual", not inside
        assert "metric_family" in cfg and "CLASSIFICATION" in cfg, c["name"]


def test_cards_respond_to_their_own_page_slicer():
    """A card that ignores the page's slicer is worse than no card.

    Every relationship in this model is many-to-one into a dimension and single-direction, so a filter
    on one fact never reaches another fact. A Merchants card sourced from the settlement table sat at
    121 while the payments page was sliced to SADAD, implying every merchant accepts it. Cards must
    read the same table the page's slicer filters, or a dimension that table hangs off.
    """
    dims = {"dim_date_saudi", "merchant_store_reference"}
    for pid, _title, _sub, visuals in PB.PAGES:
        slicers = {spec[1]["Values"][0][1] for spec in visuals if spec[0] == "slicer"}
        if not slicers:
            continue
        for spec in visuals:
            if spec[0] != "card":
                continue
            measure = spec[1]["Values"][0][1]
            home = PB.MEASURE_TABLE[measure]
            # the slicer's table filters its own fact, and any dimension it points at
            assert home in slicers | dims, (
                f"{pid}: card '{measure}' reads {home}, which the page slicer ({slicers}) "
                "cannot filter through a single-direction relationship")


def test_gauges_pin_their_axis_and_declare_a_narrowed_one():
    """Two failures to guard against, and they pull in opposite directions.

    Left to scale itself a gauge invented a maximum of 199.99% for a percentage, so both ends must be
    pinned. But pinning everything to 0-100 makes a ratio that lives near 2% an invisible sliver, so a
    narrower maximum is allowed -- and then the TITLE must say so, because a reader who assumes 0-100 on a
    0-5 gauge misreads it by twenty times. A quietly truncated axis is worse than an auto-scaled one.
    """
    import re
    gauges = [c for c in _visuals().values() if c["visual"]["visualType"] == "gauge"]
    assert gauges, "no gauges in the report"
    for g in gauges:
        axis = g["visual"]["objects"]["axis"][0]["properties"]
        assert axis["min"]["expr"]["Literal"]["Value"] == "0D", g["name"]
        raw = axis["max"]["expr"]["Literal"]["Value"]
        assert raw.endswith("D"), g["name"]
        gmax = float(raw[:-1])
        assert gmax > 0, g["name"]
        if gmax != 100:
            title = g["visual"].get("visualContainerObjects", {}).get("title", [{}])[0]
            text = json.dumps(title)
            assert re.search(rf"0\s*-\s*{gmax:g}", text), (
                f"{g['name']}: axis narrowed to 0-{gmax:g} but the title does not say so: {text}")


def test_acceptance_rate_keeps_enough_decimals_to_show_one_rejection():
    """25,000 of 25,001 is 99.996%; at two decimals it reads 100.00% and the rejection disappears."""
    fmt = next(f for name, _dax, f in PB.MEASURES["fact_zatca_clearance_ledger"]
               if name == "Acceptance Rate Pct")
    assert fmt.count("0") >= 4, f"too few decimals to distinguish 99.996% from 100%: {fmt}"


def test_percentage_measures_carry_a_unit():
    """A card reading "99.07" with no unit is ambiguous; percentages and bps say so in the format."""
    for table, measures in PB.MEASURES.items():
        for name, _dax, fmt in measures:
            if name.endswith("Pct"):
                assert '"%"' in fmt, f"{table}.{name} has no percent suffix: {fmt}"
            if name.endswith("bps"):
                assert "bps" in fmt, f"{table}.{name} has no bps suffix: {fmt}"


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


def test_internal_columns_are_hidden_from_the_field_list():
    """The incremental watermark must not be browsable next to the money fields.

    `last_source_arrival_at` (ADR-015) is the newest Bronze arrival behind a row -- pipeline bookkeeping,
    not a business date. The model has to CARRY it (a Direct Lake table is the warehouse table, and the
    incremental build depends on the column), so the only control is whether a reader is offered it.

    This guards something that fails no other test: an unhidden operational column does not break a report,
    it just sits in the field list of three fact tables until somebody puts a wall-clock timestamp on a
    finance page. The model already has three meanings of "date" -- capture day, the day a bank line settles
    for, posting day -- and a fourth that is not a business date at all is a misreading waiting to happen.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import fabric_powerbi as fp

    assert "last_source_arrival_at" in fp.INTERNAL_COLUMNS

    # Build one table's TMDL with the watermark present and check it comes out hidden.
    table = next(iter(fp.TABLES))
    cols = {t: [("merchant_id", "string"), ("last_source_arrival_at", "dateTime")] for t in fp.TABLES}
    import os
    os.environ.setdefault("FABRIC_SQL_ENDPOINT", "endpoint.example")
    os.environ.setdefault("WH_MIZAN_ID", "wh-id")
    tmdl = fp.model_parts(cols)[f"definition/tables/{table}.tmdl"]

    watermark = tmdl.split("column last_source_arrival_at", 1)[1].split("column ", 1)[0]
    assert "isHidden" in watermark, "the watermark column is browsable in the report field list"
    business = tmdl.split("column merchant_id", 1)[1].split("column ", 1)[0]
    assert "isHidden" not in business, "a business column was hidden; the rule is too broad"

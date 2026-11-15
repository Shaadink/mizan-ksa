"""Phase 10: Power BI Control Tower as code. Direct Lake semantic model (TMDL) over WH_MIZAN gld tables, and a
3-page report (PBIR): CFO Settlement, Tax ZATCA Health, CDO Data Trust. Created through the Fabric REST API.

    .\\.venv\\Scripts\\python.exe scripts\\fabric_powerbi.py          # (re)create model + report
Definitions are also written to powerbi/ so the model and report are versioned in git.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import fabric_provision as P  # noqa: E402
from fabric_deploy import API, _req, env  # noqa: E402

from mizan.privacy.crypto import load_dotenv  # noqa: E402

MODEL, REPORT = "MIZAN Control Tower Model", "MIZAN Control Tower"
TABLES = ("fact_merchant_settlement_recon", "fact_zatca_clearance_ledger", "mart_ndmo_scorecard", "dim_date_saudi")
OUT = REPO / "powerbi"
MEASURES = {
    "fact_merchant_settlement_recon": [
        ("Gross Captures SAR", "SUM(fact_merchant_settlement_recon[gross_captures_sar])", "#,0.00"),
        ("Refunds and Disputes SAR", "SUM(fact_merchant_settlement_recon[refunds_and_disputes_sar])", "#,0.00"),
        ("Acquirer Fees SAR", "SUM(fact_merchant_settlement_recon[acquirer_fees_sar])", "#,0.00"),
        ("Bank Paid SAR", "SUM(fact_merchant_settlement_recon[bank_paid_sar])", "#,0.00"),
        ("In Transit SAR", "SUM(fact_merchant_settlement_recon[in_transit_sar])", "#,0.00"),
        ("GL Card Clearing SAR", "SUM(fact_merchant_settlement_recon[gl_card_clearing_sar])", "#,0.00"),
        ("Unexplained Bank Variance SAR", "SUM(fact_merchant_settlement_recon[unexplained_bank_variance_sar])",
         "#,0.00"),
        ("Unexplained GL Variance SAR", "SUM(fact_merchant_settlement_recon[unexplained_gl_variance_sar])", "#,0.00"),
        ("Halala Breaks", "COUNTROWS(FILTER(fact_merchant_settlement_recon, "
                          "fact_merchant_settlement_recon[unexplained_bank_variance_sar] <> 0 || "
                          "fact_merchant_settlement_recon[unexplained_gl_variance_sar] <> 0)) + 0", "0"),
        ("Merchants", "DISTINCTCOUNT(fact_merchant_settlement_recon[merchant_id])", "#,0"),
        ("MID Days", "COUNTROWS(fact_merchant_settlement_recon)", "#,0")],
    "fact_zatca_clearance_ledger": [
        ("Accepted Documents", "COUNTROWS(fact_zatca_clearance_ledger)", "#,0"),
        ("Documents Total SAR", "SUM(fact_zatca_clearance_ledger[total_incl_vat_sar])", "#,0.00"),
        ("Corrections", "COUNTROWS(FILTER(fact_zatca_clearance_ledger, "
                        "NOT ISBLANK(fact_zatca_clearance_ledger[corrects_invoice_uuid])))", "0"),
        ("Retried Documents", "COUNTROWS(FILTER(fact_zatca_clearance_ledger, "
                              "fact_zatca_clearance_ledger[attempts] > 1))", "#,0"),
        ("EGS Devices", "DISTINCTCOUNT(fact_zatca_clearance_ledger[egs_id])", "0")],
    "mart_ndmo_scorecard": [
        ("Quality Checks Passing", "CALCULATE(COUNTROWS(mart_ndmo_scorecard), mart_ndmo_scorecard[status] = \"PASS\", "
                                   "mart_ndmo_scorecard[metric_family] = \"DATA_QUALITY\")", "0"),
        ("Tables Needing Split", "CALCULATE(COUNTROWS(mart_ndmo_scorecard), "
                                 "mart_ndmo_scorecard[status] = \"SPLIT_RECOMMENDED\")", "0"),
        ("Scorecard Checks", "COUNTROWS(mart_ndmo_scorecard)", "0"),
        ("Average Score Pct", "AVERAGE(mart_ndmo_scorecard[score_pct])", "#,0.00"),
        ("Threshold Pct", "AVERAGE(mart_ndmo_scorecard[threshold_pct])", "#,0.00"),
        ("Quality Score Pct", "CALCULATE(AVERAGE(mart_ndmo_scorecard[score_pct]), "
                              "mart_ndmo_scorecard[metric_family] = \"DATA_QUALITY\")", "#,0.00"),
        ("Classified Tables", "CALCULATE(COUNTROWS(mart_ndmo_scorecard), "
                              "NOT ISBLANK(mart_ndmo_scorecard[table_classification]))", "0")],
}
# Layout grid for a 1280 x 720 page. Each visual: (kind, role-spec, (x, y, w, h), title).
# Roles: ("m", measure) or ("c", table, column). Charts sort descending by their first Y measure.
R, Z, N = "fact_merchant_settlement_recon", "fact_zatca_clearance_ledger", "mart_ndmo_scorecard"
D = "dim_date_saudi"
CARD_Y, CARD_H = 70, 88


def _cards(measures: list[str]) -> list[tuple]:
    w = (1240 - 10 * (len(measures) - 1)) // len(measures)
    return [("card", {"Values": [("m", m)]}, (20 + i * (w + 10), CARD_Y, w, CARD_H), None)
            for i, m in enumerate(measures)]


PAGES = [
    ("cfo_settlement", "CFO Settlement",
     "Every halala reconciled: captures vs mada/SADAD bank file vs ERP card clearing. Variance must be SAR 0.00.",
     _cards(["Gross Captures SAR", "Bank Paid SAR", "In Transit SAR", "Unexplained Bank Variance SAR",
             "Unexplained GL Variance SAR", "Halala Breaks"]) + [
        ("lineChart", {"Category": [("c", D, "calendar_date")],
                       "Y": [("m", "Gross Captures SAR"), ("m", "Bank Paid SAR"), ("m", "GL Card Clearing SAR")]},
         (20, 168, 800, 270), "Captures vs bank paid vs GL clearing by business day "
         "(last day: bank file not yet arrived, T+1 in transit)"),
        ("clusteredBarChart", {"Category": [("c", R, "merchant_id")], "Y": [("m", "Gross Captures SAR")]},
         (830, 168, 430, 270), "Top merchants by gross captures"),
        ("slicer", {"Values": [("c", R, "merchant_id")]}, (20, 450, 200, 255), "Merchant"),
        ("tableEx", {"Values": [("c", R, c) for c in (
            "merchant_id", "business_date_ksa", "gross_captures_sar", "acquirer_fees_sar", "bank_paid_sar",
            "in_transit_sar", "gl_card_clearing_sar", "unexplained_bank_variance_sar",
            "unexplained_gl_variance_sar")]}, (230, 450, 1030, 255), "Reconciliation by MID-day (key spine)")]),
    ("tax_zatca_health", "Tax ZATCA Health",
     "Phase-2 e-invoice chain: zero ICV gaps, transport failures (5xx/timeout) retried with identical UUID and bytes.",
     _cards(["Accepted Documents", "Documents Total SAR", "Corrections", "Retried Documents", "EGS Devices"]) + [
        ("donutChart", {"Category": [("c", Z, "state")], "Y": [("m", "Accepted Documents")]},
         (20, 168, 380, 270), "Documents by ZATCA outcome"),
        ("clusteredColumnChart", {"Category": [("c", Z, "egs_id")], "Y": [("m", "Accepted Documents")]},
         (410, 168, 420, 270), "Documents per EGS device"),
        ("clusteredColumnChart", {"Category": [("c", Z, "invoice_flow")],
                                  "Y": [("m", "Documents Total SAR")]},
         (840, 168, 420, 270), "SAR by flow (REPORTING = B2C, CLEARANCE = B2B)"),
        ("slicer", {"Values": [("c", Z, "document_type")]}, (20, 450, 200, 255), "Document type"),
        ("tableEx", {"Values": [("c", Z, c) for c in (
            "egs_id", "icv", "invoice_flow", "document_type", "state", "attempts", "issue_date_ksa",
            "total_incl_vat_sar", "corrects_invoice_uuid")]}, (230, 450, 1030, 255), "Clearance ledger")]),
    ("cdo_data_trust", "CDO Data Trust",
     "NDMO scorecard: data quality checks against thresholds and 4-tier classification "
     "(TOP_SECRET / SECRET / CONFIDENTIAL / PUBLIC).",
     _cards(["Scorecard Checks", "Quality Checks Passing", "Quality Score Pct", "Tables Needing Split"]) + [
        ("clusteredBarChart", {"Category": [("c", N, "dimension")],
                               "Y": [("m", "Average Score Pct"), ("m", "Threshold Pct")]},
         (20, 168, 620, 270), "Score vs threshold by quality dimension"),
        ("donutChart", {"Category": [("c", N, "status")], "Y": [("m", "Scorecard Checks")]},
         (650, 168, 300, 270), "Checks by status"),
        ("donutChart", {"Category": [("c", N, "table_classification")], "Y": [("m", "Classified Tables")]},
         (960, 168, 300, 270), "Tables by NDMO classification"),
        ("slicer", {"Values": [("c", N, "metric_family")]}, (20, 450, 200, 255), "Metric family"),
        ("tableEx", {"Values": [("c", N, c) for c in (
            "metric_family", "dimension", "subject_table", "numerator", "denominator", "score_pct",
            "threshold_pct", "status", "table_classification")]}, (230, 450, 1030, 255), "NDMO scorecard")]),
]
MEASURE_TABLE = {m: t for t, ms in MEASURES.items() for m, _, _ in ms}
TYPE_MAP = {"varchar": "string", "char": "string", "nvarchar": "string", "int": "int64", "bigint": "int64",
            "smallint": "int64", "bit": "boolean", "decimal": "decimal", "numeric": "decimal", "date": "dateTime",
            "datetime2": "dateTime", "float": "double", "real": "double"}


def warehouse_columns() -> dict[str, list[tuple[str, str]]]:
    import pyodbc
    e = os.environ
    cs = (f"Driver={{ODBC Driver 18 for SQL Server}};Server={e['FABRIC_SQL_ENDPOINT']},1433;Database=WH_MIZAN;"
          f"Authentication=ActiveDirectoryServicePrincipal;UID={e['FABRIC_CLIENT_ID']};PWD={e['FABRIC_CLIENT_SECRET']};"
          "Encrypt=yes")
    con = pyodbc.connect(cs, timeout=60)
    out: dict[str, list[tuple[str, str]]] = {}
    for t, c, typ in con.cursor().execute(
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'gld' "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION").fetchall():
        if t in TABLES:
            out.setdefault(t, []).append((c, TYPE_MAP.get(typ.lower(), "string")))
    return out


def tag(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mizan-ksa/" + "/".join(parts)))


def model_parts(cols: dict[str, list[tuple[str, str]]]) -> dict[str, str]:
    endpoint, wh = os.environ["FABRIC_SQL_ENDPOINT"], os.environ["WH_MIZAN_ID"]
    parts = {"definition.pbism": json.dumps({"version": "4.0", "settings": {}}),
             "definition/database.tmdl": "database\n\tcompatibilityLevel: 1604\n",
             "definition/expressions.tmdl": (
                 "expression DatabaseQuery =\n\t\tlet\n"
                 f"\t\t\tdatabase = Sql.Database(\"{endpoint}\", \"{wh}\")\n\t\tin\n\t\t\tdatabase\n"
                 f"\tlineageTag: {tag('expr')}\n")}
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tsourceQueryCulture: en-US", ""]
    model += [f"ref table {t}" for t in TABLES]
    model += ["", "relationship " + tag("rel-recon-date"),
              "\tfromColumn: fact_merchant_settlement_recon.business_date_ksa",
              "\ttoColumn: dim_date_saudi.calendar_date", "",
              "relationship " + tag("rel-zatca-date"),
              "\tfromColumn: fact_zatca_clearance_ledger.issue_date_ksa",
              "\ttoColumn: dim_date_saudi.calendar_date", ""]
    parts["definition/model.tmdl"] = "\n".join(model) + "\n"
    for t in TABLES:
        lines = [f"table {t}", f"\tlineageTag: {tag(t)}", ""]
        for m, expr, fmt in MEASURES.get(t, []):
            lines += [f"\tmeasure '{m}' = {expr}", f"\t\tformatString: {fmt}", f"\t\tlineageTag: {tag(t, m)}", ""]
        for c, dt in cols[t]:
            lines += [f"\tcolumn {c}", f"\t\tdataType: {dt}", f"\t\tlineageTag: {tag(t, c)}",
                      "\t\tsummarizeBy: none", f"\t\tsourceColumn: {c}", ""]
            if dt == "decimal":
                lines.insert(-1, "\t\tformatString: #,0.00")
        lines += [f"\tpartition {t} = entity", "\t\tmode: directLake", "\t\tsource",
                  f"\t\t\tentityName: {t}", "\t\t\tschemaName: gld", "\t\t\texpressionSource: DatabaseQuery", ""]
        parts[f"definition/tables/{t}.tmdl"] = "\n".join(lines)
    return parts


def _field_measure(m: str) -> dict:
    t = MEASURE_TABLE[m]
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": t}}, "Property": m}},
            "queryRef": f"{t}.{m}", "nativeQueryRef": m}


def _field_column(t: str, c: str) -> dict:
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": t}}, "Property": c}},
            "queryRef": f"{t}.{c}", "nativeQueryRef": c}


VIS = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.3.0/schema.json"
PAGE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.3.0/schema.json"


def report_parts(model_id: str) -> dict[str, str]:
    parts = {
        "definition.pbir": json.dumps({"version": "4.0", "datasetReference": {"byConnection": {
            "connectionString": (f'Data Source="powerbi://api.powerbi.com/v1.0/myorg/mizan-ksa-dev";'
                                 f"initial catalog={MODEL};access mode=readonly;integrated security=ClaimsToken;"
                                 f"semanticmodelid={model_id}"),
            "pbiServiceModelId": None, "pbiModelVirtualServerName": "sobe_wowvirtualserver",
            "pbiModelDatabaseName": model_id, "name": "EntityDataSource",
            "connectionType": "pbiServiceXmlaStyleLive"}}}),
        "definition/version.json": json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/"
                       "1.0.0/schema.json", "version": "2.0.0"}),
        "definition/report.json": json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.2.0/"
                       "schema.json",
            "themeCollection": {"baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.59",
                                              "type": "SharedResources"},
                                "customTheme": {"name": THEME_FILE, "reportVersionAtImport": "5.59",
                                                "type": "RegisteredResources"}},
            "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                                  "items": [{"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"}]}],
            "layoutOptimization": "None",
            "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True}}),
        f"StaticResources/RegisteredResources/{THEME_FILE}": json.dumps(THEME),
        "definition/pages/pages.json": json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/"
                       "1.0.0/schema.json", "pageOrder": [p[0] for p in PAGES], "activePageName": PAGES[0][0]}),
    }
    for pid, title, subtitle, visuals in PAGES:
        parts[f"definition/pages/{pid}/page.json"] = json.dumps({
            "$schema": PAGE, "name": pid, "displayName": title, "displayOption": "FitToPage",
            "height": 720, "width": 1280,
            "objects": {"background": [{"properties": {"color": _solid(BG), "transparency": _lit("0D")}}]}})
        for i, (kind, roles, (x, y, w, h), vtitle) in enumerate(visuals):
            vid = f"{pid}_v{i}"
            parts[f"definition/pages/{pid}/visuals/{vid}/visual.json"] = json.dumps(
                {"$schema": VIS, "name": vid, "position": {"x": x, "y": y, "z": i, "width": w, "height": h},
                 "visual": _visual(kind, roles, vtitle)})
        parts[f"definition/pages/{pid}/visuals/{pid}_title/visual.json"] = json.dumps({
            "$schema": VIS, "name": f"{pid}_title", "position": {"x": 20, "y": 2, "z": 99, "width": 1240, "height": 64},
            "visual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [
                {"textRuns": [{"value": f"MIZAN-KSA Control Tower  |  {title}",
                               "textStyle": {"fontSize": "16pt", "fontWeight": "bold", "color": ACCENT}}]},
                {"textRuns": [{"value": subtitle, "textStyle": {"fontSize": "9pt", "color": MUTED}}]}]}}]}}})
    return parts


# "MIZAN Night": the same palette as the Command Center (night page, gold = the scales, emerald = captured money)
BG, PANEL, LINE, INK, MUTED = "#060B16", "#101B30", "#22314D", "#E9EFF6", "#8D9BB1"
ACCENT, EMERALD = "#D9B25F", "#2FBF8F"
THEME_FILE = "MizanNight.json"


def _c(color: str) -> dict:
    return {"solid": {"color": color}}


THEME = {
    "name": "MIZAN Night",
    "dataColors": [EMERALD, ACCENT, "#5CC8FF", "#F2A93B", "#FF5D63", "#9B8CFF", "#7FD1B9", "#F3D99C"],
    "background": PANEL, "foreground": INK, "tableAccent": ACCENT,
    "good": "#3AD29F", "neutral": "#F2A93B", "bad": "#FF5D63",
    "textClasses": {"label": {"color": "#C3CEE0"}, "callout": {"color": ACCENT}, "title": {"color": INK},
                    "header": {"color": INK}},
    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": _c(PANEL), "transparency": 0}],
            "border": [{"show": True, "color": _c(LINE), "radius": 10}],
            "title": [{"fontColor": _c(INK)}],
            "visualHeader": [{"background": _c(PANEL), "foreground": _c(MUTED)}],
            "categoryAxis": [{"labelColor": _c(MUTED), "titleColor": _c(MUTED)}],
            "valueAxis": [{"labelColor": _c(MUTED), "titleColor": _c(MUTED), "gridlineColor": _c(LINE)}],
            "legend": [{"labelColor": _c("#C3CEE0")}],
            "labels": [{"color": _c("#C3CEE0")}]}},
        "page": {"*": {"background": [{"color": _c(BG), "transparency": 0}],
                       "outspace": [{"color": _c(BG), "transparency": 0}]}},
        "tableEx": {"*": {
            "columnHeaders": [{"fontColor": _c(ACCENT), "backColor": _c("#0A1324")}],
            "values": [{"fontColorPrimary": _c(INK), "backColorPrimary": _c(PANEL),
                        "fontColorSecondary": _c(INK), "backColorSecondary": _c("#0D1729")}],
            "grid": [{"gridHorizontalColor": _c(LINE), "gridVerticalColor": _c(LINE), "outlineColor": _c(LINE)}]}},
        "slicer": {"*": {"items": [{"fontColor": _c("#C3CEE0"), "background": _c(PANEL)}],
                         "header": [{"fontColor": _c(INK)}]}},
        "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
    },
}


def _lit(v: str) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def _solid(color: str) -> dict:
    return {"solid": {"color": _lit(f"'{color}'")}}


def _proj(r: tuple) -> dict:
    return _field_measure(r[1]) if r[0] == "m" else _field_column(r[1], r[2])


def _visual(kind: str, roles: dict[str, list[tuple]], title: str | None) -> dict:
    query: dict = {"queryState": {role: {"projections": [_proj(r) for r in rs]} for role, rs in roles.items()}}
    ys = [r for r in roles.get("Y", []) if r[0] == "m"]
    if ys and kind in ("clusteredBarChart", "clusteredColumnChart", "donutChart"):
        query["sortDefinition"] = {"sort": [{"field": _proj(ys[0])["field"], "direction": "Descending"}],
                                   "isDefaultSort": True}
    container = {"background": [{"properties": {"show": _lit("true"), "color": _solid(PANEL),
                                                "transparency": _lit("0D")}}],
                 "border": [{"properties": {"show": _lit("true"), "color": _solid(LINE),
                                            "radius": _lit("8D")}}],
                 "dropShadow": [{"properties": {"show": _lit("true")}}]}
    if title:
        container["title"] = [{"properties": {"show": _lit("true"), "text": _lit("'" + title.replace("'", "''") + "'"),
                                              "fontColor": _solid(INK)}}]
    objects: dict = {}
    if kind == "card":
        m = roles["Values"][0][1]
        units = "1000000D" if m.endswith("SAR") and "Variance" not in m else "1D"    # SAR in millions, counts exact
        objects = {"labels": [{"properties": {"color": _solid(ACCENT), "fontSize": _lit("20D"),
                                              "labelDisplayUnits": _lit(units)}}],
                   "categoryLabels": [{"properties": {"show": _lit("true"), "fontSize": _lit("9D"),
                                                      "color": _solid(MUTED)}}]}
    elif kind in ("lineChart", "clusteredBarChart", "clusteredColumnChart"):
        objects = {"legend": [{"properties": {"show": _lit("true"), "position": _lit("'Top'")}}]}
        if kind == "clusteredColumnChart" or (kind == "clusteredBarChart" and len(ys) == 1):
            objects["dataPoint"] = [{"properties": {"fill": _solid(EMERALD)}}]
            objects["legend"] = [{"properties": {"show": _lit("false")}}]
    elif kind == "slicer":
        objects = {"data": [{"properties": {"mode": _lit("'Basic'")}}]}
    v = {"visualType": kind, "query": query, "visualContainerObjects": container, "drillFilterOtherVisuals": True}
    if objects:
        v["objects"] = objects
    return v


def upsert(kind: str, name: str, parts: dict[str, str], fmt: str | None = None) -> str:
    ws = env("FABRIC_WORKSPACE_ID")
    defn = {"parts": [{"path": p, "payloadType": "InlineBase64",
                       "payload": base64.b64encode(c.encode("utf-8")).decode()} for p, c in parts.items()]}
    if fmt:
        defn["format"] = fmt
    st, _, raw = _req("GET", f"{API}/workspaces/{ws}/{kind}", P.TOKEN)
    existing = next((i for i in json.loads(raw).get("value", []) if i["displayName"] == name), None)
    if existing:
        url, body = f"{API}/workspaces/{ws}/{kind}/{existing['id']}/updateDefinition", {"definition": defn}
    else:
        url, body = f"{API}/workspaces/{ws}/{kind}", {"displayName": name, "definition": defn}
    st, headers, raw = _req("POST", url, P.TOKEN, json.dumps(body).encode(), {"Content-Type": "application/json"})
    if st == 202:
        loc = headers.get("Location")
        for _ in range(120):
            time.sleep(4)
            _, _, r2 = _req("GET", loc, P.TOKEN)
            js = json.loads(r2 or b"{}")
            if js.get("status") in ("Succeeded", "Failed"):
                if js["status"] == "Failed":
                    raise RuntimeError(f"{kind} {name}: {json.dumps(js)[:1500]}")
                break
    elif st not in (200, 201):
        raise RuntimeError(f"{kind} {name} ({st}): {raw[:1500]!r}")
    st, _, raw = _req("GET", f"{API}/workspaces/{ws}/{kind}", P.TOKEN)
    iid = next(i["id"] for i in json.loads(raw)["value"] if i["displayName"] == name)
    print(f"{kind[:-1]:<14} {name:<28} {'updated' if existing else 'created'} {iid}")
    return iid


def save(folder: str, parts: dict[str, str]) -> None:
    for p, c in parts.items():
        f = OUT / folder / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(c.replace(os.environ["FABRIC_SQL_ENDPOINT"], "<WH_MIZAN_SQL_ENDPOINT>")
                     .replace(os.environ["WH_MIZAN_ID"], "<WH_MIZAN_ID>"), encoding="utf-8", newline="\n")


def main() -> None:
    load_dotenv()
    os.environ.setdefault("MIZAN_AZ_PROFILE", ".azure-college")
    P.TOKEN = P.token()                                   # owned by the signed-in user, visible in the portal
    cols = warehouse_columns()
    mparts = model_parts(cols)
    save("MIZAN Control Tower Model.SemanticModel", mparts)
    mid = upsert("semanticModels", MODEL, mparts)
    rparts = report_parts(mid)
    save("MIZAN Control Tower.Report", {k: v.replace(mid, "<SEMANTIC_MODEL_ID>") for k, v in rparts.items()})
    rid = upsert("reports", REPORT, rparts)
    ws = env("FABRIC_WORKSPACE_ID")
    print(f"open: https://app.fabric.microsoft.com/groups/{ws}/reports/{rid}")


if __name__ == "__main__":
    main()

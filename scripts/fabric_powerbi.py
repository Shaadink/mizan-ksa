"""Phase 10: Power BI Control Tower as code. Direct Lake semantic model (TMDL) over WH_MIZAN gld tables, and a
3-page report (PBIR): CFO Settlement, Tax ZATCA Health, CDO Data Trust. Created through the Fabric REST API.

    .\\.venv\\Scripts\\python.exe scripts\\fabric_powerbi.py          # (re)create model + report
Definitions are also written to powerbi/ so the model and report are versioned in git.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
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
TABLES = ("fact_merchant_settlement_recon", "fact_zatca_clearance_ledger", "mart_ndmo_scorecard", "dim_date_saudi",
          "merchant_store_reference",    # store seed (owner-approved): city / EGS / channel per merchant
          "fact_payment_method_daily",   # owner-approved: captures + bank fees per payment scheme
          "fact_merchant_dispute_monitor")  # owner-approved: card-scheme dispute ratio + count floor
OUT = REPO / "powerbi"
REJ = 'fact_zatca_clearance_ledger[state] = "CONFIRMED_REJECTION"'
DM = "fact_merchant_dispute_monitor"   # used by measures defined above PAGES, so it lives here
# Every filter inside CALCULATE is wrapped in KEEPFILTERS: a plain column filter REPLACES the filter coming from a
# visual's category on that same column (bug 2: the NDMO donut showed 27 / 27 / 27 instead of 17 / 1 / 6 / 3).
MEASURES = {
    "fact_merchant_settlement_recon": [
        ("Gross Captures SAR", "SUM(fact_merchant_settlement_recon[gross_captures_sar])", "#,0.00"),
        ("Refunds and Disputes SAR", "SUM(fact_merchant_settlement_recon[refunds_and_disputes_sar])", "#,0.00"),
        ("Acquirer Fees SAR", "SUM(fact_merchant_settlement_recon[acquirer_fees_sar])", "#,0.00"),
        ("Bank Paid SAR", "SUM(fact_merchant_settlement_recon[bank_paid_sar])", "#,0.00"),
        # bug 5: a MID-day whose bank file has not arrived is NOT ASSESSED; its bank line is blank, never 0.00
        ("Bank Paid SAR (Assessed)", "CALCULATE(SUM(fact_merchant_settlement_recon[bank_paid_sar]), "
                                     "KEEPFILTERS(fact_merchant_settlement_recon[in_transit_sar] = 0))", "#,0.00"),
        ("MID Days Assessed", "CALCULATE(COUNTROWS(fact_merchant_settlement_recon), "
                              "KEEPFILTERS(fact_merchant_settlement_recon[in_transit_sar] = 0)) + 0", "#,0"),
        ("MID Days Not Assessed", "CALCULATE(COUNTROWS(fact_merchant_settlement_recon), "
                                  "KEEPFILTERS(fact_merchant_settlement_recon[in_transit_sar] <> 0)) + 0", "#,0"),
        ("In Transit SAR", "SUM(fact_merchant_settlement_recon[in_transit_sar])", "#,0.00"),
        # Portfolio ratio is disputes over captures, NOT the average of per-merchant ratios: averaging
        # ratios weights a 43-capture merchant the same as a 10,530-capture one, which is the exact
        # mistake this page exists to point out.
        ("GL Card Clearing SAR", "SUM(fact_merchant_settlement_recon[gl_card_clearing_sar])", "#,0.00"),
        ("Unexplained Bank Variance SAR", "SUM(fact_merchant_settlement_recon[unexplained_bank_variance_sar])",
         "#,0.00"),
        ("Unexplained GL Variance SAR", "SUM(fact_merchant_settlement_recon[unexplained_gl_variance_sar])", "#,0.00"),
        ("Halala Breaks", "COUNTROWS(FILTER(fact_merchant_settlement_recon, "
                          "fact_merchant_settlement_recon[unexplained_bank_variance_sar] <> 0 || "
                          "fact_merchant_settlement_recon[unexplained_gl_variance_sar] <> 0)) + 0", "0"),
        # bug 6: MID900001's share of SAR (73.8%) is not the skew test's 65%-of-rows setting; both are labelled
        ("Largest Merchant Share of SAR Pct",
         "DIVIDE(MAXX(VALUES(fact_merchant_settlement_recon[merchant_id]), "
         "CALCULATE(SUM(fact_merchant_settlement_recon[gross_captures_sar]))), "
         "CALCULATE(SUM(fact_merchant_settlement_recon[gross_captures_sar]), "
         "REMOVEFILTERS(fact_merchant_settlement_recon[merchant_id]))) * 100", "0.0\"%\""),
        ("Expected Net Payable SAR", "SUM(fact_merchant_settlement_recon[expected_net_payable_sar])", "#,0.00"),
        ("Merchants", "DISTINCTCOUNT(fact_merchant_settlement_recon[merchant_id])", "#,0"),
        ("MID Days", "COUNTROWS(fact_merchant_settlement_recon)", "#,0")],
    DM: [
        # Card-scheme dispute monitoring. Both counts are measures on purpose: the page's claim is that a
        # ratio without a volume floor is a noise generator, and that claim needs both numbers to stand.
        # = 1, not = TRUE(). The dbt model writes these flags with bool_true(), which is literal 1 on the
        # Fabric target, so WH_MIZAN types them BIT and the semantic model imports them as int64. Comparing
        # an int64 to TRUE() does not return false, it errors -- the card renders as "See details" and the
        # page loses the two numbers it exists to show. Found by looking at the deployed report.
        ("Merchants Flagged By Ratio Only",
         f"CALCULATE(COUNTROWS({DM}), KEEPFILTERS({DM}[breaches_ratio] = 1)) + 0", "#,0"),
        ("Merchants In Programme",
         f"CALCULATE(COUNTROWS({DM}), KEEPFILTERS({DM}[in_monitoring_programme] = 1)) + 0", "#,0"),
        ("Merchants Monitored", f"COUNTROWS({DM}) + 0", "#,0"),
        ("Disputes", f"SUM({DM}[dispute_count]) + 0", "#,0"),
        ("Captures", f"SUM({DM}[capture_count]) + 0", "#,0"),
        ("Dispute Ratio Pct", f"DIVIDE(SUM({DM}[dispute_count]), SUM({DM}[capture_count])) * 100", '0.00"%"'),
        ("Disputed SAR", f"SUM({DM}[disputes_sar])", "#,0.00"),
        ("Portfolio Dispute Ratio Pct",
         f"DIVIDE(SUM({DM}[dispute_count]), SUM({DM}[capture_count])) * 100", '0.00"%"'),
    ],
    "fact_zatca_clearance_ledger": [
        ("Documents in Chain", "COUNTROWS(fact_zatca_clearance_ledger)", "#,0"),
        # bug 1: the ledger holds the confirmed rejection; "accepted" excludes it explicitly
        ("Accepted Documents", f"CALCULATE(COUNTROWS(fact_zatca_clearance_ledger), KEEPFILTERS(NOT ({REJ}))) + 0",
         "#,0"),
        ("Rejected Documents", f"CALCULATE(COUNTROWS(fact_zatca_clearance_ledger), KEEPFILTERS({REJ})) + 0", "#,0"),
        # bug 7: tax SAR (30.92M) = card invoices (22.39M = gross captures) + cash invoices + credit notes, all
        # positive amounts with the document type carrying the sign; the report shows the parts and the net
        ("Invoices SAR", "CALCULATE(SUM(fact_zatca_clearance_ledger[total_incl_vat_sar]), "
                         f"KEEPFILTERS(NOT ({REJ})), "
                         "KEEPFILTERS(fact_zatca_clearance_ledger[document_type] = \"INVOICE\"))", "#,0.00"),
        ("Credit Notes SAR", "CALCULATE(SUM(fact_zatca_clearance_ledger[total_incl_vat_sar]), "
                             f"KEEPFILTERS(NOT ({REJ})), "
                             "KEEPFILTERS(fact_zatca_clearance_ledger[document_type] = \"CREDIT_NOTE\"))", "#,0.00"),
        ("Net Invoiced SAR", "[Invoices SAR] - [Credit Notes SAR]", "#,0.00"),
        ("Corrections", "COUNTROWS(FILTER(fact_zatca_clearance_ledger, "
                        "NOT ISBLANK(fact_zatca_clearance_ledger[corrects_invoice_uuid])))", "0"),
        ("Retried Documents", "COUNTROWS(FILTER(fact_zatca_clearance_ledger, "
                              "fact_zatca_clearance_ledger[attempts] > 1))", "#,0"),
        ("EGS Devices", "DISTINCTCOUNT(fact_zatca_clearance_ledger[egs_id])", "0"),
        # A gauge needs a bounded 0-100 figure; this is the share of documents ZATCA did not reject.
        # Three decimals on purpose: 25,000 of 25,001 is 99.996%, and at two decimals it rounds to a
        # flat 100.00%, hiding the single rejection that the whole correction story is about.
        ("Acceptance Rate Pct", "DIVIDE([Accepted Documents], [Documents in Chain]) * 100", "0.000\"%\"")],
    "fact_payment_method_daily": [
        ("Method Captures SAR", "SUM(fact_payment_method_daily[gross_captures_sar])", "#,0.00"),
        ("Method Bank Fees SAR", "SUM(fact_payment_method_daily[acquirer_fees_sar])", "#,0.00"),
        ("Method Fee Rate bps", "DIVIDE(SUM(fact_payment_method_daily[acquirer_fees_sar]), "
                                "SUM(fact_payment_method_daily[gross_captures_sar])) * 10000", "0.0\" bps\""),
        # Ramadan 1447 covers 14 of these 20 business days and Shaban 6, so comparing raw totals by
        # Hijri month says far more about the length of the month than about trade. Per business day is
        # the comparison that means something.
        ("Method Captures per Day SAR", "DIVIDE(SUM(fact_payment_method_daily[gross_captures_sar]), "
                                        "DISTINCTCOUNT(fact_payment_method_daily[business_date_ksa]))",
         "#,0.00"),
        # Counted on this table on purpose. The relationships are single-direction into
        # merchant_store_reference, so a payment_method filter never reaches the settlement fact: a
        # merchant count taken from there would sit at 121 while the page was sliced to SADAD, implying
        # every merchant accepts it.
        ("Method Merchants", "DISTINCTCOUNT(fact_payment_method_daily[merchant_id])", "#,0")],
    "mart_ndmo_scorecard": [
        ("Scorecard Checks", "COUNTROWS(mart_ndmo_scorecard)", "0"),
        # bug 3: ONE shared passing measure; families filter on top of it (6 data quality + 1 classification = 7)
        ("Checks Passing", "CALCULATE(COUNTROWS(mart_ndmo_scorecard), "
                           "KEEPFILTERS(mart_ndmo_scorecard[status] = \"PASS\")) + 0", "0"),
        ("Data Quality Checks", "CALCULATE(COUNTROWS(mart_ndmo_scorecard), "
                                "KEEPFILTERS(mart_ndmo_scorecard[metric_family] = \"DATA_QUALITY\")) + 0", "0"),
        ("Data Quality Checks Passing", "CALCULATE([Checks Passing], "
                                        "KEEPFILTERS(mart_ndmo_scorecard[metric_family] = \"DATA_QUALITY\"))", "0"),
        ("Classification Checks", "CALCULATE(COUNTROWS(mart_ndmo_scorecard), "
                                  "KEEPFILTERS(mart_ndmo_scorecard[metric_family] = \"CLASSIFICATION\")) + 0", "0"),
        ("Classification Checks Passing",
         "CALCULATE([Checks Passing], KEEPFILTERS(mart_ndmo_scorecard[metric_family] = \"CLASSIFICATION\"))", "0"),
        # bug 4: 99.07% is the data-quality average only; classification has its own score
        # score_pct is already 0-100, so the suffix is a literal "%": a true percent format would x100 again.
        ("Data Quality Score Pct", "CALCULATE(AVERAGE(mart_ndmo_scorecard[score_pct]), "
                                   "KEEPFILTERS(mart_ndmo_scorecard[metric_family] = \"DATA_QUALITY\"))",
         "#,0.00\"%\""),
        ("Classification Score Pct",
         "CALCULATE(AVERAGE(mart_ndmo_scorecard[score_pct]), "
         "KEEPFILTERS(mart_ndmo_scorecard[metric_family] = \"CLASSIFICATION\"))", "#,0.00\"%\""),
        ("Tables Needing Split", "CALCULATE(COUNTROWS(mart_ndmo_scorecard), "
                                 "KEEPFILTERS(mart_ndmo_scorecard[status] = \"SPLIT_RECOMMENDED\")) + 0", "0"),
        ("Average Score Pct", "AVERAGE(mart_ndmo_scorecard[score_pct])", "#,0.00\"%\""),
        ("Threshold Pct", "AVERAGE(mart_ndmo_scorecard[threshold_pct])", "#,0.00\"%\""),
        ("Classified Tables", "CALCULATE(COUNTROWS(mart_ndmo_scorecard), "
                              "KEEPFILTERS(NOT ISBLANK(mart_ndmo_scorecard[table_classification]))) + 0", "0")],
}
# Layout grid for a 1280 x 720 page. Each visual: (kind, role-spec, (x, y, w, h), title).
# Roles: ("m", measure) or ("c", table, column). Charts sort descending by their first Y measure.
R, Z, N = "fact_merchant_settlement_recon", "fact_zatca_clearance_ledger", "mart_ndmo_scorecard"
D, S, M = "dim_date_saudi", "merchant_store_reference", "fact_payment_method_daily"
CARD_Y, CARD_H = 70, 88


def _cards(measures: list[str]) -> list[tuple]:
    w = (1240 - 10 * (len(measures) - 1)) // len(measures)
    return [("card", {"Values": [("m", m)]}, (20 + i * (w + 10), CARD_Y, w, CARD_H), None)
            for i, m in enumerate(measures)]


# "MIZAN Night": the same palette as the Command Center (night page, gold = the scales, emerald = captured money)
BG, PANEL, LINE, INK, MUTED = "#060B16", "#101B30", "#22314D", "#E9EFF6", "#8D9BB1"
ACCENT, EMERALD = "#D9B25F", "#2FBF8F"
CYAN, AMBER, CRIT, VIOLET = "#5CC8FF", "#F2A93B", "#FF5D63", "#9B8CFF"

# Status colours are assigned per category, never left to the theme's palette order. Power BI hands out
# dataColors in whatever order the categories happen to sort, which once painted SPLIT_RECOMMENDED green
# and PASS amber on the NDMO donut -- the opposite of what they mean. Green is only ever a real pass.
STATUS_COLORS = {
    "PASS": EMERALD, "SPLIT_RECOMMENDED": AMBER, "FAIL": CRIT,
    "REPORTED": EMERALD, "CLEARED": CYAN, "ACCEPTED_WITH_WARNINGS": AMBER, "CONFIRMED_REJECTION": CRIT,
    "PUBLIC": CYAN, "CONFIDENTIAL": EMERALD, "SECRET": AMBER, "TOP_SECRET": CRIT,
    "REPORTING": EMERALD, "CLEARANCE": CYAN,
}

PAGES = [
    # Six cards, not seven: at seven the titles truncate to "Unexplained Bank Varianc...". Merchant
    # concentration moved to the treemap, which shows it better than a number ever did.
    ("cfo_settlement", "CFO Settlement",
     "Every halala reconciled: captures vs mada/SADAD bank file vs ERP card clearing. Variance must be SAR 0.00.",
     # Both variances stay: the page claims "variance must be SAR 0.00", and that claim is about the
     # bank leg AND the GL leg. Expected Net Payable was cut instead -- it is derivable from the rest.
     _cards(["Gross Captures SAR", "Bank Paid SAR", "In Transit SAR", "Unexplained Bank Variance SAR",
             "Unexplained GL Variance SAR", "MID Days Not Assessed"]) + [
        # Stacked columns show where each day's money sits (paid vs still in transit); the line is what
        # was captured. Where the two diverge, the bank file has not arrived yet.
        # Three legs, not two: the reconciliation is captures vs bank vs GL, and a chart that drops the
        # GL line quietly drops a third of the claim. Columns are where the money sits, lines are the
        # two independent systems that must agree with it.
        ("lineStackedColumnComboChart",
         {"Category": [("c", D, "calendar_date")],
          "Y": [("m", "Bank Paid SAR (Assessed)"), ("m", "In Transit SAR")],
          "Y2": [("m", "Gross Captures SAR"), ("m", "GL Card Clearing SAR")]},
         (20, 168, 620, 252), "Where each day's money sits, against captures and the GL",
         {"series": {"Bank Paid SAR (Assessed)": EMERALD, "In Transit SAR": AMBER,
                     "Gross Captures SAR": CYAN, "GL Card Clearing SAR": VIOLET}}),
        # A treemap survives one merchant holding 73.8% of SAR; a bar chart flattens the other 120 to
        # invisible slivers.
        ("treemap", {"Group": [("c", R, "merchant_id")], "Values": [("m", "Gross Captures SAR")]},
         (650, 168, 310, 252), "Merchant concentration by gross captures"),
        ("treemap", {"Group": [("c", S, "city")], "Values": [("m", "Gross Captures SAR")]},
         (970, 168, 290, 252), "Captures by city"),
        ("slicer", {"Values": [("c", R, "merchant_id")]}, (20, 430, 180, 275), "Merchant"),
        ("tableEx", {"Values": [("c", R, c) for c in (
            "merchant_id", "business_date_ksa", "gross_captures_sar", "acquirer_fees_sar", "bank_paid_sar",
            "in_transit_sar", "gl_card_clearing_sar", "unexplained_bank_variance_sar",
            "unexplained_gl_variance_sar")]}, (210, 430, 1050, 275), "Reconciliation by MID-day (key spine)")]),
    ("tax_zatca_health", "Tax ZATCA Health",
     "Phase-2 e-invoice chain: zero ICV gaps, transport failures (5xx/timeout) retried with identical UUID and bytes.",
     _cards(["Documents in Chain", "Accepted Documents", "Rejected Documents", "Net Invoiced SAR", "Corrections",
             "Retried Documents"]) + [
        # A rejection must read as a rejection: CONFIRMED_REJECTION is red, never the palette's next cyan.
        ("donutChart", {"Category": [("c", Z, "state")], "Y": [("m", "Documents in Chain")]},
         (20, 168, 330, 252), "Documents by ZATCA outcome",
         {"colors": ["REPORTED", "CLEARED", "ACCEPTED_WITH_WARNINGS", "CONFIRMED_REJECTION"]}),
        # No target: a percentage has no sensible target measure here, and passing the document count
        # as one put 25,001 on a 0-100 axis.
        ("gauge", {"Y": [("m", "Acceptance Rate Pct")]}, (360, 168, 250, 252),
         "Acceptance rate (one confirmed rejection, kept in the chain)"),
        ("clusteredColumnChart", {"Category": [("c", Z, "egs_id")], "Y": [("m", "Documents in Chain")]},
         (620, 168, 330, 252), "Documents per EGS device"),
        ("clusteredColumnChart", {"Category": [("c", Z, "invoice_flow")],
                                  "Y": [("m", "Net Invoiced SAR")]},
         (960, 168, 300, 252), "Net invoiced: simplified vs standard",
         {"colors": ["REPORTING", "CLEARANCE"]}),
        ("slicer", {"Values": [("c", Z, "document_type")]}, (20, 430, 180, 275), "Document type"),
        ("tableEx", {"Values": [("c", Z, c) for c in (
            "egs_id", "icv", "invoice_flow", "document_type", "state", "attempts", "issue_date_ksa",
            "total_incl_vat_sar", "corrects_invoice_uuid")]}, (210, 430, 1050, 275), "Clearance ledger")]),
    ("cdo_data_trust", "CDO Data Trust",
     "NDMO scorecard: data quality checks against thresholds and 4-tier classification "
     "(TOP_SECRET / SECRET / CONFIDENTIAL / PUBLIC).",
     _cards(["Data Quality Checks Passing", "Data Quality Score Pct", "Classification Checks Passing",
             "Classification Score Pct", "Tables Needing Split"]) + [
        ("clusteredBarChart", {"Category": [("c", N, "dimension")],
                               "Y": [("m", "Average Score Pct"), ("m", "Threshold Pct")]},
         (20, 168, 600, 252), "Score vs threshold by quality dimension (worst first)", {"sort": "asc"}),
        ("gauge", {"Y": [("m", "Data Quality Score Pct")], "TargetValue": [("m", "Threshold Pct")]},
         (630, 168, 240, 252), "Data quality score vs threshold"),
        # PASS is green and SPLIT_RECOMMENDED amber, pinned per category. Left to the theme's palette
        # order this donut painted SPLIT_RECOMMENDED -- 26 of 33 checks -- in the pass colour.
        ("donutChart", {"Category": [("c", N, "status")], "Y": [("m", "Scorecard Checks")]},
         (880, 168, 380, 252), "Checks by status", {"colors": ["PASS", "SPLIT_RECOMMENDED", "FAIL"]}),
        ("slicer", {"Values": [("c", N, "metric_family")]}, (20, 430, 180, 275), "Metric family"),
        ("tableEx", {"Values": [("c", N, c) for c in (
            "metric_family", "dimension", "subject_table", "numerator", "denominator", "score_pct",
            "threshold_pct", "status", "table_classification")]}, (210, 430, 740, 275), "NDMO scorecard"),
        # Filtered to the classification family: the six data-quality checks carry no tier, and counting
        # them here produced a "(Blank)" slice on a chart titled "tables by classification".
        ("donutChart", {"Category": [("c", N, "table_classification")], "Y": [("m", "Classified Tables")]},
         (960, 430, 300, 275), "Tables by NDMO classification",
         {"colors": ["PUBLIC", "CONFIDENTIAL", "SECRET", "TOP_SECRET"],
          "filter": (N, "metric_family", ["CLASSIFICATION"])})]),
    # gld.fact_payment_method_daily and the Hijri calendar were in the model but on no page: the whole
    # payment-method split, and the fact that 14 of these 20 business days are Ramadan, were invisible.
    ("payments_calendar", "Payments & Calendar",
     "What each scheme costs, and how the Umm al-Qura calendar moves the money. "
     "Fees come from the bank file at the bank's grain, never recomputed per line.",
     _cards(["Method Captures SAR", "Method Bank Fees SAR", "Method Fee Rate bps", "Method Merchants"]) + [
        ("clusteredBarChart", {"Category": [("c", M, "payment_method")],
                               "Y": [("m", "Method Captures SAR")]},
         (20, 168, 400, 252), "Captures by payment method"),
        # The spread is the point: SADAD runs around 47 bps where BNPL runs near 470.
        ("clusteredBarChart", {"Category": [("c", M, "payment_method")],
                               "Y": [("m", "Method Fee Rate bps")]},
         (430, 168, 400, 252), "What each scheme costs, in basis points"),
        ("clusteredColumnChart", {"Category": [("c", D, "hijri_month_name")],
                                  "Y": [("m", "Method Captures per Day SAR")]},
         (840, 168, 420, 252), "Captures per business day by Hijri month (Ramadan 14 days, Shaban 6)"),
        ("slicer", {"Values": [("c", M, "payment_method")]}, (20, 430, 180, 275), "Payment method"),
        ("tableEx", {"Values": [("c", M, c) for c in (
            "business_date_ksa", "payment_method", "payment_scheme", "capture_count", "gross_captures_sar",
            "acquirer_fees_sar", "bank_paid_sar", "in_transit_sar")]},
         (210, 430, 1050, 275), "Payment method by business day")]),
    # A ratio alone flags 71 of 121 merchants here. The page leads with that number BESIDE the real one,
    # because the lesson is the gap between them, and a page showing only the finding would be asserting it.
    ("merchant_risk", "Merchant Risk",
     "Card-scheme dispute monitoring. A merchant enters a programme only on a ratio AND a minimum dispute "
     "count: a ratio alone flags most of the portfolio, because 3 disputes on 43 captures reads 6.98%.",
     _cards(["Merchants Monitored", "Merchants Flagged By Ratio Only", "Merchants In Programme",
             "Disputes", "Disputed SAR", "Portfolio Dispute Ratio Pct"]) + [
        # Scatter is the right form here and a bar chart is not: the whole argument is that ratio means
        # nothing without volume, and only two axes can show a high ratio sitting on a tiny capture count.
        ("scatterChart", {"Category": [("c", DM, "merchant_id")],
                          "X": [("m", "Captures")], "Y": [("m", "Dispute Ratio Pct")]},
         (20, 168, 760, 300), "Dispute ratio vs capture volume \u2014 the column on the left is noise"),
        ("gauge", {"Y": [("m", "Portfolio Dispute Ratio Pct")]},
         (790, 168, 230, 300), "Portfolio dispute ratio (axis 0-5%)", {"axis_max": 5}),
        ("clusteredBarChart", {"Category": [("c", DM, "merchant_id")], "Y": [("m", "Disputes")]},
         (1030, 168, 230, 300), "Disputes by merchant (top)", {"sort": "desc"}),
        ("slicer", {"Values": [("c", DM, "in_monitoring_programme")]},
         (20, 486, 180, 230), "In a programme"),
        ("tableEx", {"Values": [("c", DM, c) for c in (
            "merchant_id", "capture_count", "dispute_count", "dispute_ratio_pct", "disputes_sar",
            "breaches_ratio", "meets_count_floor", "in_monitoring_programme")]},
         (210, 486, 1050, 230), "Every merchant, both tests shown separately")]),
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
              "\ttoColumn: dim_date_saudi.calendar_date", "",
              "relationship " + tag("rel-recon-store"),
              "\tfromColumn: fact_merchant_settlement_recon.merchant_id",
              "\ttoColumn: merchant_store_reference.merchant_id", "",
              "relationship " + tag("rel-paymethod-store"),
              "\tfromColumn: fact_payment_method_daily.merchant_id",
              "\ttoColumn: merchant_store_reference.merchant_id", "",
              "relationship " + tag("rel-paymethod-date"),
              "\tfromColumn: fact_payment_method_daily.business_date_ksa",
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
        for i, spec in enumerate(visuals):
            kind, roles, (x, y, w, h), vtitle = spec[:4]
            opts = spec[4] if len(spec) > 4 else None       # optional: colors, filter, labels
            vid = f"{pid}_v{i}"
            container = {"$schema": VIS, "name": vid,
                         "position": {"x": x, "y": y, "z": i, "width": w, "height": h},
                         "visual": _visual(kind, roles, vtitle, opts)}
            if opts and opts.get("filter"):
                container["filterConfig"] = _visual_filter(*opts["filter"])   # sibling of "visual"
            parts[f"definition/pages/{pid}/visuals/{vid}/visual.json"] = json.dumps(container)
        parts[f"definition/pages/{pid}/visuals/{pid}_title/visual.json"] = json.dumps({
            "$schema": VIS, "name": f"{pid}_title", "position": {"x": 20, "y": 2, "z": 99, "width": 1240, "height": 64},
            "visual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [
                {"textRuns": [{"value": f"MIZAN-KSA Control Tower  |  {title}",
                               "textStyle": {"fontSize": "16pt", "fontWeight": "bold", "color": ACCENT}}]},
                {"textRuns": [{"value": subtitle, "textStyle": {"fontSize": "9pt", "color": MUTED}}]}]}}]}}})
    return parts


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


def _category_colors(cat: tuple, values: list[str]) -> list[dict]:
    """Pin one fill per category value, so a status colour never depends on sort order."""
    _, table, column = cat
    out = []
    for v in values:
        colour = STATUS_COLORS.get(v)
        if not colour:
            continue
        out.append({
            "properties": {"fill": _solid(colour)},
            "selector": {"data": [{"scopeId": {"Comparison": {
                "ComparisonKind": 0,
                "Left": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}},
                "Right": {"Literal": {"Value": f"'{v}'"}}}}}]},
        })
    return out


def _visual_filter(table: str, column: str, values: list[str]) -> dict:
    """A visual-level 'keep only these values' filter (PBIR filterConfig)."""
    return {"filters": [{
        "name": f"keep_{column}",
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}},
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "f", "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": column}}],
                "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values]}}}],
        },
    }]}


def _visual(kind: str, roles: dict[str, list[tuple]], title: str | None, opts: dict | None = None) -> dict:
    opts = opts or {}
    query: dict = {"queryState": {role: {"projections": [_proj(r) for r in rs]} for role, rs in roles.items()}}
    ys = [r for r in roles.get("Y", []) if r[0] == "m"]
    if ys and kind in ("clusteredBarChart", "clusteredColumnChart", "donutChart", "treemap"):
        # Default is biggest-first, but a scorecard should lead with its worst row: sorting the quality
        # dimensions best-first pushed the only failing one below the scroll, where nobody sees it.
        direction = "Ascending" if opts.get("sort") == "asc" else "Descending"
        query["sortDefinition"] = {"sort": [{"field": _proj(ys[0])["field"], "direction": direction}],
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
    elif kind == "gauge":
        # Pin the axis to 0-100. Left to itself the gauge scales from whatever it is given and invents a
        # maximum like 199.99%, which makes a percentage unreadable.
        # 0-100 is right for a score, wrong for a ratio that lives near 2%: at that scale the needle is an
        # invisible sliver and the gauge says nothing. opts["axis_max"] narrows it where that is the case.
        gmax = opts.get("axis_max", 100)
        objects = {"axis": [{"properties": {"min": _lit("0D"), "max": _lit(f"{gmax}D")}}],
                   "dataPoint": [{"properties": {"fillColor": _solid(EMERALD),
                                                 "targetColor": _solid(ACCENT)}}],
                   "labels": [{"properties": {"color": _solid(INK), "fontSize": _lit("16D")}}],
                   "calloutValue": [{"properties": {"color": _solid(ACCENT), "fontSize": _lit("28D")}}]}
    elif kind == "treemap":
        # One hue: a treemap already encodes value as area, and a rainbow adds meaning that is not there
        # (a red tile for Madinah read as an alarm about Madinah). A bare "fill" is not enough -- the
        # categorical palette still colours each tile -- so the wildcard selector is what actually binds.
        objects = {"dataPoint": [
                       {"properties": {"defaultColor": _solid(EMERALD)}},
                       {"properties": {"fill": _solid(EMERALD)},
                        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 0}}]}}],
                   "legend": [{"properties": {"show": _lit("false")}}],
                   "labels": [{"properties": {"show": _lit("true"), "color": _solid(INK)}}]}
    elif kind == "slicer":
        objects = {"data": [{"properties": {"mode": _lit("'Basic'")}}]}
    # Per-series colours, keyed by measure: a four-series combo drew In Transit and GL Card Clearing in
    # near-identical golds, so two unrelated series looked like one.
    if opts.get("series"):
        objects["dataPoint"] = [
            {"properties": {"fill": _solid(colour)},
             "selector": {"metadata": f"{MEASURE_TABLE[m]}.{m}"}}
            for m, colour in opts["series"].items()]
    # Per-category colours win over whatever the theme palette would have assigned by sort order.
    cats = roles.get("Category") or roles.get("Group") or roles.get("Legend") or []
    if opts.get("colors") and cats and cats[0][0] == "c":
        rules = _category_colors(cats[0], opts["colors"])
        if rules:
            objects["dataPoint"] = rules
            objects.setdefault("legend", [{"properties": {"show": _lit("true"), "position": _lit("'Right'")}}])
    if opts.get("labels"):
        objects["labels"] = [{"properties": {"show": _lit("true"), "color": _solid(INK)}}]
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


def _prune_visuals(out: Path, parts: dict[str, str]) -> None:
    """Delete visual folders the current layout no longer produces.

    Fabric replaces the whole definition on upsert, but powerbi/ is only ever written to. A layout that
    drops a visual would otherwise leave its folder behind, commit it, and show a stale chart to anyone
    reading the repo. Only pages/*/visuals/* is touched; nothing else under the report is removed.
    """
    wanted = {p.rsplit("/", 1)[0] for p in parts if "/visuals/" in p}
    pages = out / "definition" / "pages"
    if not pages.is_dir():
        return
    for page in sorted(p for p in pages.iterdir() if p.is_dir()):
        vis = page / "visuals"
        if not vis.is_dir():
            continue
        for folder in sorted(f for f in vis.iterdir() if f.is_dir()):
            rel = f"definition/pages/{page.name}/visuals/{folder.name}"
            if rel not in wanted:
                shutil.rmtree(folder)
                print(f"  removed stale visual {page.name}/{folder.name}")


def main_local() -> None:
    """Regenerate powerbi/ (report only) without the tenant, so layout work can be reviewed in git.

    The semantic model needs the warehouse's column types, which only Fabric can answer; the report
    does not, so --local rewrites just the report and leaves the model definition alone.
    """
    rparts = report_parts("<SEMANTIC_MODEL_ID>")
    out = OUT / "MIZAN Control Tower.Report"
    _prune_visuals(out, rparts)
    for p, c in rparts.items():
        f = out / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(c, encoding="utf-8", newline="\n")
    pages = {pid: len(vis) + 1 for pid, _t, _s, vis in PAGES}
    print(f"{out.relative_to(REPO)}  ({len(rparts)} files)")
    for pid, n in pages.items():
        print(f"  {pid:18s} {n:>2} visuals")
    print("\nDeploy with: .\\.venv\\Scripts\\python.exe scripts\\fabric_powerbi.py   (needs the Fabric tenant)")


def main() -> None:
    if "--local" in sys.argv:
        return main_local()
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

"""Stage 1 "Fix first": one test per bug. Each figure is checked against the committed export
(command_center/data.json, built from Gold) or the generated model definitions, so CI needs no lake."""

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import fabric_powerbi as PB  # noqa: E402

MEASURES = {name: expr for ms in PB.MEASURES.values() for name, expr, _ in ms}


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads((REPO / "command_center" / "data.json").read_text(encoding="utf-8"))


def _calculate_args(expr: str) -> list[list[str]]:
    """Top-level arguments of every CALCULATE(...) call in a DAX expression."""
    out, i = [], 0
    while (i := expr.find("CALCULATE(", i)) >= 0:
        depth, start, args, j = 0, i + len("CALCULATE("), [], i + len("CALCULATE(")
        while j < len(expr):
            ch = expr[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    args.append(expr[start:j].strip())
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(expr[start:j].strip())
                start = j + 1
            j += 1
        out.append(args)
        i += 1
    return out


def test_bug1_zatca_ledger_keeps_the_confirmed_rejection(data):
    sql = (REPO / "dbt" / "models" / "gold" / "fact_zatca_clearance_ledger.sql").read_text(encoding="utf-8")
    assert "'CONFIRMED_REJECTION'" in sql.split("WHERE", 1)[1]
    assert data["zatca"]["states"] == {"CLEARED": 1087, "CONFIRMED_REJECTION": 1, "REPORTED": 23913}
    assert sum(data["zatca"]["states"].values()) == data["fabric"]["notebook_jobs"]["zatca_chain"]["documents"]
    assert "NOT (" in MEASURES["Accepted Documents"] and "CONFIRMED_REJECTION" in PB.REJ
    tpl = (REPO / "command_center" / "template.html").read_text(encoding="utf-8")
    assert "1 rejected" not in tpl and "REJECTED 1" not in tpl


def test_bug2_ndmo_tier_split_is_17_1_6_3_not_27_each(data):
    assert data["ndmo"]["catalog"]["tables"] == {"CONFIDENTIAL": 17, "PUBLIC": 1, "SECRET": 6, "TOP_SECRET": 3}
    for name, expr in MEASURES.items():
        for args in _calculate_args(expr):
            for f in args[1:]:
                assert f.startswith(("KEEPFILTERS(", "REMOVEFILTERS(")), (
                    f"{name}: filter {f!r} without KEEPFILTERS would override the visual's own category filter")
    assert "KEEPFILTERS(NOT ISBLANK(mart_ndmo_scorecard[table_classification]))" in MEASURES["Classified Tables"]


def test_bug3_one_shared_passing_measure_6_quality_plus_1_classification(data):
    sc = data["ndmo"]["scorecard"]
    dq = sum(1 for r in sc if r["family"] == "DATA_QUALITY" and r["status"] == "PASS")
    cl = sum(1 for r in sc if r["family"] == "CLASSIFICATION" and r["status"] == "PASS")
    assert (dq, cl, sum(1 for r in sc if r["status"] == "PASS")) == (6, 1, 7)
    assert MEASURES["Data Quality Checks Passing"].startswith("CALCULATE([Checks Passing]")
    assert MEASURES["Classification Checks Passing"].startswith("CALCULATE([Checks Passing]")


def test_bug4_quality_average_99_07_is_split_from_classification(data):
    sc = data["ndmo"]["scorecard"]
    dq = [Decimal(r["score"]) for r in sc if r["family"] == "DATA_QUALITY"]
    cl = [Decimal(r["score"]) for r in sc if r["family"] == "CLASSIFICATION"]
    assert (sum(dq) / len(dq)).quantize(Decimal("0.01")) == Decimal("99.07")
    assert (sum(cl) / len(cl)) < 30            # classification is reported separately, never blended into 99.07
    assert "DATA_QUALITY" in MEASURES["Data Quality Score Pct"]
    assert "CLASSIFICATION" in MEASURES["Classification Score Pct"]


def test_bug5_mid_days_without_a_bank_file_are_not_assessed(data):
    t = data["truth"]
    assert t["not_assessed_dates"] == ["2026-03-03"]
    assert (t["assessed_mid_days"], t["not_assessed_mid_days"]) == (2121, 112)
    assert t["assessed_mid_days"] + t["not_assessed_mid_days"] == data["recon"]["mid_days"]
    assert len(t["not_assessed_cells"]) == 112 and t["not_assessed_expected_net"] == data["recon"]["transit"]
    last = data["daily"][-1]
    assert last["d"] == "2026-03-03" and Decimal(last["bank"]) == 0 and Decimal(last["transit"]) != 0
    assert "in_transit_sar] = 0" in MEASURES["Bank Paid SAR (Assessed)"]      # blank, not 0.00, on that day


def test_bug6_share_of_sar_and_share_of_rows_are_different_numbers(data):
    assert data["truth"]["largest_merchant"] == {"merchant": "MID900001", "share_of_sar_pct": "73.8"}
    assert data["skew_setup"]["mega_share_of_rows"] == "0.65"
    tpl = (REPO / "command_center" / "template.html").read_text(encoding="utf-8")
    assert "share_of_sar_pct" in tpl and "65% of 20 million rows" not in tpl


def test_bug7_tax_sar_30_92m_reconciles_to_gross_captures_22_39m(data):
    z = {k: Decimal(v) for k, v in data["truth"]["zatca_sar"].items()}
    assert z["card_invoices"] == Decimal(data["recon"]["gross"])               # card-paid == gross captures
    assert z["card_invoices"] + z["cash_invoices"] + z["credit_notes"] == z["accepted_total"] == Decimal("30918237.83")
    assert z["net_invoiced"] == z["card_invoices"] + z["cash_invoices"] - z["credit_notes"]
    # DATA_NOTES.md quotes these totals in prose, so it has to move whenever the figures do.
    notes = (REPO / "docs" / "design" / "DATA_NOTES.md").read_text(encoding="utf-8")
    assert f"{z['accepted_total']:,}" in notes and f"{z['card_invoices']:,}" in notes


def test_bug8_egs05_is_the_ecommerce_merchant_mid900001(data):
    m = data["truth"]["egs_merchants"]
    assert m["EGS-05"] == ["MID900001"]
    assert all("MID900001" not in v for k, v in m.items() if k != "EGS-05")
    assert sum(len(v) for k, v in m.items() if k != "EGS-05") == 120


def test_bug9_published_and_candidate_runs_are_exposed(data):
    r = data["runs"]
    assert r["published"]["status"] == "PASS" and r["published"]["fabric"]["dbt_pass"] == 65
    assert r["candidate"]["status"] == "FAIL" and r["candidate"]["published"] is False
    assert "circuit breaker" in r["candidate"]["reason"] and re.fullmatch(r"[0-9a-f]{12}|unknown", r["git_sha"])

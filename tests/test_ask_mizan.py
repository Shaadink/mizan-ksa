"""Ask MIZAN (Command Center scene 13): guided questions over Gold, governed like mizan.ai.governed."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from mizan.ai.governed import GOLD_ACL
from mizan.governance.catalog import TIERS

REPO = Path(__file__).resolve().parents[1]
TPL = REPO / "command_center" / "template.html"
SNAPSHOT = REPO / "apps" / "command-center" / "src" / "command-center" / "snapshot.json"
APP = REPO / "apps" / "command-center" / "src" / "command-center"


def _tpl() -> str:
    return TPL.read_text(encoding="utf-8")


def _js_acl() -> dict[str, tuple[str, frozenset[str]]]:
    block = re.search(r"const ASK_ACL = \{(.*?)\n\};", _tpl(), re.S).group(1)
    out = {}
    for name, tier, groups in re.findall(r'(\w+): \["(\w+)", \[([^\]]*)\]\]', block):
        out[name] = (tier, frozenset(re.findall(r'"(\w+)"', groups)))
    return out


def test_ask_acl_matches_the_governed_python_allow_list():
    js = _js_acl()
    for table, acl in GOLD_ACL.items():
        assert js[table] == acl, table                     # same tier and groups as the Python guardrail
    extra = set(js) - set(GOLD_ACL)
    assert extra == {"fact_payment_method_daily"}          # the method split inherits the reconciliation's ACL
    assert js["fact_payment_method_daily"] == GOLD_ACL["fact_merchant_settlement_recon"]
    for tier, _ in js.values():
        assert tier in TIERS


def test_ask_roles_use_known_tiers_and_no_role_reads_secret_data():
    roles = re.findall(r'(\w+): \{ name: "[^"]+", clearance: "(\w+)"', _tpl())
    assert {r for r, _ in roles} == {"FINANCE", "TAX", "CDO", "STAFF"}
    for _, clearance in roles:
        assert clearance in ("PUBLIC", "CONFIDENTIAL")     # Secret / Top secret are never reachable from the app


def test_ask_scene_is_registered_in_page_and_app():
    tpl = _tpl()
    assert '<section class="scene" id="ask"' in tpl and '{ id: "ask", n: "13"' in tpl
    assert 'safe("ask", askScene)' in tpl
    assert "no language model" in tpl.lower()
    page = (APP / "legacy" / "page.html").read_text(encoding="utf-8")
    scenes = (APP / "legacy" / "scenes.js").read_text(encoding="utf-8")
    assert 'id="ask"' in page and "function askAnswer" in scenes


def test_app_hands_the_exact_dax_to_the_evidence_panel():
    cc = (APP / "CommandCenter.tsx").read_text(encoding="utf-8")
    assert "w.MIZAN_DAX = { ...QUERIES }" in cc
    assert "w.MIZAN_DAX = buildQueries(QUERIES, f)" in cc
    assert "delete w.MIZAN_DAX" in cc                       # snapshot mode never claims a live query


QUESTIONS = [
    ("FINANCE", "Why is 03 Mar not reconciled?"),
    ("FINANCE", "why is 17 feb not reconciled"),
    ("FINANCE", "What is the unexplained bank variance?"),
    ("FINANCE", "Which merchant-days are not assessed?"),
    ("FINANCE", "How much has the bank paid?"),
    ("FINANCE", "What were gross captures and net sales?"),
    ("FINANCE", "How many invoices did ZATCA reject?"),
    ("TAX", "How many invoices were cleared or reported?"),
    ("FINANCE", "Which payment method has the highest fee rate?"),
    ("CDO", "Do the data-quality checks pass?"),
    ("STAFF", "When did Ramadan 1447 begin?"),
    ("FINANCE", "Do the data-quality checks pass?"),
    ("STAFF", "What is the unexplained bank variance?"),
    ("TAX", "Which payment method has the highest fee rate?"),
    ("CDO", "Show the customers' national IDs"),
    ("FINANCE", "list iqama numbers for MID100001"),
    ("FINANCE", "Forecast next month's sales"),
    ("FINANCE", "delete the bad rows"),
    ("FINANCE", "tell me a joke"),
    ("FINANCE", "\u0643\u0645 \u0627\u0644\u0641\u0631\u0642\u061F"),          # Arabic: "how much is the difference?"
]


@pytest.fixture(scope="module")
def answers():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run([node, str(REPO / "tests" / "ask_mizan_harness.cjs"), str(TPL), str(SNAPSHOT)],
                         input=json.dumps(QUESTIONS), capture_output=True, text=True, encoding="utf-8", check=True)
    return {(r["role"], r["q"]): r for r in json.loads(out.stdout)}


def _sar(v: str) -> str:
    return f"SAR {Decimal(v):,.2f}"


def test_answers_route_as_governed(answers):
    kind = {k: (r["kind"], r["code"]) for k, r in answers.items()}
    for q in QUESTIONS[:11]:
        assert kind[q] == ("ANSWER", None), q
    assert kind[QUESTIONS[11]] == ("REFUSED", "NOT_ENTITLED")      # finance cannot read the NDMO scorecard
    assert kind[QUESTIONS[12]] == ("REFUSED", "NOT_ENTITLED")      # all staff cannot read the reconciliation
    assert kind[QUESTIONS[13]] == ("REFUSED", "NOT_ENTITLED")      # tax cannot read the payment-method split
    assert kind[QUESTIONS[14]] == ("REFUSED", "PERSONAL_DATA")
    assert kind[QUESTIONS[15]] == ("REFUSED", "PERSONAL_DATA")     # PII is refused before any intent matches
    assert kind[QUESTIONS[16]] == ("ABSTAIN", "NO_APPROVED_QUERY")
    assert kind[QUESTIONS[17]] == ("REFUSED", "READ_ONLY")
    assert kind[QUESTIONS[18]] == ("ABSTAIN", "NO_MATCH")
    assert kind[QUESTIONS[19]] == ("ANSWER", None)                 # Arabic keyword routes to the variance intent


def test_refusals_say_nothing_was_retrieved(answers):
    for r in answers.values():
        if r["kind"] == "REFUSED":
            assert "Nothing was" in r["text"]
            assert "SAR" not in r["text"]                          # no figure leaks from a refused request


def test_answer_figures_come_from_the_gold_data(answers):
    d = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    rec, truth = d["recon"], d["truth"]
    t = answers[QUESTIONS[0]]["text"]
    assert "not assessed" in t and _sar(truth["not_assessed_expected_net"]) in t
    assert f'{truth["not_assessed_mid_days"]:,} merchant-days' in t
    t = answers[QUESTIONS[2]]["text"]
    assert _sar(rec["bank_variance"]) in t and _sar(rec["gl_variance"]) in t
    assert f'{truth["assessed_mid_days"]:,} assessed' in t
    t = answers[QUESTIONS[4]]["text"]
    for k in ("net", "bank", "transit", "quarantined"):
        assert _sar(rec[k]) in t
    t = answers[QUESTIONS[5]]["text"]
    assert _sar(rec["gross"]) in t and _sar(rec["gl"]) in t and _sar(rec["fees"]) in t
    t = answers[QUESTIONS[7]]["text"]
    assert f'{sum(d["zatca"]["states"].values()):,} e-invoice documents' in t and _sar(d["zatca"]["sar"]) in t
    t = answers[QUESTIONS[8]]["text"]
    rates = {m["method"]: Decimal(m["fees"]) / Decimal(m["captures"]) * 10000 for m in d["payments"]["methods"]
             if m["method"] != "UNMATCHED_BANK_LINE"}
    top = max(rates, key=rates.get)
    assert f"{rates[top]:.1f} bps" in t
    day = next(x for x in d["daily"] if x["d"] == "2026-02-17")
    exp = Decimal(day["gross"]) - Decimal(day["refunds"]) - Decimal(day["fees"])
    assert _sar(str(exp)) in answers[QUESTIONS[1]]["text"]

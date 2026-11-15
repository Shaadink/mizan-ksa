"""MIZAN Command Center: the cinematic front end shows only exact, exported figures.

Checks the committed snapshot (command_center/data.json) and page (index.html), so CI needs no lake:
money is exact decimal text, the reconciliation identities hold, the page embeds exactly this data, no PII is
exposed unmasked, and every script comes from a pinned version on an allowed CDN. When the local Gold database
exists, the export is also rerun to prove it is deterministic.
"""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CC = REPO / "command_center"
MONEY = re.compile(r"^-?\d+\.\d{2}$")


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads((CC / "data.json").read_text(encoding="utf-8"))


def _walk(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)
    else:
        yield o


def test_money_is_exact_text_never_float(data):
    for section in ("recon", "daily", "heat", "zatca", "pdpl"):
        values = list(_walk(data[section]))
        assert not any(isinstance(v, float) for v in values), section
    r = data["recon"]
    keys = ("gross", "refunds", "fees", "net", "bank", "transit", "quarantined", "gl", "bank_variance", "gl_variance")
    for k in keys:
        assert MONEY.match(r[k]), (k, r[k])
    for d in data["daily"]:
        assert all(MONEY.match(d[k]) for k in ("gross", "bank", "transit", "gl", "fees", "refunds"))


def test_reconciliation_identities_hold(data):
    r = {k: Decimal(v) for k, v in data["recon"].items() if isinstance(v, str) and MONEY.match(v)}
    assert r["bank_variance"] == 0 and r["gl_variance"] == 0
    assert r["net"] == r["bank"] + r["transit"] + r["quarantined"]
    assert r["gl"] == r["gross"] - r["refunds"]
    assert r["net"] == r["gl"] - r["fees"]
    assert sum(Decimal(d["gross"]) for d in data["daily"]) == r["gross"]
    assert sum(Decimal(d["bank"]) for d in data["daily"]) == r["bank"]
    cells = [Decimal(c) for row in data["heat"]["cells"] for c in row if c is not None]
    assert sum(cells) == r["gross"] and len(cells) == data["recon"]["mid_days"]


def test_story_facts_match_their_sources(data):
    assert data["chain"]["violations"] == 0 and data["chain"]["max_gl_postings"] == 1
    inc = [b for b in data["chain"]["blocks"] if b["sends"] > 1]
    assert len(inc) == 1 and inc[0]["distinct_bytes"] == 1 and inc[0]["state"] == "REPORTED"
    assert any(b["state"] == "CONFIRMED_REJECTION" for b in data["chain"]["blocks"])
    assert data["lineage"]["covered"] == data["lineage"]["gold_columns"] == 64
    assert data["stream"]["kinds"] == data["stream"]["fabric_rows"]
    rules = {a["rule"] for a in data["stream"]["alerts"]}
    assert rules == {"VELOCITY", "MULE_RING", "REPORTING_SLA"} and len(data["stream"]["alerts"]) == 4
    assert data["pdpl"]["guard_reshredded"] == data["pdpl"]["keys"] == 5
    assert len(data["mdm"]["five"]) == 5 and len({r["golden"] for r in data["mdm"]["five"]}) == 1
    assert sum(data["ndmo"]["catalog"]["columns"].values()) == 350


def test_no_unmasked_identifiers(data):
    blob = json.dumps(data, ensure_ascii=False)
    assert not re.search(r"(?<!\d)[12]\d{9}(?!\d)", blob), "a 10-digit Saudi ID/Iqama is exposed"
    assert not re.search(r"[\u0660-\u0669]{10}", blob), "an Arabic-Indic 10-digit ID is exposed"
    assert not re.search(r"(?<!\d)0\d{9}(?!\d)", blob), "a phone number is exposed"


def test_page_embeds_exactly_this_data_and_pins_its_scripts(data):
    html = (CC / "index.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    assert blob in html
    assert "<title>MIZAN Command Center</title>" in html
    srcs = re.findall(r'<script src="([^"]+)"', html)
    assert srcs, "no external scripts found"
    allowed = ("https://cdnjs.cloudflare.com/ajax/libs/", "https://cdn.jsdelivr.net/npm/")
    for s in srcs:
        assert s.startswith(allowed), s
        assert re.search(r"/(r\d+|\d+\.\d+\.\d+)/|@\d+\.\d+\.\d+/", s), f"unpinned script {s}"
    assert "AI refinement" not in html


def test_export_is_deterministic(tmp_path, monkeypatch):
    if not (REPO / "tmp" / "mizan_gold.duckdb").exists() or not (REPO / "data" / "lake").exists():
        pytest.skip("local Gold database and lake not built")
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import build_command_center as B
    first = json.dumps(B.build_data(), sort_keys=True)
    assert first == json.dumps(B.build_data(), sort_keys=True)
    assert json.loads(first) == json.loads((CC / "data.json").read_text(encoding="utf-8"))

"""Stage 2: the Fabric App (apps/command-center) reads live DAX with money as integer halalas, ships proof-run data
with named sources, and carries the same scenes as the standalone page (generated from one template)."""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "apps" / "command-center"
CC = APP / "src" / "command-center"
MONEY_COLS = ("gross_captures_sar", "refunds_and_disputes_sar", "acquirer_fees_sar", "expected_net_payable_sar",
              "bank_paid_sar", "in_transit_sar", "quarantined_sar", "gl_card_clearing_sar",
              "unexplained_bank_variance_sar", "unexplained_gl_variance_sar", "total_incl_vat_sar")


def test_every_money_value_leaves_dax_as_integer_halalas():
    for f in sorted((CC / "queries").glob("*.dax")):
        dax = f.read_text(encoding="utf-8")
        for col in MONEY_COLS:
            for m in re.finditer(rf"\[{col}\]", dax):
                # walk back to the start of the enclosing output expression and require the halala conversion
                line = dax[dax.rfind("\n", 0, m.start()) + 1:dax.find("\n", m.end())]
                if "FILTER(" in line and "CONVERT(" not in line:
                    continue                      # used in a filter condition, not returned
                converted = "CONVERT(ROUND(" in line and "* 100, 0), INTEGER)" in line
                assert converted or "SUMX(CURRENTGROUP()" in line, \
                    f"{f.name}: {col} not converted to halalas: {line.strip()}"
        assert "FLOAT" not in dax.upper() and "CURRENCY(" not in dax.upper()


def test_fixtures_are_recorded_for_every_query():
    queries = {f.stem for f in (CC / "queries").glob("*.dax")}
    fixtures = {f.stem for f in (CC / "__fixtures__").glob("*.json")}
    assert queries == fixtures == {"recon_totals", "recon_cells", "calendar", "zatca", "ndmo"}


def test_snapshot_is_the_export_and_proof_names_its_sources():
    snap = json.loads((CC / "snapshot.json").read_text(encoding="utf-8"))
    assert snap == json.loads((REPO / "command_center" / "data.json").read_text(encoding="utf-8"))
    proof = json.loads((CC / "proof.json").read_text(encoding="utf-8"))
    for k in ("chain", "pdpl", "mdm", "stream", "lineage", "skew", "fabric", "runs"):
        assert k in proof and k in proof["sources"], k
    for k in ("recon", "daily", "calendar", "zatca"):
        assert k not in proof, f"{k} must come live from the semantic model"


def test_app_scenes_are_generated_from_the_same_template():
    tpl = (REPO / "command_center" / "template.html").read_text(encoding="utf-8")
    js = (CC / "legacy" / "scenes.js").read_text(encoding="utf-8")
    body = re.findall(r"<script>(.*?)</script>", tpl, re.S)[0]
    body = body.replace('let D = JSON.parse(document.getElementById("mizan-data").textContent);\n', "")
    assert body in js and js.startswith("// GENERATED") and "export function mountScenes(D)" in js
    html = (CC / "legacy" / "page.html").read_text(encoding="utf-8")
    assert 'id="hero-canvas"' in html and "<script" not in html


def test_connector_is_delegated_semantic_model_and_no_deploy_state_is_committed():
    yml = (APP / "rayfin" / "rayfin.yml").read_text(encoding="utf-8")
    assert "type: fabric-semanticmodel" in yml and "type: delegated" in yml and "name: mizan" in yml
    assert "data:\n    enabled: false" in yml                        # no app database is created
    ignore = (APP / ".gitignore").read_text(encoding="utf-8")
    assert "rayfin/.env" in ignore and "rayfin/.deployments.json" in ignore


def test_stage3_shell_menu_scenes_and_profile_guard():
    tpl = (REPO / "command_center" / "template.html").read_text(encoding="utf-8")
    for label in ("Pulse", "Money flow", "Ledger", "Reconciliation", "ZATCA", "PDPL", "MDM", "Risk stream", "Map",
                  "Data trust", "Platform", "Data life cycle"):
        assert f'"{label}"' in tpl, label
    for sid in ("map", "lifecycle"):
        assert f'<section class="scene" id="{sid}"' in tpl
    assert r"linkedin\.com" in tpl and 'rel="noopener noreferrer"' in tpl     # only a LinkedIn URL becomes a link
    assert 'id="search"' in tpl and "window.MIZAN_QUERY" in tpl
    prof = json.loads((REPO / "config" / "profile.json").read_text(encoding="utf-8"))
    assert prof["name"] and prof["linkedin"].startswith("https://www.linkedin.com/")


def test_stage4_honesty_colour_zatca_language_and_presenter_rules():
    tpl = (REPO / "command_center" / "template.html").read_text(encoding="utf-8")
    assert re.search(r"[\u0600-\u06FF]", tpl) is None, "Arabic must be written as escapes/entities, never raw"
    assert '{ name: "Gross captures", k: "gross", c: C.neutral }' in tpl           # captures are neutral, not green
    assert "awaiting bank file" in tpl and "d3.line().defined(" in tpl            # bank line breaks on 03 Mar
    assert 'id="r-net"' in tpl and 'id="r-broken"' in tpl and 'id="runs-rows"' in tpl
    assert "Simplified: reporting" in tpl and "Standard: clearance" in tpl and 'id="outcome-bar"' in tpl
    assert "24 h reporting window" in tpl and "lag_minutes" in tpl
    assert "Govt payday (27th)" in tpl and "hero.setDefect" in tpl
    for key in ('kk === "p"', 'kk === "t"', 'kk === "b"', 'kk === "l"', "/^[1-9]$/"):
        assert key in tpl, key
    assert "function updateProv" in tpl and "Historical replay" in tpl
    data = json.loads((REPO / "command_center" / "data.json").read_text(encoding="utf-8"))
    r = data["recon"]
    assert (r["bank_net_residual"], r["gl_net_residual"], r["broken_keys"]) == ("0.00", "0.00", 0)
    sla = [a for a in data["stream"]["alerts"] if a["rule"] == "REPORTING_SLA"]
    assert [a["lag_minutes"] for a in sla] == [1560, None]                       # IR-0000102 26 h; IR-0000103 never

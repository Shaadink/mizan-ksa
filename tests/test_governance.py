"""Phase 6, Module 6 (pure Python): NDMO 4-tier catalog, over-classification, fail-closed legal hold, residency
gate (I-14), and the reference erasure decision's fail-closed rule."""

from pathlib import Path

import pytest

from mizan.governance import catalog as G
from mizan.mdm.arabic_norm_and_privacy import execute_pdpl_erasure_decision

POLICY = Path(__file__).resolve().parents[1] / "config" / "residency_policy.yml"


def test_column_rules():
    assert G.classify_column("security", "pii_vault_metadata", "wrapped_dek").tier == "TOP_SECRET"
    assert G.classify_column("audit", "zatca_chain_journal", "signed_xml").tier == "TOP_SECRET"
    assert G.classify_column("brz", "crm_party_raw", "full_name_ar_enc").tier == "SECRET"
    assert G.classify_column("brz", "crm_party_raw", "national_id_hmac").tier == "CONFIDENTIAL"
    assert G.classify_column("gld", "fact_merchant_settlement_recon", "bank_paid_sar").tier == "CONFIDENTIAL"
    assert G.classify_column("gld", "dim_date_saudi", "hijri_month_name").tier == "PUBLIC"


def test_mixed_table_inherits_highest_tier_and_reports_over_classification():
    rows = G.build_catalog({"brz.crm_party_raw": [("full_name_ar_enc", "string"), ("subject_token_id", "string"),
                                                  ("city", "string"), ("created_date", "string")],
                            "slv.settlement_lines": [("merchant_id", "string"), ("net_settled_sar", "decimal")]})
    crm = [r for r in rows if r["table_name"] == "crm_party_raw"]
    assert {r["table_classification"] for r in crm} == {"SECRET"}
    assert sum(r["is_over_classified"] for r in crm) == 3
    assert {r["legal_hold_class"] for r in crm} == {"CONSENT"} and crm[0]["subject_key"] == "subject_token_id"
    oc = {t["table_name"]: t for t in G.over_classification(rows)}
    assert oc["crm_party_raw"]["over_classified_pct"] == 75.0
    assert oc["crm_party_raw"]["recommendation"] == "SPLIT_SECRET_COLUMNS"
    assert oc["settlement_lines"]["recommendation"] == "NONE"


def test_unmapped_table_fails_closed():
    with pytest.raises(LookupError):
        G.build_catalog({"brz.new_unreviewed_feed": [("x", "string")]})


def test_unknown_hold_class_in_rules_fails_closed(monkeypatch):
    monkeypatch.setattr(G, "TABLE_HOLD", (("brz.*", "tax"),))
    with pytest.raises(ValueError):
        G.legal_hold_class("brz", "crm_party_raw")


def test_residency_gate_blocks_secret_in_open_zones():
    zones, approved = G.load_policy(POLICY)
    assert zones["WH_MIZAN.gld"].max_classification == "CONFIDENTIAL" and approved == {"KSA"}
    ok = [{"zone": "WH_MIZAN.gld", "schema_name": "gld", "table_name": "t", "column_name": "a",
           "classification": "CONFIDENTIAL"}]
    assert G.residency_violations(ok, zones, approved) == []
    bad = [{**ok[0], "column_name": "buyer_name_enc", "classification": "SECRET"},
           {**ok[0], "zone": "EXPORT.open_data", "classification": "CONFIDENTIAL"},
           {**ok[0], "zone": "S3.somewhere", "classification": "PUBLIC"}]
    v = G.residency_violations(bad, zones, approved)
    assert len(v) == 3 and "zone ceiling is CONFIDENTIAL" in v[0] and "undeclared zone" in v[2]


def test_secret_data_needs_an_approved_region():
    zones = {"EU.copy": G.Zone("EU.copy", "TOP_SECRET", "EU")}
    v = G.residency_violations([{"zone": "EU.copy", "schema_name": "s", "table_name": "t", "column_name": "c",
                                 "classification": "SECRET"}], zones, {"KSA"})
    assert v and "not approved for SECRET" in v[0]


def test_erasure_decision_uppercases_and_fails_closed():
    vault, tombs, tmap = {"s1": {"wrapped_dek": b"k", "status": "ACTIVE"}}, set(), {"s1": "id"}
    d = execute_pdpl_erasure_decision("s1", " tax ", vault, tombs, tmap)
    assert d["signed_tax_invoice_status"] == "LEGAL_HOLD_RETAINED" and vault["s1"]["wrapped_dek"] is None
    assert "s1" in tombs and "s1" not in tmap
    assert execute_pdpl_erasure_decision("s2", "CONSENT", {}, set(), {})["signed_tax_invoice_status"] \
        == "PURGE_SCHEDULED"
    with pytest.raises(ValueError):
        execute_pdpl_erasure_decision("s3", "ARCHIVE", {}, set(), {})

"""Phase 6 in the lakehouse: PDPL crypto-shred with legal hold + Backup Restore Guard (I-07, I-08) and the NDMO
catalog (meta.column_classification). Runs on a COPY of the shared lake so other tests are unaffected.

Artifact 3 in three panels: (1) live key, readable Arabic name; (2) after the DSR: key NULL, name unreadable,
token->ID link gone, signed tax journal LEGAL_HOLD_RETAINED, tax totals identical; (3) a restore of the vault AND
of a Silver snapshot cannot bring the person back once the Restore Guard has run.
"""

import json
import shutil

import pytest

pytest.importorskip("pyspark")
pytestmark = pytest.mark.spark

from conftest import read_csv  # noqa: E402
from mizan.privacy import crypto  # noqa: E402

GOLDEN_AR = "\u0645\u062D\u0645\u062F \u0628\u0644\u0627\u0644 \u0627\u0644\u0639\u062A\u064A\u0628\u064A"


def vault_rows(lk, tokens):
    from pyspark.sql import functions as F
    return {r["subject_token_id"]: r for r in lk.read("security", "pii_vault_metadata")
            .filter(F.col("subject_token_id").isin(*tokens)).collect()}


def golden_of(lk, token):
    for g in lk.read("slv", "golden_party_scd2").filter("is_current AND status = 'ACTIVE'").collect():
        if token in json.loads(g["member_tokens"]):
            return g
    return None


def recon_inputs(lk):
    from pyspark.sql import functions as F
    s = lk.read("slv", "settlement_lines").agg(F.sum("net_settled_sar")).first()[0]
    p = lk.read("slv", "payment_lifecycle").agg(F.sum("amount_sar")).first()[0]
    g = lk.read("slv", "erp_gl_journal_lines").agg(F.sum("amount_sar")).first()[0]
    return (s, p, g)


@pytest.fixture(scope="module")
def dsr(spark, lake_run, test_keys, gen_dir, tmp_path_factory):
    from pyspark.sql import functions as F

    from mizan.privacy.pdpl import execute_dsr, tax_totals
    from mizan.spark.lake import Lake, cleanup_staging
    from mizan.spark.session import TableLocator
    root = tmp_path_factory.mktemp("lake_pdpl")
    shutil.copytree(lake_run["root"], root, dirs_exist_ok=True)
    lk = Lake(spark, TableLocator("local", root))
    pos = read_csv(gen_dir / "crm/crm_pos_cp1256.csv", "cp1256")
    national_id = pos[0]["national_id"]                       # the five-spelling customer (D11)
    anchor_token = crypto.token_for(test_keys.hmac_key, pos[0]["source_customer_id"])
    g = golden_of(lk, anchor_token)
    tokens = sorted(json.loads(g["member_tokens"]))
    v = vault_rows(lk, tokens)
    dek = crypto.unwrap_dek(test_keys, g["name_ar_source_token"], bytes(v[g["name_ar_source_token"]]["wrapped_dek"]))
    before = {"name": crypto.decrypt_field(dek, g["name_ar_source_token"], "full_name_ar", g["name_ar_enc"]),
              "golden": g, "links": lk.read("security", "subject_token_map").filter(
                  F.col("subject_token_id").isin(*tokens)).count(),
              "vault_version": lk.spark.sql(f"DESCRIBE HISTORY {lk.ref('security', 'pii_vault_metadata')}")
              .agg({"version": "max"}).first()[0],
              "golden_version": lk.spark.sql(f"DESCRIBE HISTORY {lk.ref('slv', 'golden_party_scd2')}")
              .agg({"version": "max"}).first()[0],
              "tax": tax_totals(lk), "recon": recon_inputs(lk)}
    backup = tmp_path_factory.mktemp("vault_backup")            # an external backup taken BEFORE the erasure
    shutil.copytree(lk.path("security", "pii_vault_metadata"), backup, dirs_exist_ok=True)
    ev = execute_dsr(lk, test_keys, national_id=national_id, requested_by="dpo.test")
    cleanup_staging(spark)
    return {"lake": lk, "tokens": tokens, "before": before, "ev": ev, "backup": backup}


def test_panel1_before_erasure_key_live_and_name_readable(dsr):
    b = dsr["before"]
    assert b["name"] == GOLDEN_AR and b["golden"]["member_count"] == 5
    assert b["links"] == 5                                     # token -> identity link exists for each record


def test_panel2_dsr_shreds_every_linked_record_and_keeps_tax_evidence(dsr, test_keys):
    lk, tokens, ev = dsr["lake"], dsr["tokens"], dsr["ev"]
    assert sorted(ev["tokens"]) == tokens and ev["vault_rows_shredded"] == 5
    v = vault_rows(lk, tokens)
    assert all(r["wrapped_dek"] is None and r["dek_status"] == "SHREDDED" for r in v.values())
    with pytest.raises(PermissionError):
        crypto.unwrap_dek(test_keys, tokens[0], None)
    from pyspark.sql import functions as F
    assert lk.read("security", "subject_token_map").filter(F.col("subject_token_id").isin(*tokens)).count() == 0
    assert ev["token_links_removed"] == 5
    assert {r[0] for r in lk.read("ctl", "deletion_tombstones").select("subject_token_id").collect()} >= set(tokens)
    assert ev["legal_hold_class"] == "TAX" and ev["signed_tax_invoice_status"] == "LEGAL_HOLD_RETAINED"
    assert ev["analytical_pii_status"] == "CRYPTO_SHREDDED_UNRECOVERABLE" and ev["journal_rows_retained"] > 0
    assert ev["tax_totals_after"] == ev["tax_totals_before"] == dsr["before"]["tax"]
    assert recon_inputs(lk) == dsr["before"]["recon"]           # Gold's inputs, hence Gold SAR totals, unchanged
    assert golden_of(lk, tokens[0]) is None                     # golden profile retired
    evidence = lk.read("audit", "pdpl_dsr_evidence").collect()
    assert len(evidence) == 1 and evidence[0]["requested_by"] == "dpo.test"


def test_panel2_vault_time_travel_cannot_return_the_key(dsr):
    lk, tokens = dsr["lake"], dsr["tokens"]
    old = lk.spark.read.format("delta").option("versionAsOf", dsr["before"]["vault_version"]) \
        .load(lk.path("security", "pii_vault_metadata"))
    try:
        rows = old.filter(old.subject_token_id.isin(*tokens)).collect()
    except Exception:                                           # files VACUUMed: the old version is unreadable
        return
    assert all(r["wrapped_dek"] is None for r in rows)


def test_no_new_key_can_be_minted_for_an_erased_subject(dsr, test_keys):
    from mizan.spark.bronze import ensure_deks
    from mizan.spark.lake import cleanup_staging
    lk, tokens = dsr["lake"], dsr["tokens"]
    assert ensure_deks(lk, test_keys, tokens) == {}
    assert all(r["wrapped_dek"] is None for r in vault_rows(lk, tokens).values())
    cleanup_staging(lk.spark)


def test_panel3_restore_of_vault_and_silver_blocked_by_restore_guard(dsr, test_keys):
    from mizan.privacy.pdpl import restore_guard
    from mizan.spark.lake import cleanup_staging
    lk, tokens = dsr["lake"], dsr["tokens"]
    vault_path = lk.path("security", "pii_vault_metadata")
    shutil.rmtree(vault_path)                                   # simulate restoring the pre-erasure vault backup
    shutil.copytree(dsr["backup"], vault_path)
    lk.spark.sql(f"RESTORE TABLE {lk.ref('slv', 'golden_party_scd2')} "
                 f"TO VERSION AS OF {dsr['before']['golden_version']}")
    assert all(r["wrapped_dek"] is not None for r in vault_rows(lk, tokens).values())   # the danger is real
    assert golden_of(lk, tokens[0]) is not None

    report = restore_guard(lk, test_keys)
    assert report["keys_reshredded"] == 5 and report["goldens_reresolved"] == 1
    assert all(r["wrapped_dek"] is None and r["dek_status"] == "SHREDDED" for r in vault_rows(lk, tokens).values())
    assert golden_of(lk, tokens[0]) is None
    restored = dsr["before"]["golden"]                           # the restored row's ciphertext is now useless
    with pytest.raises(PermissionError):
        crypto.unwrap_dek(test_keys, restored["name_ar_source_token"],
                          vault_rows(lk, [restored["name_ar_source_token"]])[restored["name_ar_source_token"]][
                              "wrapped_dek"])
    cleanup_staging(lk.spark)


def test_unknown_legal_hold_class_fails_closed_before_any_change(dsr, test_keys, gen_dir):
    from mizan.privacy.pdpl import execute_dsr
    lk = dsr["lake"]
    other = read_csv(gen_dir / "crm/crm_ecom_utf8.csv")[10]["source_customer_id"]
    tok = crypto.token_for(test_keys.hmac_key, other)
    with pytest.raises(ValueError):
        execute_dsr(lk, test_keys, source_ref=other, legal_hold_class="ARCHIVE")
    assert vault_rows(lk, [tok])[tok]["dek_status"] == "ACTIVE"


# ---------------------------------------------------------------- NDMO catalog on the real lake

def test_ndmo_catalog_covers_every_table(lake_run):
    lk = lake_run["lake"]
    cat = lk.read("meta", "column_classification")
    tables = {(r[0], r[1]) for r in cat.select("schema_name", "table_name").distinct().collect()}
    for schema in ("brz", "ctl", "slv", "quarantine", "security", "audit"):
        assert {t for s, t in tables if s == schema} == set(lk.list_tables(schema))
    tiers = {(r["schema_name"], r["table_name"]): r["table_classification"] for r in cat.collect()}
    assert tiers[("security", "pii_vault_metadata")] == "TOP_SECRET"
    assert tiers[("audit", "zatca_chain_journal")] == "TOP_SECRET"
    assert tiers[("brz", "crm_party_raw")] == "SECRET"
    assert tiers[("slv", "settlement_lines")] == "CONFIDENTIAL"
    assert cat.filter("is_over_classified").count() > 0
    assert cat.filter("legal_hold_class NOT IN ('TAX', 'SAMA', 'CONSENT')").count() == 0


# ---------------------------------------------------------------- Phase 9: governed AI on the lake (I-07 for AI)

def test_ai_case_notes_entitled_then_suppressed_after_erasure(dsr, test_keys):
    from mizan.ai.governed import User
    from mizan.privacy.pdpl import execute_dsr
    from mizan.spark.ai_land import ask, build_index, load_chunks, tombstones
    from mizan.spark.lake import cleanup_staging
    lk = dsr["lake"]
    chunks = load_chunks(lk)
    assert sum(1 for c in chunks if not c.subject_token_id) > 5 and sum(1 for c in chunks if c.subject_token_id) > 1000
    dead = tombstones(lk)
    c0 = next(c for c in chunks if c.subject_token_id and c.subject_token_id not in dead)
    rid = c0.doc_id.removeprefix("CASE-")
    care = User("care.agent", frozenset({"CUSTOMER_CARE"}), "CONFIDENTIAL")
    junior = User("junior.analyst", frozenset({"ALL_STAFF"}), "PUBLIC")
    a = ask(lk, f"return case {rid} refund", care)
    assert a.route == "RAG" and a.chunks[0] == c0.chunk_id
    assert c0.chunk_id not in ask(lk, f"return case {rid} refund", junior).chunks   # public policy at most

    link = lk.read("security", "subject_token_map").filter(f"subject_token_id = '{c0.subject_token_id}'").first()
    ref = crypto.decrypt_with_kek(test_keys, f"TOKEN_MAP|{c0.subject_token_id}", link["source_ref_enc"])
    execute_dsr(lk, test_keys, source_ref=ref, requested_by="dpo.test")
    after = ask(lk, f"return case {rid} refund", care)
    assert c0.chunk_id not in after.chunks                      # suppressed at question time, before any rebuild
    build_index(lk)
    assert c0.chunk_id not in {c.chunk_id for c in load_chunks(lk)}
    log = lk.read("ai", "agent_audit_log").collect()
    assert len(log) == 3 and all(f"return case {rid}" not in str(r.asDict().values()) for r in log)
    cleanup_staging(lk.spark)

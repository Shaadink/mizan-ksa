"""Phase 3: Bronze + Silver on local Spark/Delta (same code path as Fabric via the session factory).

Covers: source-to-Bronze hash reconciliation, contracts + quarantine routing, encrypt-on-land (no cleartext PII),
CP1256 three cases, applied_event_ledger dedup / replay idempotency (I-12), Silver grain and money types,
IN_TRANSIT expectation rows, zero bank variance on main data, orphan quarantine on the demo overlay, ZATCA landing.
"""

import json
from collections import Counter

import pytest

pyspark = pytest.importorskip("pyspark")
pytestmark = pytest.mark.spark

from mizan.privacy import crypto  # noqa: E402

GOLDEN_AR = "\u0645\u062D\u0645\u062F \u0628\u0644\u0627\u0644 \u0627\u0644\u0639\u062A\u064A\u0628\u064A"


def files_by(run, source):
    return [s for s in run["files"] if s["source"] == source]


# ---------------------------------------------------------------- Bronze: reconciliation + contracts

def test_source_to_bronze_hash_reconciliation(lake_run):
    for s in lake_run["first"]["files"]:
        assert s["sha_match"] is True, s["source_file"]
        assert s["source_rows"] == s["landed_rows"] + s["duplicate_rows"] + s["rejected_rows"], s


def test_bronze_volumes(lake_run):
    first = lake_run["first"]
    landed = Counter()
    for s in first["files"]:
        landed[s["source"]] += s["landed_rows"]
    assert landed["commerce_events"] == 25_000
    assert landed["zatca_requests"] == 25_000
    assert landed["payment_events"] == 18_000
    assert landed["settlement"] == 17_000
    assert landed["crm_pos"] == 1_800 - 15 and landed["crm_ecom"] == 2_200
    assert landed["spl_address"] == 1_000


def test_duplicate_settlement_file_is_deduplicated(lake_run, manifest):
    resend = next(d for d in manifest["defects"] if d["id"] == "D07")["location"]["file"]
    st = next(s for s in lake_run["first"]["files"] if s["source_file"] == resend)
    assert st["status"] == "ALL_DUPLICATE" and st["landed_rows"] == 0 and st["duplicate_rows"] == st["source_rows"]


def test_replay_is_idempotent(lake_run, lake):
    """I-12: landing every file a second time changes nothing."""
    for s in lake_run["replay"]["files"]:
        assert s["landed_rows"] == 0 and s["status"] in ("ALL_DUPLICATE", "EMPTY"), s
    for t, n in lake_run["snapshot"].items():
        assert lake.read(*t.split(".")).count() == n, t
    assert lake_run["replay"]["zatca"]["new_documents"] == 0


def test_unrecoverable_names_quarantined(lake, manifest):
    rej = lake.read("quarantine", "schema_rejections").filter("source = 'crm_pos'").collect()
    assert len(rej) == 15
    assert all("CP1256_UNRECOVERABLE" in r["reject_reason"] for r in rej)
    payloads = [json.loads(r["payload_json"]) for r in rej]
    assert all(p.get("mobile_enc", "").startswith("v1:") for p in payloads)      # PII stays sealed in quarantine
    assert all("full_name_ar" not in p and "mobile" not in p for p in payloads)


def test_schema_drift_rejects_whole_file(spark, gen_dir, test_keys, tmp_path):
    from mizan.spark import contracts as C
    from mizan.spark.bronze import land_files
    from mizan.spark.lake import Lake
    from mizan.spark.session import TableLocator
    src = (gen_dir / "payments/payment_events.csv").read_text(encoding="utf-8").splitlines()
    data = tmp_path / "data"
    (data / "payments").mkdir(parents=True)
    drifted = [src[0].replace("amount_sar", "amount")] + src[1:20]
    (data / "payments/payment_events.csv").write_text("\n".join(drifted) + "\n", encoding="utf-8")
    lk = Lake(spark, TableLocator("local", tmp_path / "lake"))
    st = land_files(lk, test_keys, C.PAYMENTS, [data / "payments/payment_events.csv"], data)[0]
    assert st["status"] == "REJECTED_SCHEMA_DRIFT" and st["landed_rows"] == 0
    assert not lk.exists("brz", "payment_events_raw")


def test_bad_rows_routed_to_quarantine(spark, gen_dir, test_keys, tmp_path):
    from mizan.spark import contracts as C
    from mizan.spark.bronze import land_files
    from mizan.spark.lake import Lake
    from mizan.spark.session import TableLocator
    lines = (gen_dir / "payments/payment_events.csv").read_text(encoding="utf-8").splitlines()[:6]
    lines[1] = lines[1].replace(",CAPTURE,", ",capture,")              # lower-case enum
    lines[2] = lines[2].rsplit(",SAR,", 1)[0] + ",SAR,2026-02-12 10:00:00"   # wrong timestamp format
    cols = lines[3].split(",")
    cols[9] = "12.5"                                                    # 1 decimal: not halala-exact
    lines[3] = ",".join(cols)
    data = tmp_path / "data"
    (data / "payments").mkdir(parents=True)
    (data / "payments/payment_events.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lk = Lake(spark, TableLocator("local", tmp_path / "lake"))
    st = land_files(lk, test_keys, C.PAYMENTS, [data / "payments/payment_events.csv"], data)[0]
    assert (st["landed_rows"], st["rejected_rows"]) == (2, 3)
    reasons = sorted(r["reject_reason"] for r in lk.read("quarantine", "schema_rejections").collect())
    assert reasons == ["BAD_ENUM:event_type", "BAD_FORMAT:amount_sar", "BAD_FORMAT:event_ts_utc"]


# ---------------------------------------------------------------- encrypt on land (ADR-003)

def _string_values(df):
    cols = [f.name for f in df.schema.fields if f.dataType.simpleString() == "string"]
    for r in df.select(*cols).collect():
        for v in r:
            if v:
                yield v


def test_no_cleartext_pii_in_bronze(lake, gen_dir):
    from tests_helpers_pii import cleartext_probes
    probes = cleartext_probes(gen_dir)
    for table in ("commerce_events_raw", "crm_party_raw", "spl_address_raw", "zatca_invoices_raw"):
        df = lake.read("brz", table)
        assert "customer_ref" not in df.columns and "source_customer_id" not in df.columns
        values = set(_string_values(df.drop("payload_json") if table == "zatca_invoices_raw" else df))
        leaked = [p for p in probes if p in values]
        assert leaked == [], (table, leaked[:3])
    crm = lake.read("brz", "crm_party_raw")
    arabic = [v for v in _string_values(crm) if any("\u0600" <= c <= "\u06FF" for c in v)]
    assert arabic == []


def test_encrypted_fields_decrypt_with_vault_dek(lake, test_keys):
    token = crypto.subject_token(test_keys, "ECOM-C000001")   # the planted mojibake row of the golden customer
    row = lake.read("brz", "crm_party_raw").filter(f"subject_token_id = '{token}'").first()
    assert row["name_ar_encoding_status"] == "REPAIRED_MOJIBAKE"
    v = lake.read("security", "pii_vault_metadata").filter(f"subject_token_id = '{token}'").first()
    dek = crypto.unwrap_dek(test_keys, token, bytes(v["wrapped_dek"]))
    assert crypto.decrypt_field(dek, token, "full_name_ar", row["full_name_ar_enc"]) == GOLDEN_AR


def test_cp1256_statuses_landed(lake):
    c = Counter(r["name_ar_encoding_status"] for r in lake.read("brz", "crm_party_raw").collect())
    assert c["REPAIRED_MOJIBAKE"] == 41 and c["DECODED_CP1256"] > 1000 and "UNRECOVERABLE" not in c


def test_vault_has_zero_file_retention(spark, lake):
    props = spark.sql(f"DESCRIBE DETAIL {lake.ref('security', 'pii_vault_metadata')}").first()["properties"]
    assert props["delta.deletedFileRetentionDuration"] == "interval 0 hours"


def test_identifier_hmac_enables_exact_match_without_decrypting(lake, test_keys, manifest):
    ids = next(d for d in manifest["defects"] if d["id"] == "D11")["location"]["ids"]
    toks = [crypto.subject_token(test_keys, i) for i in ids]
    from pyspark.sql import functions as F
    rows = lake.read("brz", "crm_party_raw").filter(F.col("subject_token_id").isin(toks)).collect()
    assert len(rows) == 5 and len({r["national_id_hmac"] for r in rows}) == 1   # Arabic-Indic digits folded first


# ---------------------------------------------------------------- Silver

def test_no_float_columns_in_financial_tables(lake):
    for schema, table in (("slv", "payment_lifecycle"), ("slv", "settlement_lines"),
                          ("slv", "erp_gl_journal_lines"), ("slv", "zatca_invoice_documents")):
        types = {f.name: f.dataType.simpleString() for f in lake.read(schema, table).schema.fields}
        assert not any(t in ("float", "double") for t in types.values()), (table, types)
        for col in [c for c in types if c.endswith("_sar")]:
            assert types[col] == "decimal(18,2)", (table, col)


def test_payment_lifecycle_grain_and_riyadh_dates(lake):
    df = lake.read("slv", "payment_lifecycle")
    assert df.count() == 18_000 == df.select("payment_event_id").distinct().count()
    row = df.filter("payment_event_id = 'PE-0000001'").first()
    # first event of the period is after midnight KSA on 2026-02-12, i.e. still 2026-02-11 in UTC
    assert str(row["business_date_ksa"]) == "2026-02-12"


def test_settlement_lines_one_row_per_payment_event(lake):
    df = lake.read("slv", "settlement_lines")
    assert df.count() == 18_000 == df.select("payment_event_id").distinct().count()
    c = Counter(r["settlement_status"] for r in df.select("settlement_status").collect())
    assert c == {"PAID_BANK": 17_000, "IN_TRANSIT": 1_000}


def test_in_transit_rows_are_estimates_dated_on_business_day(spark, lake):
    t = lake.read("slv", "settlement_lines").filter("settlement_status = 'IN_TRANSIT'")
    assert t.filter("NOT is_estimate OR settlement_batch_id IS NOT NULL").count() == 0
    assert {str(r[0]) for r in t.select("settlement_for_date_ksa").distinct().collect()} == {"2026-03-03"}


def test_bank_leg_closes_to_zero_in_spark(spark, lake):
    lake.read("slv", "payment_lifecycle").createOrReplaceTempView("p")
    lake.read("slv", "settlement_lines").createOrReplaceTempView("s")
    bad = spark.sql("""
        WITH c AS (SELECT merchant_id, business_date_ksa d,
                          SUM(CASE WHEN event_type='CAPTURE' THEN amount_sar ELSE -amount_sar END) net
                   FROM p GROUP BY 1, 2),
             s AS (SELECT merchant_id, settlement_for_date_ksa d, SUM(acquirer_mdr_fee_sar + acquirer_vat_sar) fees,
                          SUM(net_settled_sar) settled FROM s GROUP BY 1, 2)
        SELECT * FROM c FULL OUTER JOIN s USING (merchant_id, d)
        WHERE COALESCE(c.net, 0) - COALESCE(s.fees, 0) - COALESCE(s.settled, 0) <> 0""").count()
    assert bad == 0


def test_gl_lines_signed_by_direction_and_typed(lake):
    df = lake.read("slv", "erp_gl_journal_lines")
    assert df.filter("amount_sar <= 0").count() == 0
    assert {r[0] for r in df.select("gl_account_role").distinct().collect()} <= {
        "CASH_ON_HAND", "CARD_CLEARING", "REVENUE", "VAT_OUTPUT", "CHARGEBACK_LOSS"}


def test_delta_check_constraint_blocks_bad_money(spark, lake):
    from pyspark.sql.utils import AnalysisException  # noqa: F401
    bad = spark.sql(f"SELECT * FROM {lake.ref('slv', 'payment_lifecycle')} LIMIT 1") \
        .selectExpr(*["CAST(-1 AS DECIMAL(18,2)) AS amount_sar" if c == "amount_sar" else c
                      for c in lake.read("slv", "payment_lifecycle").columns])
    with pytest.raises(Exception, match=r"(?i)check constraint|amount_positive"):
        bad.write.format("delta").mode("append").save(lake.path("slv", "payment_lifecycle"))


# ---------------------------------------------------------------- ZATCA landing

def test_zatca_control_plane_landed(lake):
    assert lake.read("ctl", "invoice_outbox").count() == 25_001
    j = lake.read("audit", "zatca_chain_journal")
    assert j.count() == 25_001
    assert dict(j.dtypes)["signed_xml"] == "binary"
    assert {r[0] for r in j.select("retention_status").distinct().collect()} == {"LEGAL_HOLD_RETAINED"}
    assert "signed_xml" not in lake.read("ctl", "invoice_outbox").columns     # ADR-001: XML only in the journal
    assert lake.read("quarantine", "zatca_chain_violations").count() == 0
    docs = lake.read("slv", "zatca_invoice_documents")
    assert docs.filter("issue_date_ksa IS NULL").count() == 0


# ---------------------------------------------------------------- demo overlay (orphan + 0.01)

def test_demo_overlay_orphan_quarantined_and_gl_corrected(lake_run, manifest):
    from decimal import Decimal
    lk = lake_run["demo_lake"]
    assert lake_run["demo_gl_stats"]["corrections"] == 1
    orphan = lk.read("slv", "settlement_lines").filter("payment_event_id = 'PE-9900001'").first()
    assert orphan["settlement_status"] == "QUARANTINED"
    assert lk.read("quarantine", "settlement_breaks").first()["break_type"] == "ORPHAN_BANK_LINE"
    d06 = next(d for d in manifest["defects"] if d["id"] == "D06")["location"]
    where = f"document_number = '{d06['BELNR']}' AND line_item = '{d06['DOCLN']}'"
    line = lk.read("slv", "erp_gl_journal_lines").filter(where).first()
    base = lake_run["lake"].read("slv", "erp_gl_journal_lines").filter(where).first()
    assert line["is_correction"] is True
    assert base["amount_sar"] - line["amount_sar"] == Decimal("0.01")


def test_zatca_invoice_documents_hold_no_cleartext_buyer_pii(lake, gen_dir):
    """Signed XML (which embeds buyer details) lives ONLY in audit.zatca_chain_journal under legal hold."""
    import json as _json

    from tests_helpers_pii import cleartext_probes
    docs = lake.read("slv", "zatca_invoice_documents")
    assert not {c for c in docs.columns if "xml" in c or "buyer" in c or c == "customer_ref"}
    probes = set(cleartext_probes(gen_dir, limit=5000))
    for line in (gen_dir / "zatca/invoice_requests.jsonl").read_text(encoding="utf-8").splitlines():
        q = _json.loads(line)
        if q["customer_ref"]:
            probes.add(q["customer_ref"])
    cols = [f.name for f in docs.schema.fields if f.dataType.simpleString() == "string"]
    cells = {v for row in docs.select(*cols).collect() for v in row if v}
    assert not cells & probes
    assert all(not any(p in v for p in probes if len(p) >= 8) for v in list(cells)[:2000])

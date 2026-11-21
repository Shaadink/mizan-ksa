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


def test_a_corrected_zatca_resend_does_not_double_the_silver_documents(lake_run, spark, test_keys, tmp_path):
    """Bronze is append-only, so a corrected re-send leaves TWO rows per request_id. Silver must take the latest.

    THE BUG THIS PINS, found on Fabric on 2026-11-19 and by no test here. Six item prices had been corrected
    weeks earlier, so re-running the pipeline on the tenant re-landed all 25,000 ZATCA requests as corrections
    -- the first time this pipeline had ever seen real corrections on a re-run. `zatca_land` then joined
    `ctl.invoice_outbox` to `brz.zatca_invoices_raw` on request_id, hit two Bronze rows per request, and fanned
    every outbox row into two: `slv.zatca_invoice_documents` doubled to 50,002 and invoice_uuid stopped being
    unique. dbt caught it (`source_unique_..._invoice_uuid`, 25,001 duplicates) and refused to publish Gold --
    the circuit breaker working -- but the defect reached the warehouse, so the breaker was the second line of
    defence. This test is the first.

    Why the existing replay could not catch it: `lake_run` replays the SAME bytes, so Bronze dedup drops every
    row and nothing lands. Idempotency on identical input was proven; idempotency on CORRECTED input was not,
    and those are different claims. Every other Bronze reader already used `_latest()`; zatca_land did not.
    """
    import json as _json
    import shutil

    from mizan.spark.bronze import land_invoice_requests
    from mizan.spark.lake import Lake
    from mizan.spark.session import TableLocator
    from mizan.spark.zatca_land import run_zatca

    root = tmp_path / "corrected"
    shutil.copytree(lake_run["root"], root, dirs_exist_ok=True)
    lk = Lake(spark, TableLocator("local", root))

    before = lk.read("slv", "zatca_invoice_documents").count()
    assert before == 25_001, "fixture changed: this test pins the document count against doubling"

    # Re-send 50 requests with a changed payload: same request_id (business key), different bytes -> correction.
    rows = lk.read("brz", "zatca_invoices_raw").limit(50).collect()
    lines = []
    for r in rows:
        payload = _json.loads(r["payload_json"])
        payload["_correction_probe"] = True
        lines.append(_json.dumps(payload, sort_keys=True))
    resend_dir = tmp_path / "resend"
    resend_dir.mkdir(parents=True, exist_ok=True)
    f = resend_dir / "zatca" / "invoice_requests.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")

    stats = land_invoice_requests(lk, test_keys, f, resend_dir)
    assert stats["landed_rows"] == 50, f"the probe did not land as corrections: {stats}"
    assert lk.read("brz", "zatca_invoices_raw").count() == 25_050, "Bronze must hold both versions"

    run_zatca(lk, None)

    docs = lk.read("slv", "zatca_invoice_documents")
    assert docs.count() == before, (
        f"Silver doubled on a corrected re-send: {docs.count()} rows, expected {before}. zatca_land must read "
        "Bronze through _latest() -- a join key with two rows per key fans out the whole table.")
    assert docs.select("invoice_uuid").distinct().count() == docs.count(), "invoice_uuid is no longer unique"


def test_a_price_corrected_after_signing_reaches_the_tax_chain_as_a_credit_note(lake_run, spark, test_keys,
                                                                                tmp_path, monkeypatch):
    """HONESTY row 29, closed. Correcting a price upstream moved Silver, Gold and the bank reconciliation and
    left the signed tax chain on the OLD amount, with no credit note raised -- the exact condition this
    project exists to detect, happening inside the project.

    Both halves of the old behaviour were right and that was the trap: `run_zatca` skips any request_id
    already in the outbox, because re-pricing a document ZATCA already holds is the one thing a tax chain
    must never do. The missing piece was not a patch to the engine, it was the pair of documents nobody was
    issuing. So this test asserts the chain ARRIVES at the corrected total without the original moving at
    all.
    """
    import json as _json
    import shutil
    from decimal import Decimal

    from mizan.spark.bronze import land_invoice_requests
    from mizan.spark.lake import Lake
    from mizan.spark.session import TableLocator
    from mizan.spark.zatca_land import run_zatca

    # Issuance is gated off by default (HONESTY rows 38 and 40): a feature whose document-type
    # correctness is still open does not write to a tax chain unless somebody says so. This test says so.
    monkeypatch.setenv(zatca_land_flag(), "1")

    root = tmp_path / "repriced"
    shutil.copytree(lake_run["root"], root, dirs_exist_ok=True)
    lk = Lake(spark, TableLocator("local", root))
    before = lk.read("slv", "zatca_invoice_documents").count()

    # Three standard invoices get a cheaper first line, exactly as an upstream price fix would leave them.
    originals = [r.asDict() for r in lk.read("ctl", "invoice_outbox")
                 .filter("document_type = 'INVOICE'").orderBy("request_id").limit(3).collect()]
    wanted = {r["request_id"] for r in originals}
    raw = {r["request_id"]: _json.loads(r["payload_json"])
           for r in lk.read("brz", "zatca_invoices_raw").collect() if r["request_id"] in wanted}

    lines, expected = [], {}
    for request_id, payload in sorted(raw.items()):
        ln = payload["lines"][0]
        net = (Decimal(ln["line_net_sar"]) * Decimal("0.80")).quantize(Decimal("0.01"))
        ln.update({"line_net_sar": f"{net:.2f}", "unit_price_sar": f"{net / Decimal(ln['qty']):.2f}",
                   "line_vat_sar": f"{(net * Decimal('0.15')).quantize(Decimal('0.01')):.2f}"})
        tn = sum((Decimal(x["line_net_sar"]) for x in payload["lines"]), Decimal("0"))
        tv = sum((Decimal(x["line_vat_sar"]) for x in payload["lines"]), Decimal("0"))
        payload.update({"total_excl_vat_sar": f"{tn:.2f}", "vat_total_sar": f"{tv:.2f}",
                        "total_incl_vat_sar": f"{tn + tv:.2f}"})
        expected[request_id] = tn + tv
        lines.append(_json.dumps(payload, sort_keys=True))

    send = tmp_path / "reprice" / "zatca" / "invoice_requests.jsonl"
    send.parent.mkdir(parents=True, exist_ok=True)
    send.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert land_invoice_requests(lk, test_keys, send, send.parent.parent)["landed_rows"] == 3

    run_zatca(lk, None)
    docs = lk.read("slv", "zatca_invoice_documents")
    assert docs.count() == before + 6, (
        f"expected one credit note + one replacement per corrected invoice, got {docs.count() - before}")
    assert docs.select("invoice_uuid").distinct().count() == docs.count()

    rows = {r["request_id"]: r.asDict() for r in docs.collect()}
    for original in originals:
        rid = original["request_id"]
        cancel, replacement = rows[f"{rid}-PC1CN"], rows[f"{rid}-PC1RI"]
        assert cancel["document_type"] == "CREDIT_NOTE" and replacement["document_type"] == "INVOICE"
        # The original is untouched: same uuid, same amount, still in the chain at its own ICV.
        assert rows[rid]["invoice_uuid"] == original["invoice_uuid"]
        assert Decimal(str(rows[rid]["total_incl_vat_sar"])) == Decimal(str(original["total_incl_vat_sar"]))
        # And the three together state the corrected amount, to the halala.
        net = (Decimal(str(rows[rid]["total_incl_vat_sar"]))
               - Decimal(str(cancel["total_incl_vat_sar"]))
               + Decimal(str(replacement["total_incl_vat_sar"])))
        assert net == expected[rid], f"{rid}: chain nets to {net}, corrected amount is {expected[rid]}"
        # Derived documents inherit the original's issue date rather than landing NULL and dropping out of
        # every date-filtered tax report.
        assert cancel["issue_date_ksa"] is not None and replacement["issue_date_ksa"] is not None

    # Running again must issue NOTHING. A detector that re-fires would add two ICVs per invoice per night.
    # This is the assertion that caught the first implementation: it asked "has this ever been corrected",
    # which only answers correctly the first time, instead of "what does the chain state today".
    run_zatca(lk, None)
    assert lk.read("slv", "zatca_invoice_documents").count() == before + 6, (
        "the price-correction detector fired twice for the same correction")

    # A SECOND price change on an already-corrected invoice must cancel the REPLACEMENT, not the original.
    # Cancelling the original twice would subtract it twice and the chain would net to the wrong figure.
    rid = originals[0]["request_id"]
    payload = raw[rid]
    ln = payload["lines"][0]
    net = (Decimal(ln["line_net_sar"]) * Decimal("0.50")).quantize(Decimal("0.01"))
    ln.update({"line_net_sar": f"{net:.2f}", "unit_price_sar": f"{net / Decimal(ln['qty']):.2f}",
               "line_vat_sar": f"{(net * Decimal('0.15')).quantize(Decimal('0.01')):.2f}"})
    tn = sum((Decimal(x["line_net_sar"]) for x in payload["lines"]), Decimal("0"))
    tv = sum((Decimal(x["line_vat_sar"]) for x in payload["lines"]), Decimal("0"))
    payload.update({"total_excl_vat_sar": f"{tn:.2f}", "vat_total_sar": f"{tv:.2f}",
                    "total_incl_vat_sar": f"{tn + tv:.2f}"})
    again = tmp_path / "reprice2" / "zatca" / "invoice_requests.jsonl"
    again.parent.mkdir(parents=True, exist_ok=True)
    again.write_text(_json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    assert land_invoice_requests(lk, test_keys, again, again.parent.parent)["landed_rows"] == 1

    run_zatca(lk, None)
    docs = lk.read("slv", "zatca_invoice_documents")
    assert docs.count() == before + 8, "a second correction must add exactly one more pair"
    rows = {r["request_id"]: r.asDict() for r in docs.collect()}
    chain = (Decimal(str(rows[rid]["total_incl_vat_sar"]))
             - Decimal(str(rows[f"{rid}-PC1CN"]["total_incl_vat_sar"]))
             + Decimal(str(rows[f"{rid}-PC1RI"]["total_incl_vat_sar"]))
             - Decimal(str(rows[f"{rid}-PC2CN"]["total_incl_vat_sar"]))
             + Decimal(str(rows[f"{rid}-PC2RI"]["total_incl_vat_sar"])))
    assert chain == tn + tv, f"after two corrections the chain nets to {chain}, live amount is {tn + tv}"
    assert (Decimal(str(rows[f"{rid}-PC2CN"]["total_incl_vat_sar"]))
            == Decimal(str(rows[f"{rid}-PC1RI"]["total_incl_vat_sar"]))), (
        "the second cancellation must reverse the first replacement, not the original")


def test_the_price_correction_detector_reads_nothing_when_no_request_was_resent(lake_run, spark):
    """On a normal night nothing has been corrected, and the detector must cost nothing to find that out.

    This guards a performance property, which is the kind that regresses silently: putting the outbox read
    back at the call site "for clarity" would make every nightly run collect all 25,001 chain documents --
    and all 25,000 Bronze payloads -- into the driver to discover that nothing changed. No test would fail;
    the run would just get slower and heavier, on the one resource ADR-008 names as binding first here.

    A tripwire rather than a timer: the lake refuses to hand over ctl.invoice_outbox at all, so the test
    fails if the detector so much as looks at it before establishing that something was resent.
    """
    from mizan.clearance.engine import ChainStore
    from mizan.spark import zatca_land
    from mizan.spark.lake import Lake
    from mizan.spark.session import TableLocator

    class Tripwire:
        """The real lake, except that touching the outbox is an error."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def _check(self, schema, table):
            if (schema, table) == ("ctl", "invoice_outbox"):
                raise AssertionError(
                    "the price-correction detector read the outbox on a run with nothing resent; it must "
                    "establish that a request has more than one Bronze version first")

        def exists(self, schema, table):
            self._check(schema, table)
            return self._inner.exists(schema, table)

        def read(self, schema, table):
            self._check(schema, table)
            return self._inner.read(schema, table)

    lk = Lake(spark, TableLocator("local", lake_run["root"]))
    assert zatca_land._price_corrections(Tripwire(lk), ChainStore()) == []


def zatca_land_flag() -> str:
    from mizan.spark.zatca_land import PRICE_CORRECTION_FLAG
    return PRICE_CORRECTION_FLAG


def test_price_corrections_are_not_issued_unless_explicitly_enabled(lake_run, spark, test_keys, tmp_path,
                                                                    monkeypatch):
    """The gate, proven in the direction that matters: OFF by default, with a correction genuinely pending.

    Measured against the live Fabric tenant on 2026-11-21, one unguarded run would have published **15,492**
    tax documents -- a credit note and a replacement for each of 7,746 invoices -- to correct SAR 2,217.05
    of halala rounding left by this project's own price fix. Whether cancel-and-reissue is even the right
    document type is open (HONESTY row 38), so the default has to be "do not write to the tax chain".

    This is the same lake setup as the test above, with the flag left alone. Nothing may be issued.
    """
    import json as _json
    import shutil
    from decimal import Decimal

    from mizan.clearance.engine import ChainStore
    from mizan.spark.bronze import land_invoice_requests
    from mizan.spark.lake import Lake
    from mizan.spark.session import TableLocator
    from mizan.spark.zatca_land import _price_corrections, run_zatca

    monkeypatch.delenv(zatca_land_flag(), raising=False)

    root = tmp_path / "gated"
    shutil.copytree(lake_run["root"], root, dirs_exist_ok=True)
    lk = Lake(spark, TableLocator("local", root))
    before = lk.read("slv", "zatca_invoice_documents").count()

    outbox = lk.read("ctl", "invoice_outbox").filter("document_type = 'INVOICE'")
    original = outbox.orderBy("request_id").limit(1).collect()[0].asDict()
    payload = next(_json.loads(r["payload_json"])
                   for r in lk.read("brz", "zatca_invoices_raw").collect()
                   if r["request_id"] == original["request_id"])
    ln = payload["lines"][0]
    net = (Decimal(ln["line_net_sar"]) * Decimal("0.70")).quantize(Decimal("0.01"))
    ln.update({"line_net_sar": f"{net:.2f}", "unit_price_sar": f"{net / Decimal(ln['qty']):.2f}",
               "line_vat_sar": f"{(net * Decimal('0.15')).quantize(Decimal('0.01')):.2f}"})
    tn = sum((Decimal(x["line_net_sar"]) for x in payload["lines"]), Decimal("0"))
    tv = sum((Decimal(x["line_vat_sar"]) for x in payload["lines"]), Decimal("0"))
    payload.update({"total_excl_vat_sar": f"{tn:.2f}", "vat_total_sar": f"{tv:.2f}",
                    "total_incl_vat_sar": f"{tn + tv:.2f}"})

    send = tmp_path / "gatedsend" / "zatca" / "invoice_requests.jsonl"
    send.parent.mkdir(parents=True, exist_ok=True)
    send.write_text(_json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    assert land_invoice_requests(lk, test_keys, send, send.parent.parent)["landed_rows"] == 1

    # Detection still works and is still worth running -- it is issuance that is gated.
    assert _price_corrections(lk, ChainStore()) != [], (
        "the fixture did not actually create a pending correction, so this test proves nothing")

    run_zatca(lk, None)
    assert lk.read("slv", "zatca_invoice_documents").count() == before, (
        "price-correction documents were issued with the flag unset; the default must never write to the "
        "tax chain, because the document type itself is still unreviewed (HONESTY row 38)")

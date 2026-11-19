"""Module 2 in the lakehouse: run the ZATCA chain over brz.zatca_invoices_raw and persist the control plane.

  ctl.egs_chain_state, ctl.invoice_outbox (no XML), audit.zatca_chain_journal (signed XML as BINARY, legal hold),
  slv.zatca_invoice_documents, quarantine.zatca_chain_violations.
Re-runs continue each EGS chain from ctl.egs_chain_state and skip requests already in the outbox.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from pyspark.sql import functions as F
from pyspark.sql import types as T

from mizan.clearance.chain_verifier import verify_chain
from mizan.clearance.engine import ChainStore, process_requests
from mizan.clearance.mock_fatoora import MockFatoora
from mizan.spark.lake import Lake, rows_to_df
from mizan.spark.silver import _latest

S, INT, B, D = T.StringType(), T.IntegerType(), T.BinaryType(), T.DecimalType(18, 2)
OUTBOX_SCHEMA = T.StructType([T.StructField(n, t) for n, t in (
    ("invoice_uuid", S), ("request_id", S), ("egs_id", S), ("icv", INT), ("pih", S), ("invoice_hash", S),
    ("qr_tlv_b64", S), ("invoice_flow", S), ("document_type", S), ("order_id", S), ("gl_key", S),
    ("total_incl_vat_sar", D), ("corrects_invoice_uuid", S), ("state", S), ("attempts", INT), ("history_json", S))])
JOURNAL_SCHEMA = T.StructType([T.StructField(n, t) for n, t in (
    ("egs_id", S), ("icv", INT), ("invoice_uuid", S), ("order_id", S), ("pih", S), ("invoice_hash", S),
    ("signed_xml", B), ("legal_hold_class", S), ("retention_status", S))])
VIOLATION_SCHEMA = T.StructType([T.StructField(n, t) for n, t in (
    ("egs_id", S), ("icv", INT), ("invoice_uuid", S), ("violation_type", S), ("detail", S))])


def _hydrate(lake: Lake) -> ChainStore:
    store = ChainStore()
    if lake.exists("ctl", "egs_chain_state"):
        for r in lake.read("ctl", "egs_chain_state").collect():
            store.egs_chain_state[r["egs_id"]] = {"egs_id": r["egs_id"], "last_icv": r["last_icv"],
                                                  "last_invoice_hash": r["last_invoice_hash"]}
    if lake.exists("ctl", "invoice_outbox"):
        for r in lake.read("ctl", "invoice_outbox").select("request_id", "invoice_uuid").collect():
            store.by_request_id[r["request_id"]] = r["invoice_uuid"]
    return store


def run_zatca(lake: Lake, plan_path: Path | None) -> dict:
    spark = lake.spark
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path and plan_path.exists() else {}
    store = _hydrate(lake)
    # _latest, not the raw table: Bronze is append-only, so a corrected re-send leaves TWO rows per
    # request_id and this would hand the engine the superseded payload alongside the current one.
    rows = _latest(lake.read("brz", "zatca_invoices_raw"), ["request_id"]) \
        .select("request_id", "payload_json").collect()
    reqs = sorted((json.loads(r["payload_json"]) for r in rows if r["request_id"] not in store.by_request_id),
                  key=lambda q: q["request_id"])
    run = process_requests(reqs, MockFatoora(plan), store=store)
    new = [r for r in run.store.invoice_outbox.values()]
    if new:
        outbox = rows_to_df(spark, OUTBOX_SCHEMA.names, [{
            **{k: getattr(r, k) for k in OUTBOX_SCHEMA.names if k != "history_json"},
            "history_json": json.dumps(r.history, sort_keys=True)} for r in new],
            {f.name: f.dataType.simpleString() for f in OUTBOX_SCHEMA.fields if f.dataType != S})
        lake.write(outbox.withColumn("updated_at", F.current_timestamp()), "ctl", "invoice_outbox", "append")
        jcols = JOURNAL_SCHEMA.names
        journal = rows_to_df(spark, jcols, [
            {**{k: j[k] for k in jcols if k != "signed_xml"},
             "signed_xml": base64.b64encode(j["signed_xml"]).decode("ascii")}
            for j in run.store.zatca_chain_journal.values()], {"icv": "int", "signed_xml": "binary_b64"})
        lake.write(journal, "audit", "zatca_chain_journal", "append", constraints={
            "hold_class_enum": "legal_hold_class IN ('TAX', 'SAMA', 'CONSENT')"})
    state = rows_to_df(spark, ["egs_id", "last_icv", "last_invoice_hash"],
                       list(run.store.egs_chain_state.values()), {"last_icv": "int"})
    lake.write(state.withColumn("updated_at", F.current_timestamp()), "ctl", "egs_chain_state", "overwrite")

    # slv.zatca_invoice_documents (hop 3) from the outbox + request issue date
    ob = lake.read("ctl", "invoice_outbox")
    # _latest matters more here than anywhere: this is a JOIN key. Two Bronze rows for one request_id fan every
    # outbox row into two, so slv.zatca_invoice_documents silently doubles and every invoice_uuid stops being
    # unique. Found on Fabric 2026-11-19 by `source_unique_..._invoice_uuid` after a price correction re-landed
    # all 25,000 requests as corrections -- the first re-run this pipeline had ever had against real corrections.
    req = _latest(lake.read("brz", "zatca_invoices_raw"), ["request_id"]).select(
        "request_id", F.to_date(F.to_timestamp("issue_ts_utc", "yyyy-MM-dd'T'HH:mm:ssX")).alias("issue_date_ksa"))
    corr_req = req.select(F.concat(F.col("request_id"), F.lit("-C1")).alias("request_id"), "issue_date_ksa")
    docs = ob.join(req.unionByName(corr_req), "request_id", "left").select(
        "invoice_uuid", "request_id", "order_id", "egs_id", "icv", "pih", "invoice_hash", "qr_tlv_b64",
        "invoice_flow", "document_type", "state", "corrects_invoice_uuid", "gl_key", "total_incl_vat_sar",
        "issue_date_ksa", "attempts")
    lake.write(docs, "slv", "zatca_invoice_documents", "overwrite", overwrite_schema=True, constraints={
        "flow_enum": "invoice_flow IN ('CLEARANCE', 'REPORTING')",
        "doc_enum": "document_type IN ('INVOICE', 'CREDIT_NOTE')"})

    journal_rows = [r.asDict() for r in lake.read("audit", "zatca_chain_journal").collect()]
    for r in journal_rows:
        r["signed_xml"] = bytes(r["signed_xml"])
    violations = verify_chain(journal_rows)
    lake.write(rows_to_df(spark, VIOLATION_SCHEMA.names, violations, {"icv": "int"})
               .withColumn("detected_at", F.current_timestamp()), "quarantine", "zatca_chain_violations",
               "overwrite")
    return {"new_documents": len(new), "restarts": run.restarts, "violations": len(violations)}

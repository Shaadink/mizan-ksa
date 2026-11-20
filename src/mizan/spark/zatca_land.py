"""Module 2 in the lakehouse: run the ZATCA chain over brz.zatca_invoices_raw and persist the control plane.

  ctl.egs_chain_state, ctl.invoice_outbox (no XML), audit.zatca_chain_journal (signed XML as BINARY, legal hold),
  slv.zatca_invoice_documents, quarantine.zatca_chain_violations.
Re-runs continue each EGS chain from ctl.egs_chain_state and skip requests already in the outbox.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from pathlib import Path

from pyspark.sql import functions as F
from pyspark.sql import types as T

from mizan.clearance.chain_verifier import verify_chain
from mizan.clearance.engine import ChainStore, price_correction_documents, process_requests
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


def _d(x) -> Decimal:
    return Decimal(str(x))


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


def _outbox_index(lake: Lake) -> dict[str, dict]:
    """request_id -> {invoice_uuid, total, document_type} for every document already in the chain."""
    if not lake.exists("ctl", "invoice_outbox"):
        return {}
    rows = lake.read("ctl", "invoice_outbox").select(
        "request_id", "invoice_uuid", "document_type", "total_incl_vat_sar").collect()
    return {r["request_id"]: {"invoice_uuid": r["invoice_uuid"], "document_type": r["document_type"],
                              "total": str(r["total_incl_vat_sar"])} for r in rows}


def _price_corrections(lake: Lake, outbox: dict[str, dict], store) -> list[dict]:
    """Documents whose price changed AFTER they were signed, as a credit note + replacement pair.

    The invariant, which is what makes this idempotent and what makes repeat corrections work:

        the chain's NET for a request must equal the current Bronze total.

    So the comparison is never "has this ever been corrected" -- that only answers the first time. It is
    "what does the chain currently SAY this invoice is worth", which is the amount on the most recent
    replacement if there is one, and the original otherwise. If that already equals the live payload there
    is nothing to issue. A detector that got this wrong would add two ICVs per invoice per night, for ever.

    Bronze is append-only, so when a price is corrected upstream it holds BOTH the version that was signed
    and the version that is now true. That is what makes this detectable at all -- the engine itself cannot
    see it, because it skips any request_id already in the outbox (correctly: re-pricing a signed tax
    document is forbidden).

    The version to cancel is identified by matching the total the chain currently states, never by "the
    oldest row". If no Bronze version matches, this raises rather than guessing: issuing a credit note for
    an amount the tax authority never received is a worse problem than the gap it was meant to close.
    """
    # The CURRENT version comes from _latest(), never from "the newest issue_ts_utc". A price correction
    # does not change when the sale happened, so both Bronze versions carry the SAME issue timestamp and
    # picking a maximum over it returns an arbitrary one -- which silently selected the superseded payload,
    # found the totals equal, and issued nothing. _latest() orders by _ingested_at / _source_file /
    # _batch_id, which is landing order, which is the only thing that actually distinguishes them. Every
    # other Bronze reader in this module already goes through it; this one has to as well.
    current_by_request = {
        r["request_id"]: json.loads(r["payload_json"])
        for r in _latest(lake.read("brz", "zatca_invoices_raw"), ["request_id"])
        .select("request_id", "payload_json").collect()}
    by_request: dict[str, list[dict]] = {}
    for r in lake.read("brz", "zatca_invoices_raw").select("request_id", "payload_json").collect():
        by_request.setdefault(r["request_id"], []).append(json.loads(r["payload_json"]))

    out: list[dict] = []
    for request_id, versions in sorted(by_request.items()):
        head = outbox.get(request_id)
        if head is None or head["document_type"] != "INVOICE" or len(versions) < 2:
            continue
        # How many corrections has this invoice already had, and what does the chain state today?
        issued = 0
        while f"{request_id}-PC{issued + 1}RI" in outbox:
            issued += 1
        stated = outbox[f"{request_id}-PC{issued}RI"] if issued else head

        current = current_by_request[request_id]
        if _d(current["total_incl_vat_sar"]) == _d(stated["total"]):
            continue                       # the chain already states the live amount
        source = next((v for v in versions if _d(v["total_incl_vat_sar"]) == _d(stated["total"])), None)
        if source is None:
            raise ValueError(
                f"{request_id}: Bronze holds no version matching the amount the chain states "
                f"({stated['total']}); refusing to issue a credit note against an amount that was never sent")
        pair = price_correction_documents(source, current, attempt=issued + 1,
                                          cancels_uuid=stated["invoice_uuid"])
        if pair and pair[0]["request_id"] not in store.by_request_id:
            out.extend(pair)
    return out


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
    # HONESTY row 29: a price corrected after signing must reach the tax chain as DOCUMENTS, because the
    # signed one can never be re-priced. Appended after the new requests so the pair gets the later ICVs.
    corrections = _price_corrections(lake, _outbox_index(lake), store)
    run = process_requests([*reqs, *corrections], MockFatoora(plan), store=store)
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
    # A derived document's request id is the original's plus a suffix, and it inherits the original's issue
    # date. Stripping the suffix rather than unioning one synthetic id per shape: `-C1` (rejection
    # correction) was the only shape until the price-correction pair added `-PC1CN` and `-PC1RI`, and a
    # union would have silently left those two with a NULL issue date -- which would quietly drop them out
    # of every date-filtered tax report rather than fail.
    base_id = F.regexp_replace(F.col("request_id"), r"-(C\d+|PC\d+(CN|RI))$", "")
    docs = ob.withColumn("_base_request_id", base_id) \
             .join(req.withColumnRenamed("request_id", "_base_request_id"), "_base_request_id", "left") \
             .select(
        "invoice_uuid", "request_id", "order_id", "egs_id", "icv", "pih", "invoice_hash", "qr_tlv_b64",
        "invoice_flow", "document_type", "state", "corrects_invoice_uuid", "gl_key", "total_incl_vat_sar",
        "issue_date_ksa", "attempts",
        # Incremental watermark (ADR-015). Deliberately the OUTBOX's updated_at and not the Bronze request's
        # arrival time: a document's STATE is decided here, after the request landed, so Bronze's timestamp
        # would not move when SUBMITTING becomes CLEARED and the incremental ledger would never see the
        # change. The invariant this depends on is stated in the ADR: any write that changes a document's
        # state must set updated_at.
        F.col("updated_at").alias("source_ingested_at"))
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

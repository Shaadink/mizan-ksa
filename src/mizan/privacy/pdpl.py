"""Module 5: PDPL data-subject erasure (crypto-shredding) with legal hold and a Backup Restore Guard.

execute_dsr()
  1. resolve the person to EVERY linked subject token (MDM golden membership + the ID HMAC in Bronze);
  2. decide per token with the spec reference function (fails closed on an unknown legal_hold_class);
  3. security.pii_vault_metadata: wrapped_dek = NULL, SHREDDED, then VACUUM RETAIN 0 HOURS (no time travel);
  4. security.subject_token_map: DELETE the token -> identity link, VACUUM;
  5. ctl.deletion_tombstones: one row per token (the Restore Guard's memory);
  6. audit.zatca_chain_journal is NOT touched: signed tax evidence stays LEGAL_HOLD_RETAINED;
  7. re-resolve MDM (shredded members leave their golden profile), write audit.pdpl_dsr_evidence.

restore_guard() re-applies every tombstone after a restore of data or vault tables, BEFORE anything is served.
"""

from __future__ import annotations

import json
import uuid

from pyspark.sql import functions as F

from mizan.mdm.arabic_norm_and_privacy import ARABIC_INDIC_MAP, execute_pdpl_erasure_decision
from mizan.mdm.engine import PartyRecord, type_identifiers
from mizan.privacy import crypto
from mizan.spark.lake import Lake, rows_to_df
from mizan.spark.mdm_land import now_ksa, run_mdm

TOMBSTONE_COLS = ["subject_token_id", "dsr_id", "legal_hold_class", "tombstoned_at"]
EVIDENCE_COLS = ["dsr_id", "requested_by", "request_basis", "subject_tokens", "golden_ids", "legal_hold_class",
                 "analytical_pii_status", "signed_tax_invoice_status", "journal_rows_retained",
                 "vault_rows_shredded", "token_links_removed", "vault_versions_vacuumed",
                 "tax_totals_before", "tax_totals_after", "executed_at"]


def _vacuum(lake: Lake, schema: str, table: str) -> None:
    lake.spark.sql(f"VACUUM {lake.ref(schema, table)} RETAIN 0 HOURS")


def _tokens_for_identifier(lake: Lake, keys: crypto.Keys, national_id: str) -> set[str]:
    probe = "DSR_LOOKUP"
    ids = type_identifiers(PartyRecord(token=probe, source=probe, party_type="PERSON", created_date="-",
                                       national_id=national_id))
    if not ids:
        return set()
    tid = ids[0]
    h = crypto.identifier_hmac_k(keys.hmac_key, tid.id_type,
                                 tid.canonical or national_id.strip().translate(ARABIC_INDIC_MAP))
    return {r[0] for r in lake.read("brz", "crm_party_raw").filter(F.col("national_id_hmac") == h)
            .select("subject_token_id").distinct().collect()}


def resolve_subject(lake: Lake, keys: crypto.Keys, *, source_ref: str | None = None,
                    national_id: str | None = None) -> tuple[set[str], set[str]]:
    """-> (subject tokens, golden ids). Expands through golden membership so every linked record is erased."""
    tokens: set[str] = set()
    if source_ref:
        tokens.add(crypto.token_for(keys.hmac_key, source_ref))
    if national_id:
        tokens |= _tokens_for_identifier(lake, keys, national_id)
    goldens: set[str] = set()
    if tokens and lake.exists("slv", "golden_party_scd2"):
        for g in lake.read("slv", "golden_party_scd2").filter("is_current AND status = 'ACTIVE'").collect():
            members = set(json.loads(g["member_tokens"]))
            if members & tokens:
                goldens.add(g["golden_id"])
                tokens |= members
    return tokens, goldens


def tax_totals(lake: Lake) -> str:
    """Statutory figures that erasure must never change: invoice count + SAR total, journal rows."""
    d = lake.read("slv", "zatca_invoice_documents").agg(F.count("*").alias("n"),
                                                        F.sum("total_incl_vat_sar").alias("sar")).first()
    j = lake.read("audit", "zatca_chain_journal").count()
    return f"docs={d['n']};sar={d['sar']};journal_rows={j}"


def _orders_of(lake: Lake, tokens: set[str]) -> set[str]:
    if not tokens or not lake.exists("brz", "zatca_invoices_raw"):
        return set()
    return {r[0] for r in lake.read("brz", "zatca_invoices_raw").filter(F.col("subject_token_id").isin(*tokens))
            .select("order_id").distinct().collect()}


def _shred_vault(lake: Lake, tokens: set[str]) -> int:
    from delta.tables import DeltaTable
    if not tokens or not lake.exists("security", "pii_vault_metadata"):
        return 0
    vault = DeltaTable.forPath(lake.spark, lake.path("security", "pii_vault_metadata"))
    cond = F.col("subject_token_id").isin(*tokens) & F.col("wrapped_dek").isNotNull()
    n = vault.toDF().filter(cond).count()
    if n:
        vault.update(condition=cond, set={"wrapped_dek": F.lit(None).cast("binary"), "dek_status": F.lit("SHREDDED")})
    _vacuum(lake, "security", "pii_vault_metadata")          # spec Patch E: no time travel back to the key
    return n


def _unlink_tokens(lake: Lake, tokens: set[str]) -> int:
    from delta.tables import DeltaTable
    if not tokens or not lake.exists("security", "subject_token_map"):
        return 0
    tm = DeltaTable.forPath(lake.spark, lake.path("security", "subject_token_map"))
    cond = F.col("subject_token_id").isin(*tokens)
    n = tm.toDF().filter(cond).count()
    if n:
        tm.delete(cond)
    _vacuum(lake, "security", "subject_token_map")
    return n


def _write_tombstones(lake: Lake, tokens: set[str], dsr_id: str, cls: str, now: str) -> None:
    known = set()
    if lake.exists("ctl", "deletion_tombstones"):
        known = {r[0] for r in lake.read("ctl", "deletion_tombstones").select("subject_token_id").collect()}
    rows = [{"subject_token_id": t, "dsr_id": dsr_id, "legal_hold_class": cls, "tombstoned_at": now}
            for t in sorted(tokens - known)]
    if rows:
        lake.write(rows_to_df(lake.spark, TOMBSTONE_COLS, rows), "ctl", "deletion_tombstones", "append",
                   constraints={"hold_enum": "legal_hold_class IN ('TAX', 'SAMA', 'CONSENT')"})


def execute_dsr(lake: Lake, keys: crypto.Keys | None = None, *, source_ref: str | None = None,
                national_id: str | None = None, legal_hold_class: str | None = None,
                requested_by: str = "dpo@najd.example", dsr_id: str | None = None) -> dict:
    """Erase one person. legal_hold_class defaults to TAX when the person has invoices, else CONSENT; any value
    is checked by the reference function, which refuses unknown classes before anything is changed."""
    keys = keys or crypto.Keys.from_env()
    now = now_ksa()
    tokens, goldens = resolve_subject(lake, keys, source_ref=source_ref, national_id=national_id)
    if not tokens:
        raise LookupError("no subject found for this request")
    orders = _orders_of(lake, tokens)
    cls = legal_hold_class if legal_hold_class is not None else ("TAX" if orders else "CONSENT")
    dsr_id = dsr_id or "DSR-" + uuid.uuid4().hex[:12].upper()

    vault_view = {t: {"wrapped_dek": b"", "status": "ACTIVE"} for t in tokens}
    tombstones: set[str] = set()
    token_map = dict.fromkeys(tokens, "linked")
    decisions = [execute_pdpl_erasure_decision(t, cls, vault_view, tombstones, token_map) for t in sorted(tokens)]

    before = tax_totals(lake)
    shredded = _shred_vault(lake, tokens)
    unlinked = _unlink_tokens(lake, tokens)
    _write_tombstones(lake, tombstones, dsr_id, cls.strip().upper(), now)
    journal_rows = (lake.read("audit", "zatca_chain_journal").filter(F.col("order_id").isin(*orders)).count()
                    if orders else 0)
    mdm = run_mdm(lake, keys, now)
    after = tax_totals(lake)
    hist = lake.spark.sql(f"DESCRIBE HISTORY {lake.ref('security', 'pii_vault_metadata')}").count()
    ev = {"dsr_id": dsr_id, "requested_by": requested_by,
          "request_basis": "NATIONAL_ID" if national_id else "SOURCE_REF",
          "subject_tokens": json.dumps(sorted(tokens)), "golden_ids": json.dumps(sorted(goldens)),
          "legal_hold_class": cls.strip().upper(),
          "analytical_pii_status": decisions[0]["analytical_pii_status"],
          "signed_tax_invoice_status": decisions[0]["signed_tax_invoice_status"],
          "journal_rows_retained": journal_rows, "vault_rows_shredded": shredded, "token_links_removed": unlinked,
          "vault_versions_vacuumed": hist, "tax_totals_before": before, "tax_totals_after": after,
          "executed_at": now}
    lake.write(rows_to_df(lake.spark, EVIDENCE_COLS, [ev], {
        "journal_rows_retained": "int", "vault_rows_shredded": "int", "token_links_removed": "int",
        "vault_versions_vacuumed": "int"}), "audit", "pdpl_dsr_evidence", "append")
    return {**ev, "mdm": mdm, "tokens": sorted(tokens)}


def restore_guard(lake: Lake, keys: crypto.Keys | None = None) -> dict:
    """Run after ANY restore (Delta RESTORE, backup copy, time-travel rollback) and before serving: every tombstoned
    subject is shredded and unlinked again, and MDM is re-resolved so a restored golden row cannot serve them."""
    if not lake.exists("ctl", "deletion_tombstones"):
        return {"tombstones": 0, "keys_reshredded": 0, "links_removed": 0}
    tombs = {r[0] for r in lake.read("ctl", "deletion_tombstones").select("subject_token_id").collect()}
    reshredded = _shred_vault(lake, tombs)
    unlinked = _unlink_tokens(lake, tombs)
    resurrected_goldens = 0
    if lake.exists("slv", "golden_party_scd2"):
        for g in lake.read("slv", "golden_party_scd2").filter("is_current AND status = 'ACTIVE'").collect():
            if set(json.loads(g["member_tokens"])) & tombs:
                resurrected_goldens += 1
    mdm = run_mdm(lake, keys) if (reshredded or unlinked or resurrected_goldens) else None
    return {"tombstones": len(tombs), "keys_reshredded": reshredded, "links_removed": unlinked,
            "goldens_reresolved": resurrected_goldens, "mdm": mdm}

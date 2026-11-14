"""Module 4 in the lakehouse: resolve brz.crm_party_raw into golden profiles and persist them.

Writes slv.golden_party_scd2, slv.identifier_registry, slv.entity_merge_ledger (append-only),
slv.address_observations (SPL 4L+4D) and quarantine.mdm_match_conflicts.

PII is decrypted only in driver memory, per subject, with that subject's DEK; nothing written here holds
cleartext: identifiers and phones are keyed HMACs, the surviving legal name is the Bronze ciphertext (so a
crypto-shred of the source subject makes the golden name unreadable too). Shredded subjects are skipped.
Resolution runs on the driver (5K records here); see HONESTY.md for the scale boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from pyspark.sql import Window
from pyspark.sql import functions as F

from mizan.mdm import engine as E
from mizan.privacy import crypto
from mizan.spark.lake import Lake, rows_to_df

SPL_RE = re.compile(r"[A-Z]{4}[0-9]{4}")          # SPL National Short Address: 4 letters + 4 digits
GOLDEN_COLS = ["golden_id", "version", "party_type", "anchor_id_type", "anchor_hmac", "member_tokens",
               "member_count", "name_ar_enc", "name_ar_source_token", "name_en_enc", "name_en_source_token", "city",
               "attr_hash", "status", "change_reason", "valid_from", "valid_to", "is_current",
               "search_key_version"]
LEDGER_COLS = ["merge_event_id", "event_seq", "golden_id", "subject_token_id", "action", "match_rule", "evidence",
               "actor", "event_ts"]
CONFLICT_COLS = ["conflict_id", "subject_token_id", "conflict_type", "candidate_golden_ids", "evidence", "status",
                 "detected_at"]
REGISTRY_COLS = ["id_type", "identifier_hmac", "golden_id", "validation_status", "is_anchor", "record_count"]
ADDRESS_COLS = ["observation_id", "source_system", "subject_token_id", "golden_id", "short_address_hmac",
                "short_address_enc", "format_status", "region_letter", "district", "city", "postal_code",
                "observed_date", "is_current_for_golden"]


def now_ksa() -> str:
    return datetime.now(ZoneInfo("Asia/Riyadh")).replace(microsecond=0).isoformat()


def _latest(df, key: str):
    w = Window.partitionBy(key).orderBy(F.col("_ingested_at").desc(), F.col("_row_num").desc())
    return df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")


def _active_deks(lake: Lake, keys: crypto.Keys) -> dict[str, bytes]:
    out = {}
    for r in lake.read("security", "pii_vault_metadata").select(
            "subject_token_id", "wrapped_dek", "dek_status").collect():
        if r["dek_status"] == "ACTIVE" and r["wrapped_dek"] is not None:
            out[r["subject_token_id"]] = crypto.unwrap_dek(keys, r["subject_token_id"], bytes(r["wrapped_dek"]))
    return out


def load_party_records(lake: Lake, keys: crypto.Keys) -> tuple[list[E.PartyRecord], int]:
    """Latest Bronze row per subject, decrypted in memory. Returns (records, shredded_skipped)."""
    deks = _active_deks(lake, keys)
    raw = _latest(lake.read("brz", "crm_party_raw"), "subject_token_id")
    cols = set(raw.columns)
    out, skipped = [], 0
    for r in raw.collect():
        t = r["subject_token_id"]
        dek = deks.get(t)
        if dek is None:
            skipped += 1
            continue

        def dec(col: str, row=r, token=t, key=dek) -> str | None:
            return crypto.decrypt_field(key, token, col, row[f"{col}_enc"]) if f"{col}_enc" in cols else None

        out.append(E.PartyRecord(
            token=t, source=r["_source"], party_type=r["party_type"], created_date=r["created_date"],
            name_ar=dec("full_name_ar"), name_en=dec("full_name_en"), national_id=dec("national_id"),
            mobile=dec("mobile"), landline=dec("landline"), vat_number=r["vat_number"] if "vat_number" in cols
            else None, unified_700=r["unified_700"] if "unified_700" in cols else None, city=r["city"],
            name_encoding_status=r["name_ar_encoding_status"], name_ar_enc=r["full_name_ar_enc"],
            name_en_enc=r["full_name_en_enc"]))
    return out, skipped


def _attr_hash(g: dict) -> str:
    keep = {k: g[k] for k in ("party_type", "anchor_id_type", "anchor_hmac", "member_tokens", "name_ar_enc",
                              "name_en_enc", "city")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode("utf-8")).hexdigest()


def scd2_rows(prior: list[dict], goldens: list[dict], now: str) -> tuple[list[dict], dict]:
    """Close changed / retired versions, open new ones. Unchanged goldens keep their current row."""
    rows = [dict(p) for p in prior]
    current = {p["golden_id"]: p for p in rows if p["is_current"]}
    seen, opened, closed = set(), 0, 0
    for g in goldens:
        h = _attr_hash(g)
        seen.add(g["golden_id"])
        cur = current.get(g["golden_id"])
        if cur is not None and cur["attr_hash"] == h and cur["status"] == "ACTIVE":
            continue
        if cur is not None:
            cur.update(is_current=False, valid_to=now)
            closed += 1
        rows.append({**g, "version": (cur["version"] + 1) if cur else 1, "attr_hash": h, "status": "ACTIVE",
                     "change_reason": "MEMBERSHIP_OR_ATTRIBUTE_CHANGE" if cur else "CREATED", "valid_from": now,
                     "valid_to": None, "is_current": True, "search_key_version": E.SEARCH_KEY_VERSION})
        opened += 1
    for gid, cur in current.items():
        if gid not in seen and cur["status"] == "ACTIVE":
            cur.update(is_current=False, valid_to=now)
            rows.append({**cur, "version": cur["version"] + 1, "status": "RETIRED", "member_tokens": "[]",
                         "member_count": 0, "change_reason": "ALL_MEMBERS_MOVED", "valid_from": now,
                         "valid_to": None, "is_current": True})
            closed += 1
            opened += 1
    return rows, {"versions_opened": opened, "versions_closed": closed}


def address_rows(lake: Lake, keys: crypto.Keys, membership: dict[str, str]) -> list[dict]:
    if not lake.exists("brz", "spl_address_raw"):
        return []
    deks = _active_deks(lake, keys)
    out = []
    for r in _latest(lake.read("brz", "spl_address_raw"), "observation_id").collect():
        t = r["subject_token_id"]
        dek = deks.get(t)
        if dek is None:
            continue          # shredded subject: the observation is no longer resolvable
        sa = re.sub(r"\s+", "", crypto.decrypt_field(dek, t, "short_address", r["short_address_enc"]) or "")
        sa = sa.upper()   # canonical form: 'ratg 5175' -> 'RATG5175'
        ok = bool(SPL_RE.fullmatch(sa))
        out.append({"observation_id": r["observation_id"], "source_system": r["source_system"],
                    "subject_token_id": t, "golden_id": membership.get(t),
                    "short_address_hmac": crypto.identifier_hmac_k(keys.hmac_key, "SPL_SHORT_ADDRESS", sa)
                    if sa else None,
                    "short_address_enc": r["short_address_enc"], "format_status": "VALID_4L4D" if ok
                    else "INVALID_FORMAT", "region_letter": sa[0] if ok else None, "district": r["district"],
                    "city": r["city"], "postal_code": r["postal_code"], "observed_date": r["observed_date"],
                    "is_current_for_golden": False})
    latest: dict[str, dict] = {}
    for o in out:
        if o["golden_id"] and o["format_status"] == "VALID_4L4D":
            best = latest.get(o["golden_id"])
            if best is None or (o["observed_date"], o["observation_id"]) > (best["observed_date"],
                                                                             best["observation_id"]):
                latest[o["golden_id"]] = o
    for o in latest.values():
        o["is_current_for_golden"] = True
    return sorted(out, key=lambda o: o["observation_id"])


def _read_rows(lake: Lake, schema: str, table: str) -> list[dict]:
    return [r.asDict() for r in lake.read(schema, table).collect()] if lake.exists(schema, table) else []


def run_mdm(lake: Lake, keys: crypto.Keys | None = None, now: str | None = None) -> dict:
    keys = keys or crypto.Keys.from_env()
    now = now or now_ksa()
    spark = lake.spark
    records, skipped = load_party_records(lake, keys)
    prior_ledger = _read_rows(lake, "slv", "entity_merge_ledger")
    prior_conflicts = _read_rows(lake, "quarantine", "mdm_match_conflicts")
    res = E.resolve(records, lambda purpose, v: crypto.identifier_hmac_k(keys.hmac_key, purpose, v),
                    prior_ledger, prior_conflicts, now)

    if res.ledger_new:
        lake.write(rows_to_df(spark, LEDGER_COLS, res.ledger_new, {"event_seq": "long"}),
                   "slv", "entity_merge_ledger", "append", constraints={
                       "action_enum": "action IN ('MERGE', 'UNMERGE')",
                       "rule_enum": "match_rule IN (" + ", ".join(f"'{x}'" for x in E.MATCH_RULES) + ")"})
    elif not lake.exists("slv", "entity_merge_ledger"):
        lake.write(rows_to_df(spark, LEDGER_COLS, [], {"event_seq": "long"}), "slv", "entity_merge_ledger")

    golden_rows, scd = scd2_rows(_read_rows(lake, "slv", "golden_party_scd2"), res.goldens, now)
    lake.write(rows_to_df(spark, GOLDEN_COLS, golden_rows, {"version": "int", "member_count": "int",
                                                            "is_current": "boolean"}),
               "slv", "golden_party_scd2", "overwrite", overwrite_schema=True, constraints={
                   "status_enum": "status IN ('ACTIVE', 'RETIRED')",
                   "party_type_enum": "party_type IN ('PERSON', 'ORGANIZATION')"})
    lake.write(rows_to_df(spark, REGISTRY_COLS, res.registry, {"is_anchor": "boolean", "record_count": "int"}),
               "slv", "identifier_registry", "overwrite", overwrite_schema=True, constraints={
                   "id_type_enum": "id_type IN (" + ", ".join(f"'{x}'" for x in E.ID_TYPES) + ")"})
    lake.write(rows_to_df(spark, CONFLICT_COLS, res.conflicts), "quarantine", "mdm_match_conflicts", "overwrite",
               overwrite_schema=True)
    addr = address_rows(lake, keys, res.membership)
    lake.write(rows_to_df(spark, ADDRESS_COLS, addr, {"is_current_for_golden": "boolean"}),
               "slv", "address_observations", "overwrite", overwrite_schema=True)
    return {**res.stats, **scd, "shredded_skipped": skipped, "address_observations": len(addr),
            "addresses_unresolved": sum(1 for a in addr if a["golden_id"] is None)}


def apply_steward_decision(lake: Lake, token: str, golden_id: str, action: str, actor: str, reason: str,
                           keys: crypto.Keys | None = None) -> dict:
    """Record a steward decision in the ledger, then re-resolve so golden profiles reflect it."""
    prior = _read_rows(lake, "slv", "entity_merge_ledger")
    ev = E.steward_event(prior, token, golden_id, action, actor, reason, now_ksa())
    lake.write(rows_to_df(lake.spark, LEDGER_COLS, [ev], {"event_seq": "long"}), "slv", "entity_merge_ledger",
               "append")
    return run_mdm(lake, keys)

"""Bronze landing (LH_MIZAN.brz) with encrypt-on-land, contracts, dedup and source-to-Bronze reconciliation.

Split of work (ADR-008): Python does what only Python should; Spark does the set work, with ZERO Python UDFs.
  Python adapter, per file:
    1. read BYTES, sha256 them, compare with the generator's _control.json (source-to-Bronze hash rec);
    2. decode (utf-8 strict, or cp1256 for the legacy POS CRM) and parse CSV; header must equal the contract;
    3. CP1256 repair (3 cases), subject ref -> HMAC subject_token_id, PII -> AES-256-GCM under the subject DEK,
       business key -> HMAC when the key is itself an identifier;
    4. write a CIPHERTEXT-ONLY UTF-8 staging CSV (cleartext PII never touches disk or a table).
  Spark, per file:
    5. read the staged CSV natively; contract checks -> quarantine.schema_rejections;
    6. ctl.applied_event_ledger: identical (business key, payload hash) already applied -> duplicate, skipped;
       same key with a new payload -> lands as a correction;
    7. append brz.<table>, append ledger rows, one ctl.ingestion_watermarks row per file.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path

from pyspark.sql import Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from mizan.ingest.cp1256 import decode_cp1256_bytes, repair_text
from mizan.mdm.arabic_norm_and_privacy import ARABIC_INDIC_MAP
from mizan.privacy import crypto
from mizan.spark.contracts import Contract
from mizan.spark.lake import Lake, rows_to_df

VAULT_PROPS = {"delta.deletedFileRetentionDuration": "interval 0 hours"}  # spec Patch E
UNIT_SEP = chr(31)
REJECT_COLS = ("source", "batch_id", "source_file", "row_num", "event_key", "payload_hash", "reject_reason",
               "payload_json")


# ----------------------------------------------------------------------------- file reading

def read_source_file(path: Path, contract: Contract) -> tuple[str, list[str], list[dict]]:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    text = decode_cp1256_bytes(raw) if contract.encoding == "cp1256" else raw.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    return sha, list(reader.fieldnames or []), rows


def _control(data_dir: Path) -> dict:
    p = data_dir / "_control.json"
    return json.loads(p.read_text(encoding="utf-8"))["files"] if p.exists() else {}


def _stage_dir() -> Path:
    base = Path(__file__).resolve().parents[3] / "tmp" / "staging"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=base))


def _write_stage(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _read_stage(spark, path: Path, columns: list[str]):
    schema = T.StructType([T.StructField(c, T.StringType()) for c in columns])
    return (spark.read.option("header", "true").option("multiLine", "true").option("escape", '"')
            .option("encoding", "UTF-8").schema(schema).csv(path.as_posix()))


# ----------------------------------------------------------------------------- vault (Phase 3 part)

def ensure_deks(lake: Lake, keys: crypto.Keys, tokens) -> dict[str, bytes]:
    """token -> DEK for every token; new subjects get a fresh DEK wrapped into security.pii_vault_metadata
    (zero deleted-file retention). Shredded subjects get no DEK at all, so nothing new can be landed for them."""
    spark = lake.spark
    existing: dict[str, bytes | None] = {}
    if lake.exists("ctl", "deletion_tombstones"):      # Restore Guard: an erased subject never gets a key again
        for r in lake.read("ctl", "deletion_tombstones").select("subject_token_id").collect():
            existing[r["subject_token_id"]] = None
    if lake.exists("security", "pii_vault_metadata"):
        for r in lake.read("security", "pii_vault_metadata").select(
                "subject_token_id", "wrapped_dek", "dek_status").collect():
            if r["subject_token_id"] in existing and existing[r["subject_token_id"]] is None:
                continue                                 # tombstoned: ignore any (restored) key
            existing[r["subject_token_id"]] = (bytes(r["wrapped_dek"]) if r["dek_status"] == "ACTIVE"
                                               and r["wrapped_dek"] is not None else None)
    out: dict[str, bytes] = {}
    new_rows = []
    for t in sorted(set(tokens)):
        if t in existing:
            if existing[t] is not None:
                out[t] = crypto.unwrap_dek(keys, t, existing[t])
            continue
        dek = crypto.new_dek()
        out[t] = dek
        new_rows.append({"subject_token_id": t,
                         "wrapped_dek_b64": base64.b64encode(crypto.wrap_dek(keys, t, dek)).decode(),
                         "kek_version": keys.kek_version, "dek_status": "ACTIVE"})
    if new_rows:
        cols = ["subject_token_id", "wrapped_dek_b64", "kek_version", "dek_status"]
        df = rows_to_df(spark, cols, new_rows).select(
            "subject_token_id", F.unbase64("wrapped_dek_b64").alias("wrapped_dek"), "kek_version", "dek_status",
            F.current_timestamp().alias("created_at"))
        first = not lake.exists("security", "pii_vault_metadata")
        lake.write(df, "security", "pii_vault_metadata", "append",
                   props=VAULT_PROPS if first else None,
                   constraints={"dek_status_enum": "dek_status IN ('ACTIVE', 'SHREDDED')"} if first else None)
    return out


def ensure_token_map(lake: Lake, keys: crypto.Keys, refs: dict[str, tuple[str, str]]) -> int:
    """security.subject_token_map: token -> source identity, encrypted under the KEK (purpose-bound). This is the
    re-identification link; PDPL erasure DELETES the row. Tombstoned subjects are never re-linked."""
    if not refs:
        return 0
    known: set[str] = set()
    for schema, table in (("security", "subject_token_map"), ("ctl", "deletion_tombstones")):
        if lake.exists(schema, table):
            known |= {r[0] for r in lake.read(schema, table).select("subject_token_id").collect()}
    rows = [{"subject_token_id": t, "source_system": src,
             "source_ref_enc": crypto.encrypt_with_kek(keys, f"TOKEN_MAP|{t}", ref)}
            for t, (src, ref) in sorted(refs.items()) if t not in known]
    if rows:
        df = rows_to_df(lake.spark, ["subject_token_id", "source_system", "source_ref_enc"], rows)
        df = df.withColumn("created_at", F.current_timestamp())
        first = not lake.exists("security", "subject_token_map")
        lake.write(df, "security", "subject_token_map", "append", props=VAULT_PROPS if first else None)
    return len(rows)


# ----------------------------------------------------------------------------- python adapter

def _prepare_rows(lake: Lake, keys: crypto.Keys, c: Contract, rows: list[dict]) -> tuple[list[str], list[dict]]:
    """Repair, tokenise, encrypt. Returns (staged columns, staged rows) with no cleartext PII."""
    is_crm = c.source in ("crm_pos", "crm_ecom")
    keep = [x for x in c.columns if x not in c.pii and x != c.subject_col]
    extra = []
    if c.subject_col:
        extra.append("subject_token_id")
    if is_crm:
        extra += ["name_ar_encoding_status", "id_type", "national_id_hmac"]
    enc_cols = [f"{p}_enc" for p in c.pii]
    staged_cols = ["_row_num", *keep, *extra, *enc_cols, "_event_key", "_payload_hash"]

    tokens = {crypto.token_for(keys.hmac_key, r.get(c.subject_col)) for r in rows} if c.subject_col else set()
    tokens.discard(None)
    deks = ensure_deks(lake, keys, tokens) if tokens else {}
    if c.subject_col:
        ensure_token_map(lake, keys, {crypto.token_for(keys.hmac_key, r[c.subject_col]): (c.source, r[c.subject_col])
                                      for r in rows if r.get(c.subject_col)})
    clean_status = "DECODED_CP1256" if c.encoding == "cp1256" else "CLEAN"
    hash_key = c.subject_col is not None  # rows that carried PII get an HMAC'd payload hash

    out = []
    for n, r in enumerate(rows, start=1):
        r = {k: (v if v != "" else None) for k, v in r.items()}
        payload = UNIT_SEP.join(r.get(x) or "" for x in c.columns)
        event_key = "|".join(r.get(k) or "" for k in c.key)
        s = {x: r.get(x) for x in keep}
        s["_row_num"] = n
        s["_payload_hash"] = (crypto.hmac_hex(keys.hmac_key, "ROW|" + payload) if hash_key
                              else hashlib.sha256(payload.encode("utf-8")).hexdigest())
        s["_event_key"] = crypto.key_hmac(keys.hmac_key, event_key) if c.subject_col in c.key else event_key
        if is_crm:
            text, status = repair_text(r.get("full_name_ar"))
            r["full_name_ar"] = text
            s["name_ar_encoding_status"] = clean_status if status == "CLEAN" and text else status
            nid = (r.get("national_id") or "").strip().translate(ARABIC_INDIC_MAP)
            if nid:
                s["id_type"] = {"1": "NATIONAL_ID", "2": "IQAMA"}.get(nid[0], "UNKNOWN")
                s["national_id_hmac"] = crypto.identifier_hmac_k(keys.hmac_key, s["id_type"], nid)
        if c.subject_col:
            token = crypto.token_for(keys.hmac_key, r.get(c.subject_col))
            s["subject_token_id"] = token
            dek = deks.get(token) if token else None
            for p in c.pii:
                # no subject or a shredded subject: the field is NOT landed (never cleartext)
                s[f"{p}_enc"] = crypto.encrypt_field(dek, token, p, r.get(p)) if dek else None
        out.append(s)
    return staged_cols, out


# ----------------------------------------------------------------------------- contract checks (Spark)

def _reasons(c: Contract):
    conds = []
    for col in c.required:
        target = ("subject_token_id" if col == c.subject_col
                  else f"{col}_enc" if col in c.pii else col)  # PII is only present encrypted
        conds.append(F.when(F.col(target).isNull() | (F.trim(F.col(target)) == ""), F.lit(f"MISSING:{col}")))
    for col, vals in c.enums.items():
        conds.append(F.when(F.col(col).isNotNull() & ~F.col(col).isin(*vals), F.lit(f"BAD_ENUM:{col}")))
    for col, rx in c.patterns.items():
        conds.append(F.when(F.col(col).isNotNull() & ~F.col(col).rlike(rx), F.lit(f"BAD_FORMAT:{col}")))
    if c.source in ("crm_pos", "crm_ecom"):
        conds.append(F.when(F.col("name_ar_encoding_status") == "UNRECOVERABLE",
                            F.lit("CP1256_UNRECOVERABLE:full_name_ar")))
    return F.concat_ws(";", *conds)


# ----------------------------------------------------------------------------- landing

def land_files(lake: Lake, keys: crypto.Keys, contract: Contract, files: list[Path], data_dir: Path) -> list[dict]:
    """Land files for one contract. Returns one stats dict per file (also written to ctl.ingestion_watermarks)."""
    control = _control(data_dir)
    stats: list[dict] = []
    for seq, path in enumerate(sorted(files)):
        rel = path.relative_to(data_dir).as_posix()
        sha, header, rows = read_source_file(path, contract)
        batch_id = f"{contract.source}:{sha[:12]}:{seq}"
        ctl_sha = control.get(rel, {}).get("sha256")
        st = {"source": contract.source, "batch_id": batch_id, "source_file": rel, "file_sha256": sha,
              "control_sha256": ctl_sha, "sha_match": (ctl_sha == sha) if ctl_sha else None,
              "source_rows": len(rows), "landed_rows": 0, "duplicate_rows": 0, "rejected_rows": 0,
              "corrections": 0, "status": "LOADED"}
        if tuple(header) != contract.columns:
            st.update(status="REJECTED_SCHEMA_DRIFT", rejected_rows=len(rows))
            _write_rejections(lake, [{"source": contract.source, "batch_id": batch_id, "source_file": rel,
                                      "row_num": None, "event_key": None, "payload_hash": sha,
                                      "reject_reason": f"SCHEMA_DRIFT: header {header}", "payload_json": None}])
        else:
            st.update(_land_rows(lake, keys, contract, rows, batch_id, rel, sha))
        stats.append(st)
    _write_watermarks(lake, stats)
    return stats


def _land_rows(lake: Lake, keys: crypto.Keys, c: Contract, rows: list[dict], batch_id: str, rel: str,
               sha: str) -> dict:
    spark = lake.spark
    staged_cols, staged = _prepare_rows(lake, keys, c, rows)
    stage = _stage_dir()
    _write_stage(stage / "rows.csv", staged_cols, staged)
    df = _read_stage(spark, stage / "rows.csv", staged_cols).withColumn("_row_num", F.col("_row_num").cast("long"))
    df = df.withColumn("_reject_reason", _reasons(c)).cache()

    rejected = df.filter(F.col("_reject_reason") != "")
    n_rejected = rejected.count()
    if n_rejected:
        data_cols = [x for x in staged_cols if not x.startswith("_")]
        q = rejected.select(
            F.lit(c.source).alias("source"), F.lit(batch_id).alias("batch_id"), F.lit(rel).alias("source_file"),
            F.col("_row_num").alias("row_num"), F.col("_event_key").alias("event_key"),
            F.col("_payload_hash").alias("payload_hash"), F.col("_reject_reason").alias("reject_reason"),
            F.to_json(F.struct(*[F.col(x) for x in data_cols])).alias("payload_json"),
            F.current_timestamp().alias("rejected_at"))
        if lake.exists("quarantine", "schema_rejections"):   # a replayed bad row is quarantined once, not twice
            seen = lake.read("quarantine", "schema_rejections").filter(F.col("source") == c.source)
            if "payload_hash" in seen.columns:
                q = q.join(seen.select("event_key", "payload_hash"), ["event_key", "payload_hash"], "left_anti")
        lake.write(q, "quarantine", "schema_rejections", "append", merge_schema=True)

    valid = df.filter(F.col("_reject_reason") == "")
    w = Window.partitionBy("_event_key", "_payload_hash").orderBy("_row_num")
    valid = valid.withColumn("_rn", F.row_number().over(w))
    in_file_dupes = valid.filter(F.col("_rn") > 1).count()
    valid = valid.filter(F.col("_rn") == 1).drop("_rn")
    dupes, n_corrections = in_file_dupes, 0
    if lake.exists("ctl", "applied_event_ledger"):
        ledger = lake.read("ctl", "applied_event_ledger").filter(F.col("source") == c.source) \
                     .select(F.col("event_key").alias("_event_key"), F.col("payload_hash").alias("_payload_hash"))
        before = valid.count()
        valid = valid.join(ledger, ["_event_key", "_payload_hash"], "left_anti")
        seen_keys = ledger.select("_event_key").distinct().withColumn("_is_correction", F.lit(True))
        valid = valid.join(seen_keys, ["_event_key"], "left") \
                     .withColumn("_is_correction", F.coalesce(F.col("_is_correction"), F.lit(False))).cache()
        dupes += before - valid.count()
        n_corrections = valid.filter("_is_correction").count()
    else:
        valid = valid.withColumn("_is_correction", F.lit(False)).cache()
    n_new = valid.count()
    result = {"landed_rows": n_new, "duplicate_rows": dupes, "rejected_rows": n_rejected,
              "corrections": n_corrections, "status": "LOADED"}
    if n_new == 0:
        result["status"] = "ALL_DUPLICATE" if dupes else "EMPTY"
    else:
        out = (valid.drop("_reject_reason").withColumn("_batch_id", F.lit(batch_id))
               .withColumn("_source_file", F.lit(rel)).withColumn("_file_sha256", F.lit(sha))
               .withColumn("_source", F.lit(c.source)).withColumn("_ingested_at", F.current_timestamp()))
        lake.write(out, "brz", c.table, "append", merge_schema=True)  # shared raw tables evolve by name
        lake.write(valid.select(F.lit(c.source).alias("source"), F.col("_event_key").alias("event_key"),
                                F.col("_payload_hash").alias("payload_hash"), F.lit(batch_id).alias("batch_id"),
                                F.lit(rel).alias("source_file"), F.current_timestamp().alias("applied_at")),
                   "ctl", "applied_event_ledger", "append")
    df.unpersist()
    valid.unpersist()
    shutil.rmtree(stage, ignore_errors=True)
    return result


def _write_rejections(lake: Lake, rows: list[dict]) -> None:
    df = rows_to_df(lake.spark, list(REJECT_COLS), rows, {"row_num": "long"}) \
        .withColumn("rejected_at", F.current_timestamp())
    lake.write(df, "quarantine", "schema_rejections", "append", merge_schema=True)


WATERMARK_FIELDS = (("source", "string"), ("batch_id", "string"), ("source_file", "string"),
                    ("file_sha256", "string"), ("control_sha256", "string"), ("sha_match", "boolean"),
                    ("source_rows", "long"), ("landed_rows", "long"), ("duplicate_rows", "long"),
                    ("rejected_rows", "long"), ("corrections", "long"), ("status", "string"))


def _write_watermarks(lake: Lake, stats: list[dict]) -> None:
    if not stats:
        return
    names = [n for n, _ in WATERMARK_FIELDS]
    df = rows_to_df(lake.spark, names, stats, {n: t for n, t in WATERMARK_FIELDS if t != "string"}) \
        .withColumn("loaded_at", F.current_timestamp())
    lake.write(df, "ctl", "ingestion_watermarks", "append")


# ----------------------------------------------------------------------------- ZATCA requests (JSONL)

ZATCA_COLS = ("request_id", "invoice_uuid", "document_type", "invoice_flow", "egs_id", "order_id", "merchant_id",
              "issue_ts_utc")


def land_invoice_requests(lake: Lake, keys: crypto.Keys, path: Path, data_dir: Path) -> dict:
    """brz.zatca_invoices_raw: UNSIGNED requests (ADR-001). customer_ref -> subject_token_id; payload kept as JSON
    without customer_ref (B2B buyers are organisations, not natural persons)."""
    spark = lake.spark
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    rel = path.relative_to(data_dir).as_posix()
    batch_id = f"zatca_requests:{sha[:12]}:0"
    reqs = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    cols = [*ZATCA_COLS, "subject_token_id", "payload_json", "_payload_hash"]
    staged = []
    for q in reqs:
        payload_json = json.dumps({k: v for k, v in q.items() if k != "customer_ref"}, sort_keys=True,
                                  ensure_ascii=False)
        staged.append({**{k: q[k] for k in ZATCA_COLS},
                       "subject_token_id": crypto.token_for(keys.hmac_key, q.get("customer_ref")),
                       "payload_json": payload_json,
                       "_payload_hash": hashlib.sha256(payload_json.encode()).hexdigest()})
    ensure_token_map(lake, keys, {crypto.token_for(keys.hmac_key, q["customer_ref"]): ("zatca_requests",
                                                                                      q["customer_ref"])
                                  for q in reqs if q.get("customer_ref")})
    stage = _stage_dir()
    _write_stage(stage / "zatca.csv", cols, staged)
    df = _read_stage(spark, stage / "zatca.csv", cols)
    if lake.exists("ctl", "applied_event_ledger"):
        ledger = lake.read("ctl", "applied_event_ledger").filter(F.col("source") == "zatca_requests")
        df = df.join(ledger.select(F.col("event_key").alias("request_id"),
                                   F.col("payload_hash").alias("_payload_hash")),
                     ["request_id", "_payload_hash"], "left_anti")
    df = df.cache()
    n_new = df.count()
    if n_new:
        lake.write(df.withColumn("_batch_id", F.lit(batch_id)).withColumn("_source_file", F.lit(rel))
                     .withColumn("_file_sha256", F.lit(sha)).withColumn("_ingested_at", F.current_timestamp()),
                   "brz", "zatca_invoices_raw", "append")
        lake.write(df.select(F.lit("zatca_requests").alias("source"), F.col("request_id").alias("event_key"),
                             F.col("_payload_hash").alias("payload_hash"), F.lit(batch_id).alias("batch_id"),
                             F.lit(rel).alias("source_file"), F.current_timestamp().alias("applied_at")),
                   "ctl", "applied_event_ledger", "append")
    df.unpersist()
    shutil.rmtree(stage, ignore_errors=True)
    control = _control(data_dir).get(rel, {})
    st = {"source": "zatca_requests", "batch_id": batch_id, "source_file": rel, "file_sha256": sha,
          "control_sha256": control.get("sha256"), "sha_match": (control.get("sha256") == sha) if control else None,
          "source_rows": len(reqs), "landed_rows": n_new, "duplicate_rows": len(reqs) - n_new, "rejected_rows": 0,
          "corrections": 0, "status": "LOADED" if n_new else "ALL_DUPLICATE"}
    _write_watermarks(lake, [st])
    return st

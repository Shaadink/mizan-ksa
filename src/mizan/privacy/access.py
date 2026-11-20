"""PDPL right of access and portability: tell a person what is held about them, and hand it over.

Erasure was implemented first because it is the harder right and the one that conflicts with tax law.
Access is its sibling and was listed as "not implemented" in the DPIA, so this closes that -- for the
right of access and the right to portability, which are the two that can be satisfied by reading.

**Access is as dangerous as erasure, in the opposite direction.** Erasure destroys a key and the risk is
doing it wrongly. Access *creates a new cleartext copy of someone's personal data* in a file, outside
every control that protects it at rest, and the risk is doing it at all. So:

  - the report is built in memory and returned; writing it to disk is the caller's deliberate act,
  - `docs/RUNBOOKS.md` says to destroy the file once it has been delivered,
  - decryption is per subject, with that subject's own key, and fails if the key has been shredded,
  - an erased subject returns `ERASED` with the tombstone, never a partial record assembled from the
    rows that survived erasure. Reconstructing a shredded person from leftovers would undo the erasure
    in the name of a different right.

**What is disclosed and what is withheld** is itself part of the answer. A subject is entitled to know
that signed tax invoices are retained under a legal obligation even though their personal data has been
shredded, so the report says so rather than silently omitting them.
"""

from __future__ import annotations

import json
from typing import Any

from pyspark.sql import functions as F

from mizan.privacy import crypto
from mizan.privacy.pdpl import resolve_subject
from mizan.spark.lake import Lake
from mizan.spark.mdm_land import now_ksa

# Which tables hold something about a person, and how they are reached. The encrypted column lists are
# taken from the Bronze contracts rather than retyped, because a contract that gains a PII column must not
# leave this file disclosing it as ciphertext -- that was the first bug here: payment_events_raw was listed
# as holding a subject token and does not. Payments reach a person only through their orders.
_BY_TOKEN = "subject_token_id"   # noqa: S105 - a column name, not a credential


def _sources() -> dict[str, dict[str, Any]]:
    """Where a person's data lives, read from the Bronze contracts rather than retyped.

    `encrypted` maps the column as **stored** to (the name it was bound to, the column naming the token
    it was encrypted under). Two details here are easy to get wrong and both fail loudly rather than
    quietly, which is the right way round:

      - Bronze writes PII to `<column>_enc` but binds the ciphertext to the *plain* name, so decrypting
        `full_name_ar_enc` means passing `full_name_ar` as the associated data.
      - The golden record encrypts each name under the token of the **source record it chose that name
        from**, which is not one token per row: `name_ar_enc` and `name_en_enc` can belong to different
        members of the same golden profile. Decrypting both with one token authenticates for neither.
    """
    from mizan.spark import contracts as C
    crm_pii = sorted({*C.CRM_POS.pii, *C.CRM_ECOM.pii})
    return {
        f"brz.{C.CRM_POS.table}": {"via": _BY_TOKEN, "label": "customer record as received",
                                   "encrypted": {f"{c}_enc": (c, _BY_TOKEN) for c in crm_pii}},
        f"brz.{C.SPL.table}": {"via": _BY_TOKEN, "label": "address observations",
                               "encrypted": {f"{c}_enc": (c, _BY_TOKEN) for c in C.SPL.pii}},
        f"brz.{C.COMMERCE.table}": {"via": _BY_TOKEN, "label": "orders and returns",
                                    "encrypted": {f"{c}_enc": (c, _BY_TOKEN) for c in C.COMMERCE.pii}},
        f"brz.{C.PAYMENTS.table}": {"via": "order_id", "label": "payments against those orders",
                                    "encrypted": {}},
        # The golden record stores the chosen name under its own column names, bound to the source
        # column it came from. tests/test_pdpl_ndmo.py decrypts it the same way.
        "slv.golden_party_scd2": {"via": "member_tokens", "label": "resolved identity (master data)",
                                  "encrypted": {"name_ar_enc": ("full_name_ar", "name_ar_source_token"),
                                                "name_en_enc": ("full_name_en", "name_en_source_token")}},
    }


SOURCES = _sources()

# Held, disclosed as held, and not handed over as personal data: the signed tax chain. The subject's
# identity link is gone after erasure, and the documents themselves are statutory evidence.
WITHHELD = {
    "audit.zatca_chain_journal": "Signed tax invoices are retained under a statutory obligation (ZATCA "
                                 "e-invoicing and tax record-keeping). They are disclosed as held; their "
                                 "contents are not provided as personal data, and after an erasure request "
                                 "the link between these documents and your identity has been removed.",
}


def _decrypt_row(keys: crypto.Keys, row: dict, encrypted: dict[str, tuple[str, str]],
                 vault: dict[str, dict]) -> tuple[dict, list[str]]:
    """Decrypt a row, resolving the key **per column** because one row can hold two subjects' ciphertext.

    Returns (row, unreadable columns). A column whose key has been shredded is dropped and named rather
    than guessed at: handing back ciphertext labelled as a person's name would be worse than omitting it.
    The output uses the plain column name -- a subject should read `full_name_ar`, not
    `full_name_ar_enc`, and certainly not both.
    """
    out, unreadable = {}, []
    for column, value in row.items():
        if column.startswith("_"):
            continue
        if column not in encrypted:
            out[column] = value
            continue
        plain, token_column = encrypted[column]
        token = row.get(token_column)
        wrapped = (vault.get(token) or {}).get("wrapped_dek") if token else None
        if not token or wrapped is None:
            unreadable.append(plain)
            continue
        dek = crypto.unwrap_dek(keys, token, bytes(wrapped))
        out[plain] = crypto.decrypt_field(dek, token, plain, value)
    return out, unreadable


def _vault(lake: Lake, tokens: set[str]) -> dict[str, dict]:
    if not lake.exists("security", "pii_vault_metadata"):
        return {}
    rows = (lake.read("security", "pii_vault_metadata")
            .filter(F.col("subject_token_id").isin(*tokens)).collect())
    return {r["subject_token_id"]: r.asDict() for r in rows}


def _tombstones(lake: Lake, tokens: set[str]) -> dict[str, dict]:
    if not lake.exists("ctl", "deletion_tombstones"):
        return {}
    rows = (lake.read("ctl", "deletion_tombstones")
            .filter(F.col("subject_token_id").isin(*tokens)).collect())
    return {r["subject_token_id"]: r.asDict() for r in rows}


def subject_access(lake: Lake, keys: crypto.Keys | None = None, *, source_ref: str | None = None,
                   national_id: str | None = None, requested_by: str = "dpo@najd.example") -> dict:
    """Everything held about one person, decrypted with their own key, or the reason it cannot be.

    Returns a report rather than writing one. See the module docstring for why that distinction matters.
    """
    keys = keys or crypto.Keys.from_env()
    tokens, goldens = resolve_subject(lake, keys, source_ref=source_ref, national_id=national_id)
    if not tokens:
        # Not an error worth a traceback: "we hold nothing about you" is a valid, complete answer, and
        # one a controller must be able to give without it looking like a failure.
        return {"status": "NOT_FOUND", "requested_by": requested_by, "generated_at": now_ksa(),
                "subject_tokens": [], "records": {}, "withheld": {}, "notes":
                ["No record was found for the identifier provided."]}

    tombstones = _tombstones(lake, tokens)
    if tombstones:
        # Fail closed. Rebuilding a shredded person from the rows erasure left behind would defeat it.
        return {"status": "ERASED", "requested_by": requested_by, "generated_at": now_ksa(),
                "subject_tokens": sorted(tokens), "records": {}, "withheld": dict(WITHHELD),
                "erasure": sorted(({"subject_token_id": t, "dsr_id": v.get("dsr_id"),
                                    "legal_hold_class": v.get("legal_hold_class"),
                                    "tombstoned_at": str(v.get("tombstoned_at"))}
                                   for t, v in tombstones.items()), key=lambda d: d["subject_token_id"]),
                "notes": ["This subject has been erased. The encryption key for their personal data was "
                          "destroyed, so no personal data can be produced, by anyone, including us.",
                          "Signed tax invoices are retained under a statutory obligation and are no longer "
                          "linked to this identity."]}

    vault = _vault(lake, tokens)
    records: dict[str, list[dict]] = {}
    notes: list[str] = []
    orders: set[str] = set()

    for name, spec in SOURCES.items():
        schema, table = name.split(".", 1)
        if not lake.exists(schema, table):
            continue
        frame = lake.read(schema, table)
        via = spec["via"]

        if via == "member_tokens":
            # Golden records hold their members as a JSON list, so this one cannot be a column filter.
            rows = [r.asDict() for r in frame.collect() if set(json.loads(r["member_tokens"])) & tokens]
        elif via == "order_id":
            # Payments carry no customer reference at all: they reach a person only through an order.
            # If no order was found, nothing here belongs to this subject -- do not fall back to a
            # broader filter, which would disclose somebody else's payments.
            if not orders:
                continue
            rows = [r.asDict() for r in frame.filter(F.col("order_id").isin(*orders)).collect()]
        else:
            if via not in frame.columns:
                # A schema that no longer matches this map is a disclosure bug, not something to skip
                # quietly: under-disclosing is the failure mode an access request cannot tolerate.
                raise RuntimeError(f"{name} has no {via} column; the access source map is out of date")
            rows = [r.asDict() for r in frame.filter(F.col(via).isin(*tokens)).collect()]

        if not rows:
            continue
        if table == "commerce_events_raw":
            orders |= {r["order_id"] for r in rows if r.get("order_id")}

        encrypted = {col: how for col, how in spec["encrypted"].items() if col in rows[0]}
        out, unreadable = [], set()
        for row in rows:
            decrypted, missing = _decrypt_row(keys, row, encrypted, vault)
            unreadable |= set(missing)
            out.append(decrypted)
        if unreadable:
            notes.append(f"{name}: {', '.join(sorted(unreadable))} could not be read; the encryption key "
                         "for those values no longer exists.")
        records[name] = out

    return {"status": "DISCLOSED", "requested_by": requested_by, "generated_at": now_ksa(),
            "subject_tokens": sorted(tokens), "golden_ids": sorted(goldens),
            "record_counts": {k: len(v) for k, v in records.items()},
            "records": records, "withheld": dict(WITHHELD), "notes": notes or
            ["All records held about this subject are included, decrypted with this subject's own key."]}


def portability_payload(report: dict) -> dict:
    """The portability subset: the subject's own data, in a structured, machine-readable form.

    Portability is narrower than access -- it covers data the subject provided, not every derived record,
    and never another person's data. Match decisions and golden membership are excluded for exactly that
    reason: they describe how we linked records, which is our processing and not their data.
    """
    if report["status"] != "DISCLOSED":
        return {"status": report["status"], "data": {}}
    provided = {name: rows for name, rows in report["records"].items()
                if not name.startswith("slv.golden_party")}
    return {"status": "DISCLOSED", "format": "application/json", "generated_at": report["generated_at"],
            "data": provided, "excluded": ["slv.golden_party_scd2 (our record-linkage decisions, not your "
                                           "data)", *sorted(WITHHELD)]}

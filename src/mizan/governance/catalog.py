"""Module 6: NDMO governance-as-code.

* 4-tier column classification (TOP_SECRET > SECRET > CONFIDENTIAL > PUBLIC) by ordered, versioned rules.
* A table inherits the HIGHEST tier of its columns (NDMO rule); columns below that tier are over-classified.
  The over-classification share is what a security split recovers for analytics.
* Every table declares a subject_key and a legal_hold_class (TAX / SAMA / CONSENT). An unknown table, or an unknown
  class, FAILS CLOSED: the catalog refuses to build rather than guess.
* Residency gate (I-14): a column may land in a zone only if its tier <= the zone's ceiling, and SECRET+ data only
  in an approved region.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

CATALOG_VERSION = "NDMO_RULES_V1"
TIERS = ("PUBLIC", "CONFIDENTIAL", "SECRET", "TOP_SECRET")
RANK = {t: i for i, t in enumerate(TIERS)}
HOLD_CLASSES = ("TAX", "SAMA", "CONSENT")

# (schema.table glob, column regex, tier, rule id, personal data?) - first match wins
COLUMN_RULES: tuple[tuple[str, str, str, str, bool], ...] = (
    ("security.pii_vault_metadata", r"wrapped_dek", "TOP_SECRET", "R01_KEY_MATERIAL", False),
    ("audit.zatca_chain_journal", r"signed_xml", "TOP_SECRET", "R02_SIGNED_TAX_EVIDENCE_WITH_BUYER_PII", True),
    ("security.subject_token_map", r"source_ref_enc", "TOP_SECRET", "R03_TOKEN_TO_IDENTITY_LINK", True),
    ("*", r".*_enc", "SECRET", "R04_ENCRYPTED_PERSONAL_DATA", True),
    ("quarantine.schema_rejections", r"payload_json", "SECRET", "R05_REJECTED_ROW_PAYLOAD", True),
    ("*", r"payload_json", "CONFIDENTIAL", "R06_UNSIGNED_REQUEST_PAYLOAD", False),
    ("*", r"(.*_hmac|subject_token_id|.*_token|member_tokens|_event_key|_payload_hash|event_key|payload_hash)",
     "CONFIDENTIAL", "R07_PSEUDONYMOUS_KEY", True),
    ("*", r"(.*_sar|amount.*|.*_amount|net_.*|gross_.*|fee.*|vat_.*|wrbtr|hsl)", "CONFIDENTIAL",
     "R08_FINANCIAL_AMOUNT", False),
    ("*", r"(invoice_hash|pih|qr_tlv_b64|last_invoice_hash|history_json|evidence|detail|candidate_golden_ids)",
     "CONFIDENTIAL", "R09_CONTROL_EVIDENCE", False),
    ("*", r".*", "PUBLIC", "R99_OPERATIONAL_ATTRIBUTE", False),
)

# legal_hold_class per table (fail closed: a table not listed here stops the catalog build)
TABLE_HOLD: tuple[tuple[str, str], ...] = (
    ("brz.zatca_invoices_raw", "TAX"), ("ctl.egs_chain_state", "TAX"), ("ctl.invoice_outbox", "TAX"),
    ("audit.zatca_chain_journal", "TAX"), ("slv.zatca_invoice_documents", "TAX"),
    ("quarantine.zatca_chain_violations", "TAX"), ("brz.erp_gl_raw", "TAX"), ("slv.erp_gl_journal_lines", "TAX"),
    ("brz.payment_events_raw", "SAMA"), ("brz.settlement_batches_raw", "SAMA"), ("slv.payment_lifecycle", "SAMA"),
    ("slv.settlement_lines", "SAMA"), ("quarantine.settlement_breaks", "SAMA"), ("brz.commerce_events_raw", "SAMA"),
    ("brz.crm_party_raw", "CONSENT"), ("brz.spl_address_raw", "CONSENT"), ("slv.golden_party_scd2", "CONSENT"),
    ("slv.identifier_registry", "CONSENT"), ("slv.entity_merge_ledger", "CONSENT"),
    ("slv.address_observations", "CONSENT"), ("quarantine.mdm_match_conflicts", "CONSENT"),
    ("quarantine.schema_rejections", "CONSENT"), ("security.*", "CONSENT"), ("ctl.deletion_tombstones", "CONSENT"),
    ("ctl.applied_event_ledger", "SAMA"), ("ctl.ingestion_watermarks", "SAMA"), ("audit.pdpl_dsr_evidence", "CONSENT"),
    ("audit.run_manifests", "SAMA"), ("audit.benchmarks", "SAMA"), ("meta.*", "SAMA"), ("ai.*", "CONSENT"),
    ("gld.*", "SAMA"),
)


@dataclass(frozen=True)
class ColumnClass:
    tier: str
    rule: str
    is_personal_data: bool


def classify_column(schema: str, table: str, column: str) -> ColumnClass:
    st = f"{schema}.{table}"
    for pattern, rx, tier, rule, personal in COLUMN_RULES:
        if fnmatch.fnmatch(st, pattern) and re.fullmatch(rx, column.lower()):
            return ColumnClass(tier, rule, personal)
    raise LookupError(f"no rule classifies {st}.{column}")       # unreachable: R99 matches everything


def legal_hold_class(schema: str, table: str) -> str:
    st = f"{schema}.{table}"
    for pattern, cls in TABLE_HOLD:
        if fnmatch.fnmatch(st, pattern):
            if cls not in HOLD_CLASSES:
                raise ValueError(f"unknown legal_hold_class {cls!r} for {st}")
            return cls
    raise LookupError(f"{st} has no legal_hold_class: refusing to catalog an unclassified table (fail closed)")


def build_catalog(tables: dict[str, list[tuple[str, str]]]) -> list[dict]:
    """tables: {'schema.table': [(column, data_type), ...]} -> meta.column_classification rows."""
    rows: list[dict] = []
    for st in sorted(tables):
        schema, table = st.split(".", 1)
        cols = tables[st]
        hold = legal_hold_class(schema, table)
        classes = [(c, t, classify_column(schema, table, c)) for c, t in cols]
        table_tier = max((k.tier for _, _, k in classes), key=RANK.__getitem__, default="PUBLIC")
        subject_key = "subject_token_id" if any(c == "subject_token_id" for c, _ in cols) else None
        for c, t, k in classes:
            rows.append({"schema_name": schema, "table_name": table, "column_name": c, "data_type": t,
                         "classification": k.tier, "rule_id": k.rule, "is_personal_data": k.is_personal_data,
                         "table_classification": table_tier,
                         "is_over_classified": RANK[k.tier] < RANK[table_tier],
                         "subject_key": subject_key, "legal_hold_class": hold, "catalog_version": CATALOG_VERSION})
    return rows


def over_classification(rows: list[dict]) -> list[dict]:
    """Per table: how many columns sit above their own tier only because they share a table with SECRET data."""
    by: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by.setdefault((r["schema_name"], r["table_name"]), []).append(r)
    out = []
    for (s, t), rs in sorted(by.items()):
        over = sum(1 for r in rs if r["is_over_classified"])
        out.append({"schema_name": s, "table_name": t, "table_classification": rs[0]["table_classification"],
                    "columns": len(rs), "over_classified_columns": over,
                    "over_classified_pct": round(100.0 * over / len(rs), 1),
                    "recommendation": "SPLIT_SECRET_COLUMNS" if over and RANK[rs[0]["table_classification"]]
                    >= RANK["SECRET"] else "NONE"})
    return out


# ----------------------------------------------------------------------------- residency gate (I-14)

@dataclass(frozen=True)
class Zone:
    name: str
    max_classification: str
    region: str


def load_policy(path: Path) -> tuple[dict[str, Zone], set[str]]:
    """Tiny YAML subset reader (no extra dependency): see config/residency_policy.yml."""
    zones: dict[str, Zone] = {}
    approved: set[str] = set()
    cur: dict[str, str] = {}
    section = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):
            section = line.rstrip(":").strip()
            continue
        item = line.strip()
        if section == "approved_secret_regions" and item.startswith("- "):
            approved.add(item[2:].strip())
        elif section == "zones":
            if item.startswith("- "):
                if cur:
                    zones[cur["zone"]] = Zone(cur["zone"], cur["max_classification"], cur["region"])
                cur = {}
                item = item[2:]
            k, v = (x.strip() for x in item.split(":", 1))
            cur[k] = v
    if cur:
        zones[cur["zone"]] = Zone(cur["zone"], cur["max_classification"], cur["region"])
    for z in zones.values():
        if z.max_classification not in TIERS:
            raise ValueError(f"zone {z.name}: unknown tier {z.max_classification!r}")
    return zones, approved


def residency_violations(columns: list[dict], zones: dict[str, Zone], approved_regions: set[str]) -> list[str]:
    """columns: [{'zone', 'schema_name', 'table_name', 'column_name', 'classification'}]. Unknown zone -> violation."""
    out = []
    for c in columns:
        where = f"{c['zone']}:{c['schema_name']}.{c['table_name']}.{c['column_name']}"
        z = zones.get(c["zone"])
        if z is None:
            out.append(f"{where} targets an undeclared zone")
            continue
        if RANK[c["classification"]] > RANK[z.max_classification]:
            out.append(f"{where} is {c['classification']} but zone ceiling is {z.max_classification}")
        if RANK[c["classification"]] >= RANK["SECRET"] and z.region not in approved_regions:
            out.append(f"{where} is {c['classification']} in region {z.region} (not approved for SECRET data)")
    return out

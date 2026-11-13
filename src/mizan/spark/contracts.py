"""Bronze schema contracts: one per source feed. A row that breaks its contract goes to
quarantine.schema_rejections with a reason; a file whose header drifts is rejected whole (SCHEMA_DRIFT).

Business keys feed ctl.applied_event_ledger: an identical (key, payload hash) is a duplicate and is skipped;
the same key with a different payload lands as a new version (a correction re-send).
"""

from __future__ import annotations

from dataclasses import dataclass, field

AMOUNT_RE = r"^[0-9]{1,16}\.[0-9]{2}$"
UTC_TS_RE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
DATE_RE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
SAP_DATE_RE = r"^[0-9]{8}$"
SCHEMES = ("MADA", "VISA", "MASTERCARD", "BNPL", "SADAD")


@dataclass(frozen=True)
class Contract:
    source: str
    table: str                      # brz.<table>
    columns: tuple[str, ...]
    key: tuple[str, ...]
    required: tuple[str, ...]
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    patterns: dict[str, str] = field(default_factory=dict)
    pii: tuple[str, ...] = ()       # encrypted at the Bronze write (ADR-003)
    subject_col: str | None = None  # source customer ref -> subject_token_id (then dropped)
    encoding: str = "utf-8"
    nullable_enums: tuple[str, ...] = ()


COMMERCE = Contract(
    source="commerce_events", table="commerce_events_raw",
    columns=("event_id", "event_type", "order_id", "return_id", "channel", "store_id", "register_id", "merchant_id",
             "customer_ref", "buyer_name", "buyer_mobile", "delivery_short_address", "payment_means", "amount_sar",
             "event_ts_utc"),
    key=("event_id",),
    required=("event_id", "event_type", "order_id", "channel", "store_id", "merchant_id", "payment_means",
              "amount_sar", "event_ts_utc"),
    enums={"event_type": ("ORDER_PLACED", "RETURN_REQUESTED"), "channel": ("POS", "ECOM"),
           "payment_means": ("CASH", *SCHEMES)},
    patterns={"amount_sar": AMOUNT_RE, "event_ts_utc": UTC_TS_RE},
    pii=("buyer_name", "buyer_mobile", "delivery_short_address"), subject_col="customer_ref")

PAYMENTS = Contract(
    source="payment_events", table="payment_events_raw",
    columns=("payment_event_id", "event_type", "order_id", "invoice_uuid", "credit_note_uuid", "merchant_id",
             "store_id", "register_id", "payment_scheme", "amount_sar", "currency", "event_ts_utc"),
    key=("payment_event_id",),
    required=("payment_event_id", "event_type", "order_id", "invoice_uuid", "merchant_id", "payment_scheme",
              "amount_sar", "currency", "event_ts_utc"),
    enums={"event_type": ("CAPTURE", "REFUND", "CHARGEBACK"), "payment_scheme": SCHEMES, "currency": ("SAR",)},
    patterns={"amount_sar": AMOUNT_RE, "event_ts_utc": UTC_TS_RE})

SETTLEMENT = Contract(
    source="settlement", table="settlement_batches_raw",
    columns=("settlement_batch_id", "payout_date", "merchant_id", "payment_event_id", "txn_type", "card_scheme",
             "txn_ts_ksa", "settlement_for_date", "gross_amount", "mdr_fee", "vat_on_fee", "net_amount", "dr_cr"),
    key=("settlement_batch_id", "payment_event_id"),
    required=("settlement_batch_id", "payout_date", "merchant_id", "payment_event_id", "txn_type",
              "settlement_for_date", "gross_amount", "mdr_fee", "vat_on_fee", "net_amount", "dr_cr"),
    enums={"txn_type": ("PURCHASE", "REFUND", "CHARGEBACK"), "dr_cr": ("CR", "DR"), "card_scheme": SCHEMES},
    patterns={"gross_amount": AMOUNT_RE, "mdr_fee": AMOUNT_RE, "vat_on_fee": AMOUNT_RE, "net_amount": AMOUNT_RE,
              "settlement_for_date": DATE_RE, "payout_date": DATE_RE})

ERP_GL = Contract(
    source="erp_gl", table="erp_gl_raw",
    columns=("RLDNR", "RBUKRS", "GJAHR", "BELNR", "DOCLN", "BUDAT", "BLDAT", "RACCT", "DRCRK", "HSL", "RHCUR",
             "PRCTR", "ZZ_STORE_ID", "ZZ_MERCHANT_ID", "SGTXT"),
    key=("RBUKRS", "GJAHR", "BELNR", "DOCLN"),
    required=("RLDNR", "RBUKRS", "GJAHR", "BELNR", "DOCLN", "BUDAT", "RACCT", "DRCRK", "HSL", "RHCUR",
              "ZZ_MERCHANT_ID"),
    enums={"DRCRK": ("S", "H"), "RHCUR": ("SAR",)},
    patterns={"HSL": AMOUNT_RE, "BUDAT": SAP_DATE_RE})

_CRM_COMMON = ("source_customer_id", "party_type", "full_name_ar", "full_name_en", "national_id", "mobile",
               "landline")
CRM_POS = Contract(
    source="crm_pos", table="crm_party_raw",
    columns=(*_CRM_COMMON, "vat_number", "unified_700", "spl_short_address", "city", "created_date"),
    key=("source_customer_id",), required=("source_customer_id", "party_type", "created_date"),
    enums={"party_type": ("PERSON", "ORGANIZATION")}, patterns={"created_date": DATE_RE},
    pii=("full_name_ar", "full_name_en", "national_id", "mobile", "landline", "spl_short_address"),
    subject_col="source_customer_id", encoding="cp1256")
CRM_ECOM = Contract(
    source="crm_ecom", table="crm_party_raw",
    columns=(*_CRM_COMMON, "email", "spl_short_address", "city", "created_date"),
    key=("source_customer_id",), required=("source_customer_id", "party_type", "created_date"),
    enums={"party_type": ("PERSON", "ORGANIZATION")}, patterns={"created_date": DATE_RE},
    pii=("full_name_ar", "full_name_en", "national_id", "mobile", "landline", "email", "spl_short_address"),
    subject_col="source_customer_id")
SPL = Contract(
    source="spl_address", table="spl_address_raw",
    columns=("observation_id", "source_system", "source_customer_id", "short_address", "building_number",
             "secondary_number", "district", "city", "postal_code", "observed_date"),
    key=("observation_id",), required=("observation_id", "source_customer_id", "short_address", "observed_date"),
    enums={"source_system": ("DELIVERY", "POS", "ECOM")}, patterns={"observed_date": DATE_RE},
    pii=("short_address", "building_number", "secondary_number"), subject_col="source_customer_id")

ALL = (COMMERCE, PAYMENTS, SETTLEMENT, ERP_GL, CRM_POS, CRM_ECOM, SPL)

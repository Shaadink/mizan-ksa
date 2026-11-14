"""Silver conformed tables (LH_MIZAN.slv) built from Bronze. Each build is a full, idempotent recompute.

Money rule (CLAUDE.md, ADR-007): event amounts stay POSITIVE with event_type / debit_credit carrying direction.
The one derived measure, settlement_lines.net_settled_sar, is the bank's signed net position (CR +, DR -),
which is what the Gold circuit breaker sums.
"""

from __future__ import annotations

from pathlib import Path

from pyspark.sql import Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from mizan.spark.lake import Lake
from mizan.spark.session import spark_file_uri

MONEY = T.DecimalType(18, 2)
SETTLEMENT_STATUSES = ("PAID_BANK", "IN_TRANSIT", "QUARANTINED")
GL_ROLES = ("CASH_ON_HAND", "CARD_CLEARING", "REVENUE", "VAT_OUTPUT", "CHARGEBACK_LOSS")
EVENT_TYPES = ("CAPTURE", "REFUND", "CHARGEBACK")
_BANK_TO_EVENT = {"PURCHASE": "CAPTURE", "REFUND": "REFUND", "CHARGEBACK": "CHARGEBACK"}


def _latest(df, keys: list[str]):
    """Latest landed version per business key (a correction re-send supersedes the original)."""
    w = Window.partitionBy(*keys).orderBy(F.col("_ingested_at").desc(), F.col("_source_file").desc(),
                                          F.col("_batch_id").desc())
    return df.withColumn("_v", F.row_number().over(w)).filter("_v = 1").drop("_v")


def _ref_csv(spark, path: Path, schema: T.StructType):
    return (spark.read.option("header", "true").schema(
        T.StructType([T.StructField(c.name, T.StringType()) for c in schema.fields])).csv(spark_file_uri(path)))


# ----------------------------------------------------------------------------- payment lifecycle

def build_payment_lifecycle(lake: Lake):
    raw = _latest(lake.read("brz", "payment_events_raw"), ["payment_event_id"])
    ts = F.to_timestamp("event_ts_utc", "yyyy-MM-dd'T'HH:mm:ssX")
    out = raw.select(
        "payment_event_id", "order_id", "invoice_uuid", "credit_note_uuid", "merchant_id", "store_id",
        "register_id", "event_type", "payment_scheme",
        F.col("amount_sar").cast(MONEY).alias("amount_sar"),
        ts.alias("event_ts"),
        F.to_date(ts).alias("business_date_ksa"),          # session TZ = Asia/Riyadh
        F.col("_batch_id").alias("source_batch_id"))
    lake.write(out, "slv", "payment_lifecycle", "overwrite", overwrite_schema=True, constraints={
        "amount_positive": "amount_sar > 0",
        "event_type_enum": "event_type IN ('CAPTURE', 'REFUND', 'CHARGEBACK')"})
    return lake.read("slv", "payment_lifecycle")


# ----------------------------------------------------------------------------- settlement lines

def build_settlement_lines(lake: Lake, data_dir: Path):
    spark = lake.spark
    pay = lake.read("slv", "payment_lifecycle")
    bank = _latest(lake.read("brz", "settlement_batches_raw"), ["payment_event_id"])
    fees = _ref_csv(spark, data_dir / "reference/acquirer_fee_schedule.csv", T.StructType([
        T.StructField(n, T.StringType()) for n in
        ("card_scheme", "mdr_rate", "fee_cap_sar", "chargeback_fee_sar", "vat_on_fee_rate")]))
    fees = fees.select(F.col("card_scheme").alias("payment_scheme"),
                       F.col("mdr_rate").cast(T.DecimalType(9, 4)).alias("mdr_rate"),
                       F.col("fee_cap_sar").cast(MONEY).alias("fee_cap_sar"),
                       F.col("chargeback_fee_sar").cast(MONEY).alias("chargeback_fee_sar"),
                       F.col("vat_on_fee_rate").cast(T.DecimalType(9, 4)).alias("vat_on_fee_rate"))

    mapping = F.create_map(*[x for k, v in _BANK_TO_EVENT.items() for x in (F.lit(k), F.lit(v))])
    net = F.col("net_amount").cast(MONEY)
    b = bank.select(
        "payment_event_id", F.col("merchant_id").alias("bank_merchant_id"), "settlement_batch_id",
        F.to_date("settlement_for_date").alias("settlement_for_date_ksa"),
        F.col("gross_amount").cast(MONEY).alias("gross_amount_sar"),
        F.col("mdr_fee").cast(MONEY).alias("acquirer_mdr_fee_sar"),
        F.col("vat_on_fee").cast(MONEY).alias("acquirer_vat_sar"),
        F.when(F.col("dr_cr") == "CR", net).otherwise(-net).cast(MONEY).alias("net_settled_sar"),
        mapping[F.col("txn_type")].alias("bank_event_type"), "_source_file")
    j = b.join(pay.select("payment_event_id", "merchant_id", "event_type", "amount_sar"), "payment_event_id", "left")
    break_type = (F.when(F.col("event_type").isNull(), "ORPHAN_BANK_LINE")
                  .when(F.col("merchant_id") != F.col("bank_merchant_id"), "MERCHANT_MISMATCH")
                  .when(F.col("event_type") != F.col("bank_event_type"), "EVENT_TYPE_MISMATCH")
                  .when(F.col("amount_sar") != F.col("gross_amount_sar"), "AMOUNT_MISMATCH"))
    j = j.withColumn("break_type", break_type)
    bank_lines = j.select(
        "payment_event_id", F.col("bank_merchant_id").alias("merchant_id"), "settlement_batch_id",
        "settlement_for_date_ksa", F.coalesce("event_type", "bank_event_type").alias("event_type"),
        "gross_amount_sar", "acquirer_mdr_fee_sar", "acquirer_vat_sar", "net_settled_sar",
        F.when(F.col("break_type").isNull(), "PAID_BANK").otherwise("QUARANTINED").alias("settlement_status"),
        F.lit(False).alias("is_estimate"), "break_type")

    # IN_TRANSIT expectation rows: payment events whose bank file has not arrived (estimated fee)
    pending = pay.join(bank.select("payment_event_id"), "payment_event_id", "left_anti") \
                 .join(fees, "payment_scheme", "left")
    rate_fee = F.round(F.col("amount_sar") * F.col("mdr_rate"), 2).cast(MONEY)
    fee = (F.when(F.col("event_type") == "REFUND", F.lit(0).cast(MONEY))
           .when(F.col("event_type") == "CHARGEBACK", F.col("chargeback_fee_sar"))
           .otherwise(F.when(F.col("fee_cap_sar").isNotNull() & (rate_fee > F.col("fee_cap_sar")),
                             F.col("fee_cap_sar")).otherwise(rate_fee))).cast(MONEY)
    pending = pending.withColumn("fee", fee) \
                     .withColumn("vat", F.round(F.col("fee") * F.col("vat_on_fee_rate"), 2).cast(MONEY))
    est_net = F.when(F.col("event_type") == "CAPTURE", F.col("amount_sar") - F.col("fee") - F.col("vat")) \
               .otherwise(-(F.col("amount_sar") + F.col("fee") + F.col("vat")))
    transit = pending.select(
        "payment_event_id", "merchant_id", F.lit(None).cast("string").alias("settlement_batch_id"),
        F.col("business_date_ksa").alias("settlement_for_date_ksa"), "event_type",
        F.col("amount_sar").alias("gross_amount_sar"), F.col("fee").alias("acquirer_mdr_fee_sar"),
        F.col("vat").alias("acquirer_vat_sar"), est_net.cast(MONEY).alias("net_settled_sar"),
        F.lit("IN_TRANSIT").alias("settlement_status"), F.lit(True).alias("is_estimate"),
        F.when(F.col("mdr_rate").isNull(), "NO_FEE_SCHEDULE").alias("break_type"))

    lines = bank_lines.unionByName(transit).cache()
    lake.write(lines.drop("break_type"), "slv", "settlement_lines", "overwrite", overwrite_schema=True,
               constraints={"status_enum": "settlement_status IN ('PAID_BANK', 'IN_TRANSIT', 'QUARANTINED')",
                            "fees_non_negative": "acquirer_mdr_fee_sar >= 0 AND acquirer_vat_sar >= 0",
                            "gross_positive": "gross_amount_sar > 0"})
    breaks = lines.filter(F.col("break_type").isNotNull()).select(
        "payment_event_id", "merchant_id", "settlement_batch_id", "settlement_for_date_ksa", "break_type",
        "net_settled_sar", F.current_timestamp().alias("detected_at"))
    lake.write(breaks, "quarantine", "settlement_breaks", "overwrite", overwrite_schema=True)
    lines.unpersist()
    return lake.read("slv", "settlement_lines")


# ----------------------------------------------------------------------------- GL journal lines

def build_erp_gl_journal_lines(lake: Lake, data_dir: Path):
    spark = lake.spark
    gl = _latest(lake.read("brz", "erp_gl_raw"), ["RBUKRS", "GJAHR", "BELNR", "DOCLN"])
    roles = _ref_csv(spark, data_dir / "reference/gl_account_roles.csv", T.StructType([
        T.StructField(n, T.StringType()) for n in ("RACCT", "gl_account_role", "normal_side")]))
    j = gl.join(roles.select("RACCT", "gl_account_role"), "RACCT", "left").cache()
    unknown = j.filter(F.col("gl_account_role").isNull())
    if unknown.limit(1).count():
        rej = unknown.select(F.col("_source").alias("source"), F.col("_batch_id").alias("batch_id"),
                             F.col("_source_file").alias("source_file"), F.lit(None).cast("long").alias("row_num"),
                             F.col("_event_key").alias("event_key"), F.col("_payload_hash").alias("payload_hash"),
                             F.concat(F.lit("UNKNOWN_GL_ACCOUNT:"), F.col("RACCT")).alias("reject_reason"),
                             F.to_json(F.struct("RACCT", "BELNR", "DOCLN", "HSL")).alias("payload_json"),
                             F.current_timestamp().alias("rejected_at"))
        lake.write(rej, "quarantine", "schema_rejections", "append", merge_schema=True)
    out = j.filter(F.col("gl_account_role").isNotNull()).select(
        F.col("ZZ_MERCHANT_ID").alias("merchant_id"), F.col("ZZ_STORE_ID").alias("store_id"),
        F.to_date("BUDAT", "yyyyMMdd").alias("posting_date_ksa"), F.col("RACCT").alias("gl_account"),
        "gl_account_role", F.col("DRCRK").alias("debit_credit"), F.col("HSL").cast(MONEY).alias("amount_sar"),
        F.col("RBUKRS").alias("company_code"), F.col("RLDNR").alias("ledger"), F.col("GJAHR").alias("fiscal_year"),
        F.col("BELNR").alias("document_number"), F.col("DOCLN").alias("line_item"),
        F.col("PRCTR").alias("profit_center"), F.col("_is_correction").alias("is_correction"),
        F.col("_batch_id").alias("source_batch_id"))
    lake.write(out, "slv", "erp_gl_journal_lines", "overwrite", overwrite_schema=True, constraints={
        "amount_positive": "amount_sar > 0", "drcr_enum": "debit_credit IN ('S', 'H')",
        "role_enum": "gl_account_role IN (" + ", ".join(f"'{r}'" for r in GL_ROLES) + ")"})
    j.unpersist()
    return lake.read("slv", "erp_gl_journal_lines")

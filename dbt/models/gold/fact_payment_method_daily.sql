-- ==============================================================================
-- FILE: dbt/models/gold/fact_payment_method_daily.sql     (owner-approved addition, 2026-11-15)
-- Grain: merchant_id x business_date_ksa x payment_scheme. materialized = 'incremental' (ADR-015)
-- Splits the reconciliation's captures, the BANK's own fees and the bank's settlement status (paid / in transit /
-- quarantined) (MDR + VAT from the settlement file, at the bank's
-- line grain; never recomputed) by payment scheme. A key spine over captures and settlement lines keeps every row;
-- a bank line without a payment event would appear as UNMATCHED_BANK_LINE, never be dropped.
-- Reconciles exactly to gld.fact_merchant_settlement_recon (tests/assert_payment_methods_reconcile_to_recon.sql).
--
-- THE UNIQUE KEY IS DELIBERATELY COARSER THAN THE GRAIN, and this is the subtlest thing in the model.
-- The grain is (merchant, day, scheme) but the incremental key is only (merchant, day). The reason is that
-- a scheme row can VANISH. A bank line whose payment event has not arrived is reported under the synthetic
-- scheme UNMATCHED_BANK_LINE; when the payment lands, that row is replaced by a real MADA or VISA row and
-- the UNMATCHED_BANK_LINE row for that day should no longer exist. Keyed at the grain, the rebuild would
-- have no row to overwrite it with and the stale UNMATCHED_BANK_LINE row would survive forever -- the
-- reconciliation test against fact_merchant_settlement_recon would then fail, because the day's fees would
-- be counted twice. Keyed at the day, the delete clears every scheme for that day before the insert, so a
-- scheme that has stopped existing is gone. Deleting more than you insert is the safe direction; the test
-- test_vanishing_scheme_row_is_removed pins it.
-- ==============================================================================
{{ config(
    materialized = 'incremental',
    incremental_strategy = 'delete+insert',
    unique_key = ['merchant_id', 'business_date_ksa'],
    on_schema_change = 'fail'
) }}

WITH
{% if is_incremental() %}
changed AS (
    SELECT merchant_id, business_date_ksa
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }}
    WHERE source_ingested_at >= {{ since_last_arrival() }}
    UNION
    SELECT merchant_id, settlement_for_date_ksa
    FROM {{ source('slv_lakehouse', 'settlement_lines') }}
    WHERE source_ingested_at >= {{ since_last_arrival() }}
    UNION
    -- Same fourth leg as fact_merchant_settlement_recon, and it bites harder here: a late payment event
    -- does not change the bank line's arrival time, but it DOES move that line out of
    -- UNMATCHED_BANK_LINE and into its real scheme. That is a row appearing and a row disappearing on a
    -- day nothing else touched.
    SELECT s.merchant_id, s.settlement_for_date_ksa
    FROM {{ source('slv_lakehouse', 'settlement_lines') }} s
    JOIN {{ source('slv_lakehouse', 'payment_lifecycle') }} p ON p.payment_event_id = s.payment_event_id
    WHERE p.source_ingested_at >= {{ since_last_arrival() }}
),
{% endif %}
-- The scheme lookup reads the WHOLE payment table on purpose, never the scoped one. It answers "which
-- scheme is this bank line's payment?", and a bank line can legitimately state a settlement date that
-- differs from its payment's business date -- that mismatch is itself a break this platform reports.
-- Scoping the lookup to the changed days would make such a payment invisible to the join and relabel a
-- perfectly matched line as UNMATCHED_BANK_LINE. It is two narrow columns and no aggregation.
scheme_of AS (
    SELECT payment_event_id, payment_scheme FROM {{ source('slv_lakehouse', 'payment_lifecycle') }}
),
pay AS (
    SELECT p.payment_event_id, p.merchant_id, p.business_date_ksa, p.payment_scheme, p.event_type,
           p.amount_sar, p.source_ingested_at
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }} p
    {% if is_incremental() %}
    WHERE EXISTS (SELECT 1 FROM changed c
                  WHERE c.merchant_id = p.merchant_id AND c.business_date_ksa = p.business_date_ksa)
    {% endif %}
),
settle AS (
    SELECT s.payment_event_id, s.merchant_id, s.settlement_for_date_ksa, s.settlement_status, s.is_estimate,
           s.net_settled_sar, s.acquirer_mdr_fee_sar, s.acquirer_vat_sar, s.source_ingested_at
    FROM {{ source('slv_lakehouse', 'settlement_lines') }} s
    {% if is_incremental() %}
    WHERE EXISTS (SELECT 1 FROM changed c
                  WHERE c.merchant_id = s.merchant_id AND c.business_date_ksa = s.settlement_for_date_ksa)
    {% endif %}
),
captures AS (
    SELECT merchant_id, business_date_ksa, payment_scheme,
           SUM(CASE WHEN event_type = 'CAPTURE' THEN 1 ELSE 0 END)                           AS capture_count,
           SUM(CASE WHEN event_type = 'CAPTURE' THEN amount_sar ELSE 0 END)                  AS gross_captures_sar,
           SUM(CASE WHEN event_type IN ('REFUND', 'CHARGEBACK') THEN amount_sar ELSE 0 END)  AS refunds_and_disputes_sar
    FROM pay
    GROUP BY merchant_id, business_date_ksa, payment_scheme
),
fees AS (
    SELECT s.merchant_id, s.settlement_for_date_ksa AS business_date_ksa,
           COALESCE(p.payment_scheme, 'UNMATCHED_BANK_LINE')                                       AS payment_scheme,
           SUM(s.acquirer_mdr_fee_sar + s.acquirer_vat_sar)                                        AS acquirer_fees_sar,
           SUM(CASE WHEN s.is_estimate = {{ bool_true() }} THEN s.acquirer_mdr_fee_sar + s.acquirer_vat_sar ELSE 0 END) AS fees_estimated_sar,
           SUM(CASE WHEN s.settlement_status = 'PAID_BANK'   THEN s.net_settled_sar ELSE 0 END)                AS bank_paid_sar,
           SUM(CASE WHEN s.settlement_status = 'IN_TRANSIT'  THEN s.net_settled_sar ELSE 0 END)                AS in_transit_sar,
           SUM(CASE WHEN s.settlement_status = 'QUARANTINED' THEN s.net_settled_sar ELSE 0 END)                AS quarantined_sar
    FROM settle s
    LEFT JOIN scheme_of p ON p.payment_event_id = s.payment_event_id
    GROUP BY s.merchant_id, s.settlement_for_date_ksa, COALESCE(p.payment_scheme, 'UNMATCHED_BANK_LINE')
),
-- Keyed at the DAY, not at the grain, to match unique_key: every scheme row written for a day carries the
-- same watermark. A per-scheme watermark would let one scheme's cut-off run ahead of another's within the
-- same day, and since the delete clears the whole day, the laggard's days would stop being revisited.
arrival AS (
    SELECT merchant_id, business_date_ksa, MAX(source_ingested_at) AS last_source_arrival_at
    FROM (
        SELECT merchant_id, business_date_ksa, source_ingested_at FROM pay
        UNION ALL
        SELECT merchant_id, settlement_for_date_ksa, source_ingested_at FROM settle
    ) a
    GROUP BY merchant_id, business_date_ksa
),
spine AS (
    SELECT merchant_id, business_date_ksa, payment_scheme FROM captures
    UNION SELECT merchant_id, business_date_ksa, payment_scheme FROM fees
)
SELECT k.merchant_id, k.business_date_ksa, k.payment_scheme,
       CASE k.payment_scheme WHEN 'MADA' THEN 'MADA' WHEN 'VISA' THEN 'CARD' WHEN 'MASTERCARD' THEN 'CARD'
                             WHEN 'BNPL' THEN 'BNPL' WHEN 'SADAD' THEN 'SADAD'
                             WHEN 'UNMATCHED_BANK_LINE' THEN 'UNMATCHED_BANK_LINE' END              AS payment_method,
       CAST(COALESCE(c.capture_count, 0) AS INTEGER)                                                AS capture_count,
       CAST(COALESCE(c.gross_captures_sar, 0) AS DECIMAL(18,2))                                     AS gross_captures_sar,
       CAST(COALESCE(c.refunds_and_disputes_sar, 0) AS DECIMAL(18,2))                               AS refunds_and_disputes_sar,
       CAST(COALESCE(f.acquirer_fees_sar, 0) AS DECIMAL(18,2))                                      AS acquirer_fees_sar,
       CAST(COALESCE(f.fees_estimated_sar, 0) AS DECIMAL(18,2))                                     AS fees_estimated_sar,
       CAST(COALESCE(f.bank_paid_sar, 0) AS DECIMAL(18,2))                                          AS bank_paid_sar,
       CAST(COALESCE(f.in_transit_sar, 0) AS DECIMAL(18,2))                                         AS in_transit_sar,
       CAST(COALESCE(f.quarantined_sar, 0) AS DECIMAL(18,2))                                        AS quarantined_sar,
       COALESCE(w.last_source_arrival_at, {{ arrival_floor() }})                                    AS last_source_arrival_at
FROM spine k
LEFT JOIN captures c ON c.merchant_id = k.merchant_id AND c.business_date_ksa = k.business_date_ksa
                    AND c.payment_scheme = k.payment_scheme
LEFT JOIN fees f     ON f.merchant_id = k.merchant_id AND f.business_date_ksa = k.business_date_ksa
                    AND f.payment_scheme = k.payment_scheme
LEFT JOIN arrival w  ON w.merchant_id = k.merchant_id AND w.business_date_ksa = k.business_date_ksa

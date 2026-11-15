-- ==============================================================================
-- FILE: dbt/models/gold/fact_payment_method_daily.sql     (owner-approved addition, 2026-11-15)
-- Grain: merchant_id x business_date_ksa x payment_scheme. materialized = 'table'
-- Splits the reconciliation's captures, the BANK's own fees and the bank's settlement status (paid / in transit /
-- quarantined) (MDR + VAT from the settlement file, at the bank's
-- line grain; never recomputed) by payment scheme. A key spine over captures and settlement lines keeps every row;
-- a bank line without a payment event would appear as UNMATCHED_BANK_LINE, never be dropped.
-- Reconciles exactly to gld.fact_merchant_settlement_recon (tests/assert_payment_methods_reconcile_to_recon.sql).
-- ==============================================================================
WITH pay AS (
    SELECT payment_event_id, merchant_id, business_date_ksa, payment_scheme, event_type, amount_sar
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }}
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
    FROM {{ source('slv_lakehouse', 'settlement_lines') }} s
    LEFT JOIN pay p ON p.payment_event_id = s.payment_event_id
    GROUP BY s.merchant_id, s.settlement_for_date_ksa, COALESCE(p.payment_scheme, 'UNMATCHED_BANK_LINE')
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
       CAST(COALESCE(f.quarantined_sar, 0) AS DECIMAL(18,2))                                        AS quarantined_sar
FROM spine k
LEFT JOIN captures c ON c.merchant_id = k.merchant_id AND c.business_date_ksa = k.business_date_ksa
                    AND c.payment_scheme = k.payment_scheme
LEFT JOIN fees f     ON f.merchant_id = k.merchant_id AND f.business_date_ksa = k.business_date_ksa
                    AND f.payment_scheme = k.payment_scheme

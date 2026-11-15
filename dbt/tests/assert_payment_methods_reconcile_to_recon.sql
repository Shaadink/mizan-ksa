-- The payment-method split must add up, per merchant-day, to the reconciliation (captures, refunds, bank fees).
-- Returns the merchant-days that do not match (expected: none).
WITH pm AS (
    SELECT merchant_id, business_date_ksa, SUM(gross_captures_sar) AS g, SUM(refunds_and_disputes_sar) AS r,
           SUM(acquirer_fees_sar) AS f
    FROM {{ ref('fact_payment_method_daily') }}
    GROUP BY merchant_id, business_date_ksa
)
SELECT r.merchant_id, r.business_date_ksa
FROM {{ ref('fact_merchant_settlement_recon') }} r
LEFT JOIN pm ON pm.merchant_id = r.merchant_id AND pm.business_date_ksa = r.business_date_ksa
WHERE COALESCE(pm.g, 0) <> r.gross_captures_sar OR COALESCE(pm.r, 0) <> r.refunds_and_disputes_sar
   OR COALESCE(pm.f, 0) <> r.acquirer_fees_sar

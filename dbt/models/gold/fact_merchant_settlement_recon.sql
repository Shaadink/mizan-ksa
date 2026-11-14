-- ==============================================================================
-- FILE: dbt/models/gold/fact_merchant_settlement_recon.sql      (v1.1 design freeze)
-- Grain: merchant_id (acquirer MID) x business_date_ksa. materialized = 'table'
-- Contract: slv.settlement_lines has ONE row per payment_event_id. Events whose bank
-- file has not arrived carry an IN_TRANSIT expectation row (estimated MDR fee);
-- the real bank line replaces it. Amounts are positive; event_type carries the sign.
-- Only change from the spec reference: the GL leg signs amount_sar by debit_credit (ADR-007).
-- ==============================================================================
WITH captures AS (
    SELECT merchant_id, business_date_ksa,
           SUM(CASE WHEN event_type = 'CAPTURE'    THEN amount_sar ELSE 0 END) AS gross_captures_sar,
           SUM(CASE WHEN event_type = 'REFUND'     THEN amount_sar ELSE 0 END) AS refunds_sar,
           SUM(CASE WHEN event_type = 'CHARGEBACK' THEN amount_sar ELSE 0 END) AS chargebacks_sar,
           SUM(CASE WHEN event_type IN ('CAPTURE', 'REFUND', 'CHARGEBACK')
                     AND amount_sar IS NOT NULL THEN 0 ELSE 1 END)              AS unclassified_events
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }}
    GROUP BY merchant_id, business_date_ksa
),
settlements AS (
    SELECT merchant_id, settlement_for_date_ksa AS business_date_ksa,
           SUM(acquirer_mdr_fee_sar + acquirer_vat_sar)                                    AS total_fees_sar,
           SUM(CASE WHEN settlement_status = 'PAID_BANK'   THEN net_settled_sar ELSE 0 END) AS bank_paid_sar,
           SUM(CASE WHEN settlement_status = 'IN_TRANSIT'  THEN net_settled_sar ELSE 0 END) AS in_transit_sar,
           SUM(CASE WHEN settlement_status = 'QUARANTINED' THEN net_settled_sar ELSE 0 END) AS quarantined_sar
    FROM {{ source('slv_lakehouse', 'settlement_lines') }}
    GROUP BY merchant_id, settlement_for_date_ksa
),
gl AS (
    SELECT merchant_id, posting_date_ksa AS business_date_ksa,
           SUM(CASE WHEN debit_credit = 'S' THEN amount_sar ELSE -amount_sar END) AS gl_card_clearing_sar
    FROM {{ source('slv_lakehouse', 'erp_gl_journal_lines') }}
    WHERE gl_account_role = 'CARD_CLEARING'
    GROUP BY merchant_id, posting_date_ksa
),
spine AS (                       -- every key from ANY leg: nothing is dropped
    SELECT merchant_id, business_date_ksa FROM captures
    UNION SELECT merchant_id, business_date_ksa FROM settlements
    UNION SELECT merchant_id, business_date_ksa FROM gl
),
j AS (
    SELECT k.merchant_id, k.business_date_ksa,
           COALESCE(c.gross_captures_sar, 0)                           AS gross_captures_sar,
           COALESCE(c.refunds_sar, 0) + COALESCE(c.chargebacks_sar, 0) AS refunds_and_disputes_sar,
           COALESCE(s.total_fees_sar, 0)                               AS acquirer_fees_sar,
           COALESCE(s.bank_paid_sar, 0)                                AS bank_paid_sar,
           COALESCE(s.in_transit_sar, 0)                               AS in_transit_sar,
           COALESCE(s.quarantined_sar, 0)                              AS quarantined_sar,
           COALESCE(g.gl_card_clearing_sar, 0)                         AS gl_card_clearing_sar,
           COALESCE(c.unclassified_events, 0)                          AS unclassified_events
    FROM spine k
    LEFT JOIN captures    c ON c.merchant_id = k.merchant_id AND c.business_date_ksa = k.business_date_ksa
    LEFT JOIN settlements s ON s.merchant_id = k.merchant_id AND s.business_date_ksa = k.business_date_ksa
    LEFT JOIN gl          g ON g.merchant_id = k.merchant_id AND g.business_date_ksa = k.business_date_ksa
)
SELECT merchant_id, business_date_ksa,
       CAST(gross_captures_sar AS DECIMAL(18,2))                                      AS gross_captures_sar,
       CAST(refunds_and_disputes_sar AS DECIMAL(18,2))                                AS refunds_and_disputes_sar,
       CAST(acquirer_fees_sar AS DECIMAL(18,2))                                       AS acquirer_fees_sar,
       CAST(gross_captures_sar - refunds_and_disputes_sar - acquirer_fees_sar
            AS DECIMAL(18,2))                                                         AS expected_net_payable_sar,
       CAST(bank_paid_sar AS DECIMAL(18,2))                                           AS bank_paid_sar,
       CAST(in_transit_sar AS DECIMAL(18,2))                                          AS in_transit_sar,
       CAST(quarantined_sar AS DECIMAL(18,2))                                         AS quarantined_sar,
       CAST(gl_card_clearing_sar AS DECIMAL(18,2))                                    AS gl_card_clearing_sar,
       CAST((gross_captures_sar - refunds_and_disputes_sar - acquirer_fees_sar)
            - (bank_paid_sar + in_transit_sar + quarantined_sar) AS DECIMAL(18,2))     AS unexplained_bank_variance_sar,
       CAST((gross_captures_sar - refunds_and_disputes_sar) - gl_card_clearing_sar
            AS DECIMAL(18,2))                                                         AS unexplained_gl_variance_sar,
       unclassified_events
FROM j

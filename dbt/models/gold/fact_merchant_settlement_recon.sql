-- ==============================================================================
-- FILE: dbt/models/gold/fact_merchant_settlement_recon.sql      (v1.1 design freeze)
-- Grain: merchant_id (acquirer MID) x business_date_ksa. materialized = 'table'
-- Contract: slv.settlement_lines has ONE row per payment_event_id. Events whose bank
-- file has not arrived carry an IN_TRANSIT expectation row (estimated MDR fee);
-- the real bank line replaces it. Amounts are positive; event_type carries the sign.
-- Only change from the spec reference: the GL leg signs amount_sar by debit_credit (ADR-007).
--
-- WHICH DATE THIS RECONCILES ON -- read this before assuming a bug.
-- The settlement leg keys on `settlement_for_date_ksa`: the ORIGINATING CAPTURE business date that the
-- bank line pays for, NOT the date the bank file arrived. That is the whole reason a T+1 platform can
-- reconcile a day at all. Keying on the file's own arrival date instead would shift every bank line one
-- day away from the captures it settles, and every single merchant-day would show a false variance in
-- both directions -- a textbook off-by-one that looks like a reconciliation and balances to nothing.
--
-- So the three legs line up on one meaning of "day":
--   captures     business_date_ksa      the day the sale happened (Asia/Riyadh)
--   settlements  settlement_for_date_ksa the capture day this bank line pays for
--   gl           posting_date_ksa        the day the ledger booked it
-- The bank file's own arrival date is carried separately on slv.settlement_lines and is NOT a join key.
--
-- What a real acquirer would need on top of this: an independent VALUE DATE from the bank, which can
-- differ from T+1 by scheme, merchant category and the Friday/Saturday KSA weekend. Here the synthetic
-- bank file states the capture day it settles, so one mapping suffices. Against a real file the spine
-- would gain a date-mapping leg (capture date -> value date) and the in-transit bucket would carry a lag
-- distribution rather than a single T+1 flag. Not implemented; stated so it is not mistaken for solved.
--
-- Also not implemented, and the harder of the two: cross-period chargeback matching. A chargeback 45 days
-- after its capture lands on its OWN business date, reducing that day's net while the capture it claws
-- back sat in a different month. Disputes here are counted on their own event date.
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

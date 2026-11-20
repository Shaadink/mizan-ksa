-- ==============================================================================
-- FILE: dbt/models/gold/fact_merchant_settlement_recon.sql      (v1.1 design freeze)
-- Grain: merchant_id (acquirer MID) x business_date_ksa. materialized = 'incremental' (ADR-015)
-- Contract: slv.settlement_lines has ONE row per payment_event_id. Events whose bank
-- file has not arrived carry an IN_TRANSIT expectation row (estimated MDR fee);
-- the real bank line replaces it. Amounts are positive; event_type carries the sign.
-- Only change from the spec reference: the GL leg signs amount_sar by debit_credit (ADR-007).
--
-- INCREMENTAL, AND WHY IT IS STILL A TABLE.
-- The frozen rule is "Gold materialized as tables so Direct Lake never falls back to DirectQuery". An
-- incremental model IS a physical table -- dbt creates it once and then deletes and inserts rows in it.
-- Nothing becomes a view, so Direct Lake is unaffected and the frozen rule still holds. What changes is
-- only HOW the table is refreshed. Owner-approved 2026-11-20; see docs/adr/ADR-015.
--
-- A day is rebuilt WHOLE or not at all. The incremental run finds the merchant-days touched by anything
-- that arrived since the last build, deletes those days, and re-derives them from all of Silver. It never
-- appends to a day. A reconciliation is a sum over three legs, so a day half-built from a late bank file
-- would balance to nothing -- see dbt/macros/incremental_rebuild.sql for the full argument.
--
-- WHY NOT A LOOKBACK WINDOW ("rebuild the last 7 days"), which is the usual shortcut: because this
-- domain's whole problem is late data. A chargeback can land 45 days after the capture it claws back, and
-- a bank file can be re-sent weeks later. A fixed window would silently stop reconciling exactly the cases
-- this model exists to catch. The watermark has no window: however late a row is, the day it belongs to is
-- rebuilt.
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
-- `source_ingested_at` -- the incremental watermark -- is a third, different thing again: when the row
-- landed in Bronze. It is never a join key either.
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
{{ config(
    materialized = 'incremental',
    incremental_strategy = 'delete+insert',
    unique_key = ['merchant_id', 'business_date_ksa'],
    on_schema_change = 'fail'
) }}

WITH
{% if is_incremental() %}
-- The merchant-days touched by anything that arrived since the last build, from ANY of the three legs.
-- A day that only a GL line moved is in here too, which is the point: it is exactly the day whose GL
-- variance changed.
changed AS (
    SELECT merchant_id, business_date_ksa
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }}
    WHERE source_ingested_at >= {{ since_last_arrival() }}
    UNION
    SELECT merchant_id, settlement_for_date_ksa
    FROM {{ source('slv_lakehouse', 'settlement_lines') }}
    WHERE source_ingested_at >= {{ since_last_arrival() }}
    UNION
    SELECT merchant_id, posting_date_ksa
    FROM {{ source('slv_lakehouse', 'erp_gl_journal_lines') }}
    WHERE gl_account_role = 'CARD_CLEARING' AND source_ingested_at >= {{ since_last_arrival() }}
    UNION
    -- The fourth leg, and the one that is easy to miss. A bank line that arrived BEFORE a watermark can
    -- still change meaning after it: an orphan line whose payment event had not arrived is QUARANTINED,
    -- and when the payment finally lands the same line becomes PAID_BANK. Money moves between
    -- quarantined_sar and bank_paid_sar, but the LINE's own arrival time never moves -- it is the bank
    -- file's, and that file is old. Without this leg the day would keep the quarantined figure for good.
    -- So: any settlement day whose matching payment event arrived since the cut-off is also changed.
    SELECT s.merchant_id, s.settlement_for_date_ksa
    FROM {{ source('slv_lakehouse', 'settlement_lines') }} s
    JOIN {{ source('slv_lakehouse', 'payment_lifecycle') }} p ON p.payment_event_id = s.payment_event_id
    WHERE p.source_ingested_at >= {{ since_last_arrival() }}
),
{% endif %}
-- Each leg is scoped to the changed days FIRST, so the aggregates below read only those days. Scoping
-- after the GROUP BY would give the same answer and none of the saving.
pay AS (
    SELECT p.merchant_id, p.business_date_ksa, p.event_type, p.amount_sar, p.source_ingested_at
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }} p
    {% if is_incremental() %}
    WHERE EXISTS (SELECT 1 FROM changed c
                  WHERE c.merchant_id = p.merchant_id AND c.business_date_ksa = p.business_date_ksa)
    {% endif %}
),
settle AS (
    SELECT s.merchant_id, s.settlement_for_date_ksa, s.settlement_status, s.net_settled_sar,
           s.acquirer_mdr_fee_sar, s.acquirer_vat_sar, s.source_ingested_at
    FROM {{ source('slv_lakehouse', 'settlement_lines') }} s
    {% if is_incremental() %}
    WHERE EXISTS (SELECT 1 FROM changed c
                  WHERE c.merchant_id = s.merchant_id AND c.business_date_ksa = s.settlement_for_date_ksa)
    {% endif %}
),
glines AS (
    SELECT g.merchant_id, g.posting_date_ksa, g.debit_credit, g.amount_sar, g.source_ingested_at
    FROM {{ source('slv_lakehouse', 'erp_gl_journal_lines') }} g
    WHERE g.gl_account_role = 'CARD_CLEARING'
    {% if is_incremental() %}
      AND EXISTS (SELECT 1 FROM changed c
                  WHERE c.merchant_id = g.merchant_id AND c.business_date_ksa = g.posting_date_ksa)
    {% endif %}
),
captures AS (
    SELECT merchant_id, business_date_ksa,
           SUM(CASE WHEN event_type = 'CAPTURE'    THEN amount_sar ELSE 0 END) AS gross_captures_sar,
           SUM(CASE WHEN event_type = 'REFUND'     THEN amount_sar ELSE 0 END) AS refunds_sar,
           SUM(CASE WHEN event_type = 'CHARGEBACK' THEN amount_sar ELSE 0 END) AS chargebacks_sar,
           SUM(CASE WHEN event_type IN ('CAPTURE', 'REFUND', 'CHARGEBACK')
                     AND amount_sar IS NOT NULL THEN 0 ELSE 1 END)              AS unclassified_events
    FROM pay
    GROUP BY merchant_id, business_date_ksa
),
settlements AS (
    SELECT merchant_id, settlement_for_date_ksa AS business_date_ksa,
           SUM(acquirer_mdr_fee_sar + acquirer_vat_sar)                                    AS total_fees_sar,
           SUM(CASE WHEN settlement_status = 'PAID_BANK'   THEN net_settled_sar ELSE 0 END) AS bank_paid_sar,
           SUM(CASE WHEN settlement_status = 'IN_TRANSIT'  THEN net_settled_sar ELSE 0 END) AS in_transit_sar,
           SUM(CASE WHEN settlement_status = 'QUARANTINED' THEN net_settled_sar ELSE 0 END) AS quarantined_sar
    FROM settle
    GROUP BY merchant_id, settlement_for_date_ksa
),
gl AS (
    SELECT merchant_id, posting_date_ksa AS business_date_ksa,
           SUM(CASE WHEN debit_credit = 'S' THEN amount_sar ELSE -amount_sar END) AS gl_card_clearing_sar
    FROM glines
    GROUP BY merchant_id, posting_date_ksa
),
-- The newest arrival that contributed to each day, from whichever leg it came. This is what the NEXT
-- incremental run reads as its cut-off, so it must cover every leg or that leg's late data would be
-- invisible from then on.
arrival AS (
    SELECT merchant_id, business_date_ksa, MAX(source_ingested_at) AS last_source_arrival_at
    FROM (
        SELECT merchant_id, business_date_ksa, source_ingested_at FROM pay
        UNION ALL
        SELECT merchant_id, settlement_for_date_ksa, source_ingested_at FROM settle
        UNION ALL
        SELECT merchant_id, posting_date_ksa, source_ingested_at FROM glines
    ) a
    GROUP BY merchant_id, business_date_ksa
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
           COALESCE(c.unclassified_events, 0)                          AS unclassified_events,
           COALESCE(w.last_source_arrival_at, {{ arrival_floor() }})   AS last_source_arrival_at
    FROM spine k
    LEFT JOIN captures    c ON c.merchant_id = k.merchant_id AND c.business_date_ksa = k.business_date_ksa
    LEFT JOIN settlements s ON s.merchant_id = k.merchant_id AND s.business_date_ksa = k.business_date_ksa
    LEFT JOIN gl          g ON g.merchant_id = k.merchant_id AND g.business_date_ksa = k.business_date_ksa
    LEFT JOIN arrival     w ON w.merchant_id = k.merchant_id AND w.business_date_ksa = k.business_date_ksa
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
       unclassified_events,
       last_source_arrival_at
FROM j

-- ==============================================================================
-- FILE: dbt/models/gold/fact_merchant_dispute_monitor.sql   (owner-approved addition, 2026-11-19)
-- Grain: merchant_id, over the whole dataset window. materialized = 'table'
--
-- Card schemes watch each merchant's dispute (chargeback) ratio and put the ones that cross the line into a
-- monitoring programme: fines, reserves, and eventually losing the ability to accept cards. An acquiring and
-- settlement platform is the thing that has to run that check, so MIZAN runs it on data it already carries --
-- CAPTURE, REFUND and CHARGEBACK are native event types in slv.payment_lifecycle. No new source.
--
-- The point of this model is the FLOOR, not the ratio.
-- On this dataset the ratio alone flags 71 of 121 merchants (59% of the portfolio, i.e. useless), because a
-- merchant with 43 captures and 3 disputes reads 6.98% and means nothing. Requiring a minimum dispute count as
-- well -- which is exactly why the real programmes have one -- flags 1. Both numbers are emitted so the
-- difference is visible rather than asserted: `breaches_ratio` and `in_monitoring_programme`.
--
-- Window, stated rather than buried: the real programmes run on a calendar month. This dataset spans about three
-- weeks, so the window here is the dataset's own span and `window_days` carries it. A monthly split would cut the
-- span into a 17-day February and a 3-day March and make the counts less meaningful, not more.
--
-- Thresholds come from `vars` in dbt_project.yml. They are read from secondary sources, not from the scheme
-- rulebooks, and they change -- see HONESTY.md.
-- ==============================================================================
WITH pay AS (
    SELECT merchant_id, business_date_ksa, event_type, amount_sar
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }}
),
window_span AS (
    SELECT MIN(business_date_ksa) AS window_start_ksa, MAX(business_date_ksa) AS window_end_ksa FROM pay
),
per_merchant AS (
    SELECT merchant_id,
           SUM(CASE WHEN event_type = 'CAPTURE'    THEN 1 ELSE 0 END)          AS capture_count,
           SUM(CASE WHEN event_type = 'CAPTURE'    THEN amount_sar ELSE 0 END) AS captures_sar,
           SUM(CASE WHEN event_type = 'REFUND'     THEN 1 ELSE 0 END)          AS refund_count,
           SUM(CASE WHEN event_type = 'REFUND'     THEN amount_sar ELSE 0 END) AS refunds_sar,
           SUM(CASE WHEN event_type = 'CHARGEBACK' THEN 1 ELSE 0 END)          AS dispute_count,
           SUM(CASE WHEN event_type = 'CHARGEBACK' THEN amount_sar ELSE 0 END) AS disputes_sar
    FROM pay
    GROUP BY merchant_id
)
SELECT m.merchant_id,
       w.window_start_ksa,
       w.window_end_ksa,
       CAST({{ date_diff_days('w.window_start_ksa', 'w.window_end_ksa') }} + 1 AS INTEGER)   AS window_days,
       CAST(m.capture_count AS INTEGER)                                              AS capture_count,
       CAST(m.captures_sar AS DECIMAL(18,2))                                         AS captures_sar,
       CAST(m.refund_count AS INTEGER)                                               AS refund_count,
       CAST(m.refunds_sar AS DECIMAL(18,2))                                          AS refunds_sar,
       CAST(m.dispute_count AS INTEGER)                                              AS dispute_count,
       CAST(m.disputes_sar AS DECIMAL(18,2))                                         AS disputes_sar,
       -- A ratio is not money, but it must not be a float either: the no_float_columns guard covers the model.
       CAST(CASE WHEN m.capture_count = 0 THEN 0
                 ELSE 100.0 * m.dispute_count / m.capture_count END AS DECIMAL(9,4)) AS dispute_ratio_pct,
       CAST(CASE WHEN m.capture_count = 0 THEN 0
                 ELSE 100.0 * m.refund_count / m.capture_count END AS DECIMAL(9,4))  AS refund_ratio_pct,
       -- What the naive check would say on its own: kept so the floor's effect is visible, not claimed.
       CASE WHEN m.capture_count > 0
             AND 100.0 * m.dispute_count / m.capture_count >= {{ var('dispute_ratio_pct_threshold') }}
            THEN {{ bool_true() }} ELSE {{ bool_false() }} END                        AS breaches_ratio,
       CASE WHEN m.dispute_count >= {{ var('dispute_count_threshold') }}
            THEN {{ bool_true() }} ELSE {{ bool_false() }} END                        AS meets_count_floor,
       -- The actual finding: both conditions, which is how the real programmes are written.
       CASE WHEN m.capture_count > 0
             AND 100.0 * m.dispute_count / m.capture_count >= {{ var('dispute_ratio_pct_threshold') }}
             AND m.dispute_count >= {{ var('dispute_count_threshold') }}
            THEN {{ bool_true() }} ELSE {{ bool_false() }} END                        AS in_monitoring_programme
FROM per_merchant m
CROSS JOIN window_span w

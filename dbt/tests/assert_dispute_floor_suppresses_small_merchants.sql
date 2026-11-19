-- The count floor is the whole point of the model, so it gets a test that fails if it stops working.
--
-- Two things must hold at once:
--   1. the floor actually suppresses something -- there must exist merchants that breach the ratio but are NOT
--      in the programme, otherwise the floor is decorative and the model is the naive version in disguise;
--   2. nothing is in the programme without meeting BOTH conditions.
--
-- (1) is the one that would rot silently: regenerate the data with fewer small merchants, or raise the ratio
-- threshold far enough, and the model keeps returning rows while quietly ceasing to make its own point.
WITH m AS (
    SELECT * FROM {{ ref('fact_merchant_dispute_monitor') }}
),
checks AS (
    SELECT 'in programme without meeting both conditions' AS failure
    FROM m
    WHERE in_monitoring_programme = {{ bool_true() }}
      AND NOT (breaches_ratio = {{ bool_true() }} AND meets_count_floor = {{ bool_true() }})

    UNION ALL

    SELECT 'the count floor suppresses nothing: it is decorative' AS failure
    WHERE NOT EXISTS (
        SELECT 1 FROM m
        WHERE breaches_ratio = {{ bool_true() }}
          AND in_monitoring_programme = {{ bool_false() }}
    )
)
SELECT * FROM checks

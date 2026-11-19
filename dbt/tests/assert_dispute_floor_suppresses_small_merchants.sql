-- The count floor is the whole point of the model, so it gets a test that fails if it stops working.
--
-- Two things must hold at once:
--   1. the floor actually suppresses something -- there must exist merchants that breach the ratio but are NOT
--      in the programme, otherwise the floor is decorative and the model is the naive version in disguise;
--   2. nothing is in the programme without meeting BOTH conditions.
--
-- (1) is the one that would rot silently: regenerate the data with fewer small merchants, or raise the ratio
-- threshold far enough, and the model keeps returning rows while quietly ceasing to make its own point.
--
-- Written without a leading CTE on purpose. dbt wraps a test's SQL in `select count(*) from ( ... )`, and
-- T-SQL rejects a WITH clause inside a derived table -- on Fabric this failed with "Invalid object name 'm'"
-- while passing on DuckDB. The ref() is repeated instead, which costs a few characters and builds on both.
-- The second arm uses HAVING with no GROUP BY (one group = the whole table); `GROUP BY 'x'` is a DuckDB-ism
-- that T-SQL rejects with "Each GROUP BY expression must contain at least one column".
SELECT 'in programme without meeting both conditions' AS failure
FROM {{ ref('fact_merchant_dispute_monitor') }}
WHERE in_monitoring_programme = {{ bool_true() }}
  AND NOT (breaches_ratio = {{ bool_true() }} AND meets_count_floor = {{ bool_true() }})

UNION ALL

SELECT 'the count floor suppresses nothing: it is decorative' AS failure
FROM {{ ref('fact_merchant_dispute_monitor') }}
HAVING SUM(CASE WHEN breaches_ratio = {{ bool_true() }}
                 AND in_monitoring_programme = {{ bool_false() }} THEN 1 ELSE 0 END) = 0

-- Gregorian calendar with the Saudi weekend (Friday + Saturday since 2013-06-29).
-- Hijri (versioned Umm al-Qura) columns are added in Phase 5 from the calendar seed.
WITH d AS (
    {{ date_spine('2025-01-01', '2028-01-01') }}
),
x AS (
    SELECT calendar_date,
           {{ dbt.datediff("CAST('2024-01-01' AS DATE)", "calendar_date", "day") }} AS days_since_monday
    FROM d
)
SELECT CAST(YEAR(calendar_date) * 10000 + MONTH(calendar_date) * 100 + DAY(calendar_date) AS INT) AS date_key,
       calendar_date,
       CAST(YEAR(calendar_date) AS INT)                     AS gregorian_year,
       CAST(MONTH(calendar_date) AS INT)                    AS gregorian_month,
       CAST(DAY(calendar_date) AS INT)                      AS gregorian_day,
       CAST((MONTH(calendar_date) - 1) / 3 + 1 AS INT)      AS gregorian_quarter,
       CAST(days_since_monday % 7 + 1 AS INT)               AS iso_day_of_week,
       CASE WHEN days_since_monday % 7 + 1 IN (5, 6) THEN 1 ELSE 0 END AS is_saudi_weekend
FROM x

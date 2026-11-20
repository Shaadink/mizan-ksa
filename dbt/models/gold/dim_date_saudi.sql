-- STAYS A FULL TABLE (ADR-015). Not incremental, on purpose.
-- An official moon-sighting announcement moves the START of a Hijri month, and every day after it is then
-- re-numbered -- the month before the override grows or shrinks by the same days. One new seed row rewrites
-- a stretch of the calendar in both directions. There is no "changed key" to find: the thing that changed is
-- a boundary, not a row. It is three years of dates and it rebuilds in under a second.
-- Gregorian + versioned Umm al-Qura Hijri calendar with official-announcement overrides; Saudi weekend Fri + Sat.
-- An override moves the START of a Hijri month; every day is then re-numbered from the effective month starts,
-- so the month before an override shrinks or grows by the same days. is_override_adjusted flags changed days.
WITH d AS (
    {{ date_spine('2025-01-01', '2028-01-01') }}
),
uaq AS (
    SELECT calendar_date, hijri_year, hijri_month, hijri_day, calendar_version
    FROM {{ ref('umm_al_qura_calendar') }}
),
uaq_months AS (
    SELECT hijri_year, hijri_month, MIN(calendar_date) AS uaq_start
    FROM uaq
    GROUP BY hijri_year, hijri_month
),
months AS (
    SELECT m.hijri_year, m.hijri_month,
           COALESCE(o.announced_start_date, m.uaq_start) AS month_start
    FROM uaq_months m
    LEFT JOIN {{ ref('hijri_announcement_overrides') }} o
           ON o.hijri_year = m.hijri_year AND o.hijri_month = m.hijri_month
),
bounded AS (
    SELECT hijri_year, hijri_month, month_start,
           LEAD(month_start) OVER (ORDER BY month_start) AS next_start
    FROM months
),
h AS (
    SELECT d.calendar_date, b.hijri_year, b.hijri_month,
           CAST({{ dbt.datediff("b.month_start", "d.calendar_date", "day") }} + 1 AS INT) AS hijri_day,
           {{ dbt.datediff("CAST('2024-01-01' AS DATE)", "d.calendar_date", "day") }}      AS days_since_monday
    FROM d
    JOIN bounded b
      ON d.calendar_date >= b.month_start AND (b.next_start IS NULL OR d.calendar_date < b.next_start)
)
SELECT CAST(YEAR(h.calendar_date) * 10000 + MONTH(h.calendar_date) * 100 + DAY(h.calendar_date) AS INT) AS date_key,
       h.calendar_date,
       CAST(YEAR(h.calendar_date) AS INT)                     AS gregorian_year,
       CAST(MONTH(h.calendar_date) AS INT)                    AS gregorian_month,
       CAST(DAY(h.calendar_date) AS INT)                      AS gregorian_day,
       CAST((MONTH(h.calendar_date) - 1) / 3 + 1 AS INT)      AS gregorian_quarter,
       CAST(h.days_since_monday % 7 + 1 AS INT)               AS iso_day_of_week,
       CASE WHEN h.days_since_monday % 7 + 1 IN (5, 6) THEN 1 ELSE 0 END AS is_saudi_weekend,
       CAST(h.hijri_year AS INT)                              AS hijri_year,
       CAST(h.hijri_month AS INT)                             AS hijri_month,
       h.hijri_day,
       CAST(h.hijri_year * 10000 + h.hijri_month * 100 + h.hijri_day AS INT) AS hijri_date_key,
       CASE h.hijri_month WHEN 1 THEN 'MUHARRAM' WHEN 2 THEN 'SAFAR' WHEN 3 THEN 'RABI_AL_AWWAL'
            WHEN 4 THEN 'RABI_AL_THANI' WHEN 5 THEN 'JUMADA_AL_ULA' WHEN 6 THEN 'JUMADA_AL_AKHIRAH'
            WHEN 7 THEN 'RAJAB' WHEN 8 THEN 'SHABAN' WHEN 9 THEN 'RAMADAN' WHEN 10 THEN 'SHAWWAL'
            WHEN 11 THEN 'DHU_AL_QADAH' WHEN 12 THEN 'DHU_AL_HIJJAH' END AS hijri_month_name,
       CASE WHEN h.hijri_month = 9 THEN 1 ELSE 0 END          AS is_ramadan,
       CASE WHEN h.hijri_month = 9 THEN h.hijri_day END       AS ramadan_day,   -- aligns Ramadan YoY
       CASE WHEN h.hijri_year = u.hijri_year AND h.hijri_month = u.hijri_month AND h.hijri_day = u.hijri_day
            THEN 0 ELSE 1 END                                 AS is_override_adjusted,
       CASE WHEN h.hijri_year = u.hijri_year AND h.hijri_month = u.hijri_month AND h.hijri_day = u.hijri_day
            THEN u.calendar_version ELSE CONCAT(u.calendar_version, '+ANNOUNCEMENT') END AS calendar_version
FROM h
JOIN uaq u ON u.calendar_date = h.calendar_date

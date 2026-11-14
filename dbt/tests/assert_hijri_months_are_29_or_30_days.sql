-- Every complete Hijri month in the dimension has 29 or 30 days (Umm al-Qura and announcements alike).
WITH m AS (
    SELECT hijri_year, hijri_month, COUNT(*) AS n_days, MIN(hijri_day) AS first_day
    FROM {{ ref('dim_date_saudi') }}
    GROUP BY hijri_year, hijri_month
)
SELECT * FROM m
WHERE first_day = 1
  AND n_days NOT IN (29, 30)
  AND hijri_year * 100 + hijri_month < (SELECT MAX(hijri_year * 100 + hijri_month) FROM m)

-- NDMO scorecard (Module 6): the six data-quality dimensions on the key financial tables, plus the
-- over-classification share of every Lakehouse table (columns above their own tier only because a SECRET column
-- shares the table). One row per (metric_family, dimension, subject_table). Scores are DECIMAL, never FLOAT.
WITH q AS (
    SELECT 'COMPLETENESS' AS dimension, 'slv.payment_lifecycle' AS subject_table,
           SUM(CASE WHEN merchant_id IS NOT NULL AND amount_sar IS NOT NULL AND business_date_ksa IS NOT NULL
                    THEN 1 ELSE 0 END) AS numerator, COUNT(*) AS denominator, 99.90 AS threshold_pct
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }}
    UNION ALL
    SELECT 'UNIQUENESS', 'slv.settlement_lines', COUNT(DISTINCT payment_event_id), COUNT(*), 100.00
    FROM {{ source('slv_lakehouse', 'settlement_lines') }}
    UNION ALL
    SELECT 'VALIDITY', 'slv.payment_lifecycle',
           SUM(CASE WHEN event_type IN ('CAPTURE', 'REFUND', 'CHARGEBACK') THEN 1 ELSE 0 END), COUNT(*), 100.00
    FROM {{ source('slv_lakehouse', 'payment_lifecycle') }}
    UNION ALL
    SELECT 'CONSISTENCY', 'gld.fact_merchant_settlement_recon',
           SUM(CASE WHEN unexplained_bank_variance_sar = 0 AND unexplained_gl_variance_sar = 0 THEN 1 ELSE 0 END),
           COUNT(*), 100.00
    FROM {{ ref('fact_merchant_settlement_recon') }}
    UNION ALL
    SELECT 'TIMELINESS', 'slv.settlement_lines',
           SUM(CASE WHEN settlement_status = 'PAID_BANK' THEN 1 ELSE 0 END),
           SUM(CASE WHEN settlement_status IN ('PAID_BANK', 'IN_TRANSIT') THEN 1 ELSE 0 END), 90.00
    FROM {{ source('slv_lakehouse', 'settlement_lines') }}
    UNION ALL
    SELECT 'ACCURACY', 'slv.zatca_invoice_documents',
           SUM(CASE WHEN state IN ('CLEARED', 'REPORTED', 'ACCEPTED_WITH_WARNINGS') THEN 1 ELSE 0 END), COUNT(*),
           99.90
    FROM {{ source('slv_lakehouse', 'zatca_invoice_documents') }}
),
c AS (
    SELECT CONCAT(schema_name, '.', table_name) AS subject_table,
           MAX(table_classification)                                                    AS table_classification,
           SUM(CASE WHEN is_over_classified = {{ bool_true() }} THEN 0 ELSE 1 END)        AS numerator,
           COUNT(*)                                                                     AS denominator
    FROM {{ source('meta_lakehouse', 'column_classification') }}
    GROUP BY schema_name, table_name
)
SELECT 'DATA_QUALITY' AS metric_family, dimension, subject_table,
       CAST(numerator AS BIGINT) AS numerator, CAST(denominator AS BIGINT) AS denominator,
       CAST(100.0 * numerator / NULLIF(denominator, 0) AS DECIMAL(5,2))  AS score_pct,
       CAST(threshold_pct AS DECIMAL(5,2))                                AS threshold_pct,
       CASE WHEN 100.0 * numerator / NULLIF(denominator, 0) >= threshold_pct THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(NULL AS VARCHAR(16))                                          AS table_classification
FROM q
UNION ALL
SELECT 'CLASSIFICATION', 'CORRECTLY_CLASSIFIED_COLUMNS', subject_table,
       CAST(numerator AS BIGINT), CAST(denominator AS BIGINT),
       CAST(100.0 * numerator / NULLIF(denominator, 0) AS DECIMAL(5,2)),
       CAST(100.00 AS DECIMAL(5,2)),
       CASE WHEN numerator = denominator THEN 'PASS' ELSE 'SPLIT_RECOMMENDED' END,
       table_classification
FROM c

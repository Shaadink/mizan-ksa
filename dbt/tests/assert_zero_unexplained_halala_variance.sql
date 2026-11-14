-- FILE: dbt/tests/assert_zero_unexplained_halala_variance.sql   (fails the build on any row)
SELECT *
FROM {{ ref('fact_merchant_settlement_recon') }}
WHERE unexplained_bank_variance_sar <> 0
   OR unexplained_gl_variance_sar <> 0
   OR unclassified_events > 0

-- Grain: 1 row per document in the legal chain with a definitive ZATCA outcome: accepted (CLEARED / REPORTED /
-- ACCEPTED_WITH_WARNINGS) or CONFIRMED_REJECTION. A 400 rejection keeps its ICV in the chain and is corrected by a
-- new document, so the ledger shows it (25,001 documents, not 25,000). "Accepted" figures filter on state.
SELECT invoice_uuid, request_id, order_id, egs_id, icv, invoice_flow, document_type, state,
       issue_date_ksa, gl_key, corrects_invoice_uuid, attempts,
       CAST(total_incl_vat_sar AS DECIMAL(18,2)) AS total_incl_vat_sar
FROM {{ source('slv_lakehouse', 'zatca_invoice_documents') }}
WHERE state IN ('CLEARED', 'REPORTED', 'ACCEPTED_WITH_WARNINGS', 'CONFIRMED_REJECTION')

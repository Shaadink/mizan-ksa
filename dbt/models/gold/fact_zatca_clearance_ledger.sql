-- Grain: 1 row per accepted invoice or credit note (CLEARED / REPORTED / ACCEPTED_WITH_WARNINGS).
-- Rejected documents stay in the legal chain (audit.zatca_chain_journal) but are not ledger rows.
SELECT invoice_uuid, request_id, order_id, egs_id, icv, invoice_flow, document_type, state,
       issue_date_ksa, gl_key, corrects_invoice_uuid, attempts,
       CAST(total_incl_vat_sar AS DECIMAL(18,2)) AS total_incl_vat_sar
FROM {{ source('slv_lakehouse', 'zatca_invoice_documents') }}
WHERE state IN ('CLEARED', 'REPORTED', 'ACCEPTED_WITH_WARNINGS')

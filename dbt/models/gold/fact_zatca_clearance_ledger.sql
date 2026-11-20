-- Grain: 1 row per document in the legal chain with a definitive ZATCA outcome: accepted (CLEARED / REPORTED /
-- ACCEPTED_WITH_WARNINGS) or CONFIRMED_REJECTION. A 400 rejection keeps its ICV in the chain and is corrected by a
-- new document, so the ledger shows it (25,001 documents, not 25,000). "Accepted" figures filter on state.
--
-- materialized = 'incremental' (ADR-015), keyed on invoice_uuid -- the only natural key here, and the same
-- key the GL idempotency rule uses.
--
-- The watermark for this model is slv.zatca_invoice_documents.source_ingested_at, which comes from
-- ctl.invoice_outbox.updated_at and NOT from the Bronze request's arrival time. That distinction is the
-- whole correctness argument: a document's state is decided by what ZATCA answers, long after the request
-- landed in Bronze. If the watermark were Bronze's, a document that moved from SUBMITTING to CLEARED would
-- carry an unchanged timestamp, sit below the cut-off, and never be inserted. The ledger would be missing
-- exactly the documents that had just succeeded.
--
-- The invariant this depends on, stated plainly because it is a promise the rest of the code has to keep:
-- any write that changes a document's state must set updated_at. src/mizan/spark/zatca_land.py does.
--
-- Safe in the other direction by construction: the four states this model selects are TERMINAL. A document
-- never leaves the ledger once it is in, so delete+insert on invoice_uuid never has to remove a row that
-- the rebuild will not replace.
{{ config(
    materialized = 'incremental',
    incremental_strategy = 'delete+insert',
    unique_key = 'invoice_uuid',
    on_schema_change = 'fail'
) }}

SELECT invoice_uuid, request_id, order_id, egs_id, icv, invoice_flow, document_type, state,
       issue_date_ksa, gl_key, corrects_invoice_uuid, attempts,
       CAST(total_incl_vat_sar AS DECIMAL(18,2)) AS total_incl_vat_sar,
       source_ingested_at AS last_source_arrival_at
FROM {{ source('slv_lakehouse', 'zatca_invoice_documents') }}
WHERE state IN ('CLEARED', 'REPORTED', 'ACCEPTED_WITH_WARNINGS', 'CONFIRMED_REJECTION')
{% if is_incremental() %}
  AND source_ingested_at >= {{ since_last_arrival() }}
{% endif %}

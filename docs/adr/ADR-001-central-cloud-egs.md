# ADR-001: MIZAN runs the 5 EGS units centrally (cloud-EGS pattern)

- **Status:** Accepted (spec v1.1 Design Freeze, Section 5.1) — frozen; change only with owner approval.
- **Date:** 2026-11-12

## Context

POS lanes at 120 stores race on shared EGS sequences; a store-side signer cannot guarantee a single writer per EGS.

## Decision

MIZAN runs the 5 EGS units centrally. It mints the ICV and PIH, signs, and submits.

## Consequences

`brz.zatca_invoices_raw` holds only *unsigned* invoice requests from POS. Signed XML lives only in `audit.zatca_chain_journal` (legal hold). One writer per EGS removes ICV races.

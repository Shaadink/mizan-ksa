# ADR-004: Every invoice carries invoice_flow = CLEARANCE (standard, B2B) or REPORTING (simplified, B2C)

- **Status:** Accepted (spec v1.1 Design Freeze, Section 5.1) — frozen; change only with owner approval.
- **Date:** 2026-11-12

## Context

B2B standard invoices must be cleared by ZATCA before they are valid; B2C simplified invoices are reported within 24 hours. v1.0 wrongly held B2C revenue on a ZATCA timeout.

## Decision

`invoice_flow` is an uppercase enum on every invoice. Success state is CLEARED (CLEARANCE) or REPORTED (REPORTING).

## Consequences

B2C posts to the GL at the point of sale; B2B posts once cleared. GL idempotency key = `invoice_uuid`, so `accounting_postings == 1`.

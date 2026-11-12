# ADR-005: Canonicalization uses lxml C14N 1.0 (inclusive, no comments)

- **Status:** Accepted (spec v1.1 Design Freeze, Section 5.1) — frozen; change only with owner approval.
- **Date:** 2026-11-12

## Context

The invoice hash must be byte-stable. ZATCA specifies C14N 1.1; lxml implements C14N 1.0 (and 2.0).

## Decision

Use lxml `method="c14n"`, `exclusive=False`, `with_comments=False`, after removing UBLExtensions, cac:Signature and the QR reference.

## Consequences

For UBL invoices without `xml:base` or `xml:id`, C14N 1.0 output equals C14N 1.1. To be validated against a ZATCA SDK sample hash; if no match is possible, a self-consistent hash ships and the gap is stated in HONESTY.md.

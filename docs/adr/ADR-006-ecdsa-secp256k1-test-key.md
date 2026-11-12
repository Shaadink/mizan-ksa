# ADR-006: Signing = ECDSA secp256k1 with a self-generated test key

- **Status:** Accepted (spec v1.1 Design Freeze, Section 5.1) — frozen; change only with owner approval.
- **Date:** 2026-11-12

## Context

Real signing needs a ZATCA-issued CSID certificate, which requires onboarding a real taxpayer.

## Decision

Sign with ECDSA over secp256k1 using a self-generated test key. QR tags 1-9 are produced (tags 8-9 as raw bytes).

## Consequences

Full XAdES signed-properties structure and SDK certification are out of scope, stated in HONESTY.md.

# ADR-002: merchant_id = acquirer merchant ID (MID)

- **Status:** Accepted (spec v1.1 Design Freeze, Section 5.1) — frozen; change only with owner approval.
- **Date:** 2026-11-12

## Context

"Merchant" is ambiguous: the retailer, the store, or the acquirer's merchant account. The bank settlement file is keyed by MID.

## Decision

`merchant_id` everywhere means the acquirer MID. A single retailer has many MIDs; the e-commerce MID carries 65% of volume.

## Consequences

The reconciliation grain (MID x business_date_ksa) matches the bank file, and the 65% mega-MID is the real skew key for Module 7.

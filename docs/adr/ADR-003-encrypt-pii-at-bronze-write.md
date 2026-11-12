# ADR-003: Encrypt PII at the Bronze write, not at Bronze->Silver

- **Status:** Accepted (spec v1.1 Design Freeze, Section 5.1) — frozen; change only with owner approval.
- **Date:** 2026-11-12

## Context

If Bronze holds cleartext PII, every Bronze snapshot and time-travel version is an erasure liability (v1.0 defect E).

## Decision

PII is HMAC-SHA256 tokenized (`subject_token_id`) and AES-256-GCM encrypted with a per-subject DEK at the moment it is written to Bronze.

## Consequences

No cleartext PII exists outside the legal-hold journal. The HMAC tokenizer and AES-GCM ship first; the policy engine and Restore Guard follow.

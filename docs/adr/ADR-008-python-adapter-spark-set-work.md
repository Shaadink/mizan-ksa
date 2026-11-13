# ADR-008: Python landing adapter + Spark set work, with zero Python UDFs

- **Status:** Accepted (Phase 3)
- **Date:** 2026-11-13

## Context

The spec requires CP1256 decoding in Python (not Spark's CSV encoding option), and PII encrypted at the Bronze
write. The first implementation used Python UDFs and `createDataFrame` from Python lists. On local Windows Spark
this spawned Python worker processes per task: a 100K-row load took over 10 minutes and then failed with
"Python worker failed to connect back".

## Decision

- A Python adapter per file reads the bytes, checks the sha256, decodes, repairs CP1256, tokenises (HMAC-SHA256),
  encrypts PII (AES-256-GCM under the subject DEK) and writes a **ciphertext-only** UTF-8 staging CSV.
- Spark reads the staged file natively and does all set work: contract checks and quarantine routing,
  `ctl.applied_event_ledger` dedup, Silver builds and Delta writes. No Python UDFs anywhere in `mizan.spark`.
- All small control-table writes go through `rows_to_df` (the same staging pattern).

## Consequences

The full Bronze + Silver + ZATCA run takes about 6 minutes locally, and the code path is identical on Fabric
(staging under the Lakehouse `Files/`). Cleartext PII exists only in the adapter's process memory, never on disk
or in a table. At very large scale the adapter would move into `mapPartitions`, which is the same code applied
per partition.

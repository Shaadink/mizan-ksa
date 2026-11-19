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

## Where this breaks, measured

The standing objection to this ADR is that single-threaded Python in front of a distributed engine cannot scale.
That objection is correct in shape and wrong in magnitude, so here is the measurement rather than an argument
(`scripts/bench_adapter.py`, same machine as the rest of the benchmarks):

| Operation | Throughput |
|---|---|
| `hmac_hex` (subject tokenisation) | ~400,000 fields/sec |
| `encrypt_field` (AES-256-GCM, random 96-bit nonce, AAD `token\|column`) | ~296,000 fields/sec |
| **Combined, per field** | **~170,000 fields/sec** |

Contracts carry 3 to 7 PII columns, so one core sustains roughly **24,000 to 57,000 rows/sec**, or on the order of
**90M to 200M rows/hour**. The adapter is not the bottleneck at this project's 99K rows, and would not be at a
hundred times that. What actually binds first is driver **memory** -- the adapter accumulates staged rows in a
list -- not CPU.

**The migration path, in order:** (1) chunk the adapter so memory is bounded rather than proportional to the file;
(2) move it into `mapPartitions`, which is the same function applied per partition and needs the DEKs broadcast
to executors; (3) past that, a tokenisation service behind a private endpoint with keys in Key Vault, so Spark
still receives only ciphertext.

Step 2 is the one that changes the security property this ADR exists to protect, because it puts per-subject keys
in executor memory. That is the trade the ADR is really making: **today, cleartext PII and the DEKs never leave
one process.** The cost of that guarantee is one core's throughput, and the measurement above is what it costs.

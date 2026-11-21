# MIZAN-KSA

**Saudi regulated commerce and payments data integrity platform — Microsoft Fabric**

*Every assessed halala reconciled. Everything else, honestly flagged.*

Live, no sign-in: **https://delightful-field-01a948c0f.4.azurestaticapps.net**

Source: **https://github.com/Shaadink/mizan-ksa**

---

## Four numbers, none of them typed by hand

| `SAR 0.00` | `25,001` | `94 / 94` | `20,000,000` |
|---|---|---|---|
| bank **and** GL variance across 2,121 assessed merchant-days of 2,233 | e-invoices in an unbroken ZATCA Phase-2 hash chain, **0 breaks** | Gold columns traced to source, column by column | rows joined at **62:1 skew** in a **local Spark benchmark** — three plans, one identical SAR checksum |

**The fifth number is the one that matters most: 112 merchant-days are *not* assessed.** Their bank file has not
arrived (SAR 1,125,209.07 in transit). They are counted and labelled, never averaged away. A platform that
reconciles 100% of everything is lying about something; this one reconciles what it can prove and flags the rest.

---

## What it does

One commercial transaction, followed end to end: **order capture → ZATCA Phase-2 e-invoice → mada/SADAD T+1 bank
settlement → ACDOCA-shaped ERP general ledger.** The scales settle only when bank and ledger agree to 0.01 SAR.

| Problem | How MIZAN handles it |
|---|---|
| **ZATCA Phase-2 e-invoicing** | Real UBL 2.1, C14N canonicalisation, XAdES signature, TLV QR, PIH hash chain from the correct genesis hash. Submitted XML validated against **ZATCA's own SDK (3.0.8)** — it found 9 defects, all fixed; XSD and EN 16931 now PASS. |
| **Transport failure mid-submit** | `SUBMITTING` is persisted *before* any HTTP call. A worker killed mid-flight resumes as `UNKNOWN_OUTCOME` and retries the **byte-identical signed bytes** under the same UUID. Only 200/202/400/401/403 are treated as definitive. |
| **PDPL right to erasure** | PII encrypted at the Bronze write (HMAC token + per-subject AES-256-GCM key). Erasure destroys the key, shreds across all layers, VACUUMs the vault, and leaves 25,001 signed tax documents intact. Restore Guard re-shreds anything a time-travel restore brings back — tested against **data *and* vault** history. |
| **Reconciliation that silently drops rows** | A **key spine**: the union of keys from payments, settlement and GL. No LEFT JOIN that can lose a row. Unclassified events are counted, not discarded. |
| **Mega-merchant data skew** | One merchant on 65% of rows. Three plans benchmarked on 20M rows; salting cuts the skew ratio 61.8 → 9.5 with **zero spill** — and all three produce the same `50020661413.78` SAR checksum. |
| **Merchants with too many disputes** | Card schemes fine merchants whose chargeback ratio crosses a line, and an acquirer has to watch for it. The ratio **alone** flags 71 of 121 merchants here — useless. The real programmes require a ratio **and** a minimum dispute count, and so does this: **1** merchant, 200 disputes on 10,530 captures, SAR 319,280 clawed back. Both numbers are published so the floor's effect is shown, not claimed. |
| **Arabic master data** | Five spellings of one entity resolved to a single golden record; steward merge/unmerge is reversible SCD2. |

---

## How every number is proven

This is the part that distinguishes it from an architecture document.

- **`docs/PROOF_MANIFEST.md`** — 13 claims, each with the proof file behind it and that file's SHA-256.
- **`HONESTY.md`** — what the project does *not* do, where evidence is stale, and two defects found in ZATCA's own
  validator (a float VAT comparison, and a QR rule made unsatisfiable by two other rules).
- **444 Python tests and 184 app tests** (183 pass, 1 skipped), and dbt **99/99 on both the local target
  and WH_MIZAN**, run in CI on every push, including the full PySpark and dbt suites.
- **Disaster recovery drill** — source and lake rebuilt from scratch in 9.8 min, Gold in 18.2 s (RTO 604.7 s).
  All 10 tables, 35,789 rows, fingerprinted by SHA-256 and **identical to the live warehouse**.
- **Determinism** — the generator is fixed-seed and must produce byte-identical output on a rerun.
- **ADR-001…016** — the decisions, with the reasoning and what was rejected.
- Planted defects trip a **circuit breaker**: when variance is not 0.00 the dbt build fails and nothing publishes.
  The system does not email you about bad numbers; it refuses to release them.

---

## Architecture

| Layer | Objects |
|---|---|
| **Lakehouse `LH_MIZAN`** | `brz` `ctl` `slv` `quarantine` `security` `audit` `meta` `ai` |
| **Warehouse `WH_MIZAN`** | `gld` — Gold models materialised as tables, `DECIMAL(18,2)` money, no `NVARCHAR`/`DATETIME`/`MONEY` |
| **Real-time** | Eventstream `ES_MIZAN` → Eventhouse `EH_MIZAN`; velocity, mule-ring and reporting-SLA rules in KQL |
| **Governance** | 350 columns classified on four NDMO tiers, fail-closed on anything unknown; column-level lineage via OpenLineage |
| **Consumption** | Direct Lake semantic model, 3-page Power BI suite, a Fabric App front end, and a governed AI assistant that refuses personal data |

**Stack (frozen by ADR):** Microsoft Fabric (OneLake Delta, PySpark, Warehouse, Eventhouse/Eventstream, Direct Lake)
as the data plane; Apache Airflow, dbt-fabric, OpenLineage + Marquez, pytest, Docker and GitHub Actions as the
control plane.

---

## Scope

Synthetic data, fixed seed, Asia/Riyadh. A **standards-informed engineering reference architecture**, not a
regulator-certified tax product. Money is Python `Decimal` and SQL `DECIMAL(18,2)` throughout — never float.

---

## CV project block (copy-paste)

```
MIZAN-KSA — Saudi Commerce & Payments Data Integrity Platform (Microsoft Fabric)

• Built an end-to-end payments reconciliation platform on Microsoft Fabric (OneLake Delta,
  PySpark, Warehouse, Eventhouse, Direct Lake) that reconciles bank settlement and ERP general
  ledger to SAR 0.00 across 2,121 merchant-days, and labels the 112 it cannot yet prove rather
  than averaging them away.

• Implemented ZATCA Phase-2 e-invoicing for real: UBL 2.1, C14N canonicalisation, XAdES
  signing, TLV QR and a 25,001-document PIH hash chain with zero breaks. Validated against
  ZATCA's own SDK, which surfaced 9 defects — all fixed; XSD and EN 16931 pass.

• Engineered crash-safe submission (state persisted before the HTTP call, byte-identical retry
  on transport failure) and PDPL Article-18 erasure by per-subject key destruction, shredding
  PII across all layers while leaving signed tax evidence intact and surviving a time-travel
  restore.

• Eliminated Spark shuffle skew on a mega-merchant holding 65% of rows — 62:1 down to 9.5:1
  with zero spill across 20M rows — and proved correctness by an identical SAR checksum under
  three different execution plans.
```

---

*Every figure above is generated from Gold or a named proof run, never typed. Sources: `docs/PROOF_MANIFEST.md`,
`HONESTY.md`, `docs/artifacts/`.*

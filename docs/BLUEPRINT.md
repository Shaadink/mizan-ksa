# MIZAN-KSA — Complete Project Blueprint

**Written for:** an external reviewer (human or AI) who has never seen this project and is being asked to
critique it — what to keep, what to remove, what to rewrite, what to avoid, and what is missing.

**What this document is:** a full account of what was built, in what order, why, and with what evidence. It
is written twice over: in plain English for the general reader, and in technical detail with real code for
an engineer. It includes the things that do **not** work, the shortcuts taken, and the claims that rest on
reasoning rather than measurement.

**What this document is not:** a sales pitch. Where a number is unverified, it says so. Where a decision was
arguable, it gives the argument against.

**Status at the time of writing:** 2026-11-19. Built, tested, deployed, running. Two tasks outstanding, both
requiring a human (a demo video and eight screenshots).

---

# PART 0 — FACT SHEET

| | |
|---|---|
| **Name** | MIZAN-KSA (*mizan* = Arabic for "the balance / the scales") |
| **One line** | Saudi regulated commerce and payments data integrity platform on Microsoft Fabric |
| **Built by** | One person, with AI-assisted development throughout. Every architectural decision is in `docs/adr/`; every claim is bound to a named test or proof run |
| **Purpose** | A data engineering reference architecture for Saudi regulated commerce and payments |
| **Data** | 100% synthetic, deterministic, fixed seed (20261112), ~99,418 generated source rows |
| **Period modelled** | 2026-02-12 to 2026-03-03, Asia/Riyadh (20 days, 14 of them Ramadan) |
| **Python source** | 5,773 lines across 50 modules |
| **Scripts** | 3,595 lines across 15 scripts |
| **Tests** | 3,886 lines across 29 test files |
| **Python tests** | **302 passing**, 0 failing |
| **Fabric App tests** | 184 (169 pass, 15 skip while the Fabric dataset is behind) |
| **dbt** | **91/91 PASS** locally; the new dispute model also 10/10 on Fabric |
| **Gold** | 9 tables, 35,668 rows, **91 of 91 columns traced to source** |
| **ADRs** | 14 |
| **Invariants** | 14 (I-01 … I-14), each bound to named tests |
| **Honesty rows** | 17 documented limitations |
| **Live, no login** | https://delightful-field-01a948c0f.4.azurestaticapps.net |
| **Live, Fabric tenant** | https://fond-gulf-57cbbd6a65-uaenorth.webapp.fabricapps.net |
| **Fabric workspace** | `mizan-ksa-dev`, trial capacity FTL64, UAE North (a tenant the owner does not control; the whole workspace rebuilds from `scripts/fabric_*.py` on any capacity) |

---

# PART 1 — PLAIN ENGLISH: WHAT THIS IS

## The one-sentence version

When you buy something in a Saudi shop, five different systems record that one purchase — and this project
proves they all agree, to the last **halala** (one hundredth of a riyal).

## Why that is hard

Buy a coffee for SAR 23. In the next 48 hours:

1. The **till** records a sale
2. A **tax e-invoice** is created, cryptographically sealed and sent to the Saudi tax authority
3. The **bank** takes its fee and pays the shop the rest, the next day
4. The shop's **accounting system** books the revenue
5. The **fraud system** checks the card wasn't stolen

Every one of those is a separate system with its own copy of the truth. They drift. Fees get recalculated
slightly differently. A bank file arrives late. A refund lands in one system but not another. By the end of
the month, the shop's books and the bank's statement disagree by a few riyals and nobody can explain why.

**MIZAN follows one transaction through all of it and proves the numbers close exactly.**

## What it actually produces

- `SAR 0.00` — the difference between what the bank paid and what the ledger says, across 2,121 merchant-days
- `25,001` — tax e-invoice documents in unbroken cryptographic chains, zero breaks

**The denominator, since "2,121" invites the question.** 121 merchants over 20 days is 2,420 *possible*
merchant-days. Only **2,233** of them exist in Gold, because a merchant-day is created by activity and the long
tail does not trade every day — the remaining 187 are days on which that merchant sold nothing, and a row
asserting SAR 0.00 against no activity would be noise, not evidence. Of the 2,233 that do exist, **2,121 are
assessed and balance to SAR 0.00**, and **112 are in transit** and deliberately not assessed. So:
`2,420 possible = 2,233 with activity (2,121 assessed + 112 in transit) + 187 with no trading`.

**And "unbroken chain" is five chains, not one.** ZATCA chains per EGS device, and there are five (EGS-01…05).
Each verifies from its own genesis PIH with zero ICV gaps; the 25,001 figure is the total across all five.
- `112` — merchant-days it **refuses** to call balanced, because the bank file hasn't arrived yet
- `20,000,000` — rows joined in a stress test, with the money proven unchanged under three different strategies

That third number is the most important one and is explained below.

## The idea that holds the whole thing together

**A system that reconciles 100% of everything is lying about something.**

On the last day of the data, 112 shops have no bank file yet — the money is in transit, as it should be at
T+1. A naive system either ignores those rows (and reports a false 100%) or counts them as broken (and
reports a false alarm).

MIZAN does neither. It labels them **"not assessed"**, counts them (SAR 1,125,209.07 in transit), and
excludes them from the balanced claim. The headline reads *"Every **assessed** halala, reconciled. Everything
else, honestly flagged."*

Almost every design decision in the project follows from that sentence.

---

# PART 2 — THE PROBLEM DOMAIN

Saudi Arabia has four regulators whose rules land on the same transaction:

| Regulator | What it demands | What MIZAN does |
|---|---|---|
| **ZATCA** (tax) | Phase-2 e-invoicing: every invoice signed, hashed, chained to the previous one, QR-coded, and cleared or reported to the government portal | Full implementation: UBL 2.1 XML, C14N canonicalisation, XAdES-style signature, TLV QR, hash chain from the correct genesis value, crash-safe submission |
| **SDAIA / PDPL** | Personal data protection; a citizen can demand erasure, but tax records must be kept 6–10 years | Per-subject encryption keys; destroy the key and the personal data is gone everywhere, while the signed tax documents survive intact |
| **NDMO** | Four-tier data classification (Top Secret / Secret / Confidential / Public) inherited by everything downstream, including AI | 350 columns classified by rule, fail-closed on anything unknown; the AI assistant cannot read above its clearance |
| **SAMA** (central bank) | Real-time payment fraud monitoring | Velocity, shared-identity ring and reporting-SLA rules in KQL — **named as velocity rules, with no SAMA clause cited**, because the clause was never verified |

That last row is deliberate and worth noting: the project repeatedly declines to claim regulatory backing it
has not checked.

---

# PART 3 — ARCHITECTURE

## The shape

```
SOURCE FILES (synthetic, 7 contracts)
  orders · ZATCA requests · payments · bank settlement · ERP GL · CRM · addresses
                    │
                    ▼
BRONZE  (LH_MIZAN.brz)      raw, immutable, PII encrypted AT THE WRITE
                    │        sha256 checked against a control file
                    ▼
SILVER  (LH_MIZAN.slv)      typed, deduplicated, conformed
                    │        payment_lifecycle · settlement_lines · erp_gl_journal_lines
                    │        zatca_invoice_documents · golden_party_scd2 · identifier_registry
                    ▼
GOLD    (WH_MIZAN.gld)      9 tables, Kimball-ish, materialised as tables
                             fact_merchant_settlement_recon ← the reconciliation
                             fact_zatca_clearance_ledger
                             fact_payment_method_daily
                             fact_merchant_dispute_monitor  ← newest
                             dim_date_saudi (Gregorian + Hijri)
                             dim_party_golden · mart_ndmo_scorecard + 2 seeds
                    │
       ┌────────────┼────────────┬──────────────┐
       ▼            ▼            ▼              ▼
  Power BI     Fabric App   Public site    Governed AI
  (Direct Lake) (Rayfin)    (no login)     (Azure OpenAI)
```

Alongside the batch path:

```
Eventstream ES_MIZAN → Eventhouse EH_MIZAN (KQL)   — fraud + SLA rules on a replayed stream
Open mirroring MR_MIZAN → erp.merchant_master       — CDC files, Fabric maintains the table
Airflow (Docker) → Fabric REST jobs → dbt → lineage — daily orchestration at 03:00
OpenLineage → Marquez                               — column-level lineage graph
```

## The frozen stack

Deliberately small, and fixed by ADR:

- **Data plane:** Microsoft Fabric — OneLake Delta (`LH_MIZAN`), Warehouse (`WH_MIZAN`), Eventhouse /
  Eventstream, Direct Lake semantic model
- **Control plane:** Apache Airflow, dbt (dbt-fabric + dbt-duckdb), OpenLineage + Marquez, pytest, Docker,
  GitHub Actions
- **Explicitly excluded:** Great Expectations, Kubernetes, any second database, extra domains

A local DuckDB target exists so the same dbt models build on a laptop and in CI without a cloud tenant. This
turns out to matter a lot — see Part 9.

## The eight lakehouse schemas

| Schema | Holds |
|---|---|
| `brz` | Raw landed source, PII already encrypted |
| `ctl` | Control: watermarks, applied-event ledger, EGS chain state, invoice outbox |
| `slv` | Conformed Silver |
| `quarantine` | Rows that failed a contract, with the rule that rejected them |
| `security` | PII vault metadata, subject token map (KEK-encrypted) |
| `audit` | ZATCA chain journal (signed XML as BINARY), PDPL evidence, run manifests, benchmarks |
| `meta` | Column classification (NDMO tiers) |
| `ai` | Policy chunks and case notes for the governed assistant, with tier inheritance |

---

# PART 4 — BUILD HISTORY, PHASE BY PHASE

This is the micro-step record. Each phase ends with tests green and one commit.

**A correction, since this document asks to be audited.** An earlier draft put a cumulative test count beside each
phase heading. Those numbers were carried forward by hand rather than counted, and they showed it: two pairs of
consecutive phases had identical totals, and one phase appeared to *reduce* the suite. Reviewers caught it, and
they were right to. `PROGRESS.md` reliably records only the counts taken at the time -- 133, 140, 177, 220, then
302 today -- so the per-phase figures are gone rather than guessed. The current suite is **302 Python tests**,
and `pytest -q` is the only authority on that number.

## Phase 0 — Scaffold

`pyproject.toml`, `.gitignore`, `.gitattributes` (LF endings), `.env.example`, `CLAUDE.md` (standing rules),
`README.md`, `HONESTY.md`, `invariants.md` (I-01…I-14), ADR-001…006, package skeleton, first 7 tests.

**Decision set here that shaped everything:** money is `Decimal` in Python and `DECIMAL(18,2)` in SQL, never
float, anywhere, ever. A dbt generic test (`no_float_columns`) enforces it on every financial model.

## Phase 1 — Deterministic generator

`python -m mizan.generator --out data/generated` — about 3 seconds, fixed seed 20261112, byte-identical on
rerun (a test asserts this).

Produces 99,418 rows across seven files:

| File | Rows | Notes |
|---|---|---|
| `orders/commerce_events.csv` | 25,000 | 23,500 orders + 1,500 returns |
| `zatca/invoice_requests.jsonl` | 25,000 | 23,500 invoices + 1,500 credit notes, EGS-01…05 |
| `payments/payment_events.csv` | 18,000 | 16,200 captures, 1,500 refunds, 300 chargebacks |
| `settlement/NAJDACQ_*.csv` | 17,000 | 19 daily T+1 bank files + one byte-identical resend |
| `erp/erp_gl_acdoca.csv` | 9,418 | store × day × account, ACDOCA-shaped |
| `crm/` | 5,000 | 1,800 POS in CP1256 + 2,200 e-commerce in UTF-8 = **4,000 party records**, plus 1,000 address observations |
| `demo/` | 2 | an orphan bank line and a 0.01 float-drift GL line — **overlay only**, not in the main build |

**Twelve planted defects (D01–D12)** recorded in `defect_manifest.json`, each one the seed of a later test:
transport timeout, ICV gap, crash mid-submit, HTTP 400 rejection, orphan settlement, 0.01 float drift,
duplicate batch, CP1256 mojibake, unrecoverable `?????`, two brothers with different IDs, five spellings of
one customer, a mega-merchant holding 65% of rows.

**Design facts fixed here:** amounts are always positive and the sign lives in `event_type` / `dr_cr` /
`DRCRK`; source timestamps are UTC and business dates are derived in Asia/Riyadh (over 100 events cross
midnight and would land on the wrong day otherwise).

## Phase 2 — ZATCA engine

The hardest part of the project. `python -m mizan.clearance` — about 45 seconds.

Modules in `src/mizan/clearance/`:

- `tlv_qr_and_state_machine.py` — genesis PIH, invoice hash, TLV QR encoder/decoder, the submission state
  machine, GL posting rule, and a hardened XML parser that refuses DOCTYPE
- `ubl.py` — two-step UBL 2.1 builder: build unsigned → hash → sign → attach `UBLExtensions`, `cac:Signature`
  and the QR reference
- `signing.py` — ECDSA secp256k1 deterministic test key per EGS device, self-signed certificate for QR tags
  8 and 9
- `engine.py` — the chain store (`ctl.egs_chain_state`, `ctl.invoice_outbox`, `audit.zatca_chain_journal`),
  a per-EGS lock sequencer, the worker, and an idempotent GL sink keyed on the sale UUID
- `mock_fatoora.py` — a mock government portal that verifies the QR hash, the signature and VAT sums, and
  runs scripted faults
- `chain_verifier.py` — walks a chain from genesis and reports violations

**Result of a full run:** 25,001 documents (one correction), 23,913 REPORTED, 1,087 CLEARED, 1
CONFIRMED_REJECTION, one simulated worker restart, **zero chain violations**, 25,000 GL postings with a
maximum of one posting per sale. The tamper demo produces exactly two violations (ICV_GAP and PIH_MISMATCH)
at the planted position.

**Eight chaos tests**, each a scenario rather than a unit:

1. Timeout → retry sends byte-identical bytes
2. Crash while in SUBMITTING → recovers to UNKNOWN_OUTCOME → retries identically
3. A rejection stays in the chain; the fix is a new document with a new ICV
4. Verify from genesis, with and without tampering
5. Eight non-definitive HTTP statuses (408/409/429/500/502/503/504/302) all → UNKNOWN_OUTCOME
6. 401/403 → AUTH_HOLD → credential renewal → identical bytes
7. B2B held on timeout, B2C posted anyway
8. Eight concurrent lanes on one device → ICV 1…240 with no gaps

**And the boundary that test cannot reach**, added after external review raised it: those eight lanes are threads
sharing one in-memory store, so a `threading.Lock` suffices and the happy path is all they can prove. Two worker
*processes* would both read `last_icv = n`, both mint `n+1`, and fork the chain — two documents claiming one ICV,
unrecoverable because a submitted ICV cannot be withdrawn. `commit_signed` does guard this with a compare-and-set
rather than a read-then-write, and a ninth test now proves the refusal actually fires (verified by removing the
guard and watching the test fail). What is not built is the durable half: a real multi-worker deployment needs
that compare-and-set in a transactional store, not a Python lock over a dict. See `HONESTY.md` row 18.

## Phase 3 — Bronze + Silver in PySpark

About 6 minutes locally.

The notable design is a **Python adapter boundary**: checksum verification, CP1256 decoding and repair, HMAC
tokenisation and AES-256-GCM encryption all happen in driver-side Python, and only ciphertext is staged into
Spark. Spark never sees cleartext PII and no Python worker processes are required (ADR-008).

The standing objection is that single-threaded Python in front of a distributed engine cannot scale, so ADR-008
now carries a measurement rather than an argument (`scripts/bench_adapter.py`): **~170,000 fields/sec combined**,
which at 3 to 7 PII columns per row is 24,000–57,000 rows/sec, or 90M–200M rows/hour on one core. The adapter is
not the bottleneck at this volume and would not be at a hundred times it; what binds first is driver **memory**,
because staged rows accumulate in a list. The migration path is chunking, then `mapPartitions`, then a
tokenisation service — and the ADR names which of those steps gives up the property it exists to protect
(`mapPartitions` puts per-subject keys in executor memory).

A related question from review, worth recording because the answer is a near miss: if the generator is
byte-deterministic, are the AES-GCM nonces deterministic too? That would be catastrophic — nonce reuse under one
key destroys GCM. They are not: `secrets.token_bytes(12)` per field, with AAD binding `token|column`. Determinism
is a property of the *generator*, never of the ciphertext.

Produces: contract validation into `quarantine.schema_rejections`, idempotent replay via
`ctl.applied_event_ledger`, watermarks, the PII vault with **zero deleted-file retention**, and the three
Silver fact tables with Delta CHECK constraints.

**Result:** every file checksum matches; the resend file is detected as ALL_DUPLICATE (995 rows); 15
unrecoverable `?????` rows quarantined; 41 mojibake rows repaired; the bank leg closes to 0.00 per
merchant-day inside Spark.

## Phase 4 — Gold in dbt

One dbt project, two targets: `duckdb` (local and CI, reading Silver Delta) and `fabric` (WH_MIZAN through a
service principal). **One SQL file serves both adapters**; only the date spine dispatches per dialect.

The reconciliation model is the heart of the project, and its key idea is the **key spine**:

```sql
spine AS (                       -- every key from ANY leg: nothing is dropped
    SELECT merchant_id, business_date_ksa FROM captures
    UNION SELECT merchant_id, business_date_ksa FROM settlements
    UNION SELECT merchant_id, business_date_ksa FROM gl
),
j AS (
    SELECT k.merchant_id, k.business_date_ksa,
           COALESCE(c.gross_captures_sar, 0) AS gross_captures_sar,
           ...
    FROM spine k
    LEFT JOIN captures    c ON ...
    LEFT JOIN settlements s ON ...
    LEFT JOIN gl          g ON ...
)
```

A LEFT JOIN from payments would silently lose a bank line that has no matching payment. The UNION spine
cannot. This is the single most important line of SQL in the project.

**Which date the legs join on**, because four independent reviewers assumed this was a bug and it is not. The
settlement leg keys on `settlement_for_date_ksa` — the *originating capture date that a bank line pays for*, not
the date the bank file arrived. Keying on file arrival would shift every bank line one day from the captures it
settles and show a false variance on every merchant-day in both directions: a textbook off-by-one that looks like
a reconciliation and balances to nothing. The file's own arrival date is carried on `slv.settlement_lines` and is
**not** a join key.

**Two things it does not do, named rather than left for a reviewer to find.** A real acquirer's bank file carries
an independent *value date* that can differ from T+1 by scheme, merchant category and the Friday/Saturday KSA
weekend; here the synthetic file states the capture day it settles, so one mapping suffices, and against a real
file the spine would need a date-mapping leg and a lag distribution instead of a single in-transit flag. Harder
still: **cross-period chargeback matching**. A chargeback 45 days after its capture lands on its own business
date, reducing that day's net while the capture it claws back sat in a different month. Disputes here are counted
on their own event date. Neither is implemented; both are stated so they are not mistaken for solved.

Plus a **circuit breaker**: a singular dbt test, `assert_zero_unexplained_halala_variance`, that fails the
build when variance is not 0.00. The demo overlay fails exactly that test, on exactly the two planted
merchant-days, and nothing downstream publishes.

## Phase 5 — Arabic Master Data Management

Pure-Python matching engine with a **deterministic ladder**, not a fuzzy score:

1. **Anchor** on a typed identifier (National ID / Iqama with Modulo-10 checksum, VAT number, 700 number)
2. Otherwise: an ID-less record that is name-compatible **and** shares a phone, **and** has exactly one
   candidate
3. Otherwise: the steward queue. Never an automatic merge.

Every merge is an append-only event in `slv.entity_merge_ledger`, so membership is a fold and every merge is
reversible. Survivorship prefers the clean source, plain spelling over tashkeel/ligature forms, and the full
English name.

**Result:** 3,985 records → 2,552 golden profiles. (3,985 = the 4,000 generated party records minus the 15 whose
Arabic names arrived as unrecoverable `?????` and were quarantined in Phase 3 — they are not silently dropped,
they are counted in `quarantine.schema_rejections`.) The five spellings of one customer converge to one golden
record anchored on the Iqama. The two **brothers** with different National IDs stay separate — this is the
hard-negative test, and a fuzzy matcher would have merged them. The ID-less third person becomes one open
conflict for a steward. 54 cross-script ID-less records deliberately stay separate: the project does not
transliterate.

## Phase 6 — PDPL erasure and NDMO classification

**Crypto-shredding.** Every data subject gets their own AES-256-GCM key. Erasure destroys the key, which
makes the ciphertext permanently unreadable in Bronze, Silver, Gold and the AI index at once — without
deleting a single tax record.

Mechanics: resolve the subject via an ID HMAC plus golden-record membership to every token; a reference
decision that cannot be resolved **fails closed**; the vault is set to NULL and SHREDDED; `VACUUM RETAIN 0
HOURS` on both the vault and the token map; tombstones written; the MDM re-resolves; evidence recorded with
tax totals before and after.

**Result:** the DSR shreds 5 linked tokens, 18 journal rows are retained under legal hold, and the tax totals
are **identical** before and after. Vault time travel cannot return the key. Restoring a pre-erasure backup
**and** a Silver snapshot is re-shredded by the Restore Guard before serving.

NDMO: 350 columns classified by ordered rules, a table inherits the maximum tier of its columns,
over-classification is reported, and `legal_hold_class` is uppercase and fail-closed on anything unknown.

## Phase 7 — Spark skew

A deliberately skewed join: one mega-merchant holds 65% of 20 million rows. Three strategies benchmarked in
Docker with task statistics pulled from the Spark REST API.

```python
keyed = keyed.withColumn("_salt", F.pmod(F.xxhash64(F.col(salt_col)), F.lit(buckets)).cast("int"))
dim_rep = dim.withColumn("_salt", F.explode(F.sequence(F.lit(0), F.lit(buckets - 1))))
joined = keyed.join(dim_rep, [key, "_salt"], "left").drop("_salt")
```

| Strategy | Duration | Skew ratio | Spill |
|---|---|---|---|
| AQE off | 23.12 s | **61.8×** | 0 |
| AQE skew-join | 15.52 s | 6.0× | 0 |
| 16-bucket salt | 17.62 s | 9.5× | 0 |

**All three produce the identical SAR checksum `50020661413.78`.** That is the point: the optimisation did
not move a halala. Compaction reduced 400 files to 1.

**AQE beat the hand-written salt**, on this workload, on both duration and skew ratio. That is in the table above
and it is worth saying out loud rather than letting a reviewer discover it: writing a salt to beat a config flag
would be the wrong reason to write one. The right reasons are that salting is what remains when AQE *cannot*
split a partition — a stream-to-static join, or a skewed pre-shuffle aggregation — and that implementing it is
how you learn why the built-in wins. Both are kept for that comparison.

**One caveat on the skew ratios themselves, which a Spark-literate reader will spot.** They are `max/median` task
duration, and the runs were measured on different stages with very different task counts: 64 tasks with AQE off,
5 with AQE skew-join. A median over five samples is nearly meaningless, so `61.8× → 6.0×` compares two
distributions that are not directly comparable. The durations, the row counts and the checksum are sound; the
ratio is an indicator, not a measurement, and the benchmark harness should be rerun on comparable stages before
the ratio is quoted as a result.

`WALK_IN` and NULL merchant keys are isolated before salting, because a null key is not skew — it is absence,
and bucketing it would invent structure.

## Phase 8 — Airflow, OpenLineage, Marquez

`airflow/dags/mizan_daily.py`, scheduled `0 3 * * *`:

```
bronze_land → silver_build → mdm_resolve → zatca_chain
    → fabric_restore_guard → freshness_gate → dbt_build_gold
    → fabric_ai_index + fabric_ndmo_catalog → residency_gate
    → lineage_and_run_manifest
```

Two of those are **gates that stop the pipeline**: a freshness gate and a data-residency gate. The DAG ends
by emitting OpenLineage events to Marquez, including column-level lineage derived from the dbt manifest plus
an explicit overrides file, with a run facet carrying the real git SHA.

**100% of Gold columns must have lineage or the build raises** — this is invariant I-13, and it has caught
every new Gold model since, including twice in the last two days.

## Phase 9 — Governed AI

A deterministic, retrieval-based assistant with no language model: policy chunks inherit NDMO tiers and ACLs,
the entitlement filter runs **before** ranking (so a user cannot even influence what they cannot see),
tombstoned subjects are suppressed, and money questions can only run allow-listed read-only Gold SQL
templates guarded by a validator.

**Proof:** a junior is refused the MDR negotiation policy; the Data Protection Officer never ranks the SECRET
section; a care agent sees a case note, the subject is erased, and the note is no longer served and is gone
from the rebuilt index.

## Phase 9b — Streaming

Deterministic replay of CHECKOUT / PAYMENT / INVOICE events carrying **only HMAC tokens, never PII**, into
Event Hubs, with reference rules implemented both in Python (for tests) and KQL (for Eventhouse):

- **Velocity:** more than 5 checkouts per customer token in 10 minutes
- **Mule ring:** one mobile token across more than 3 distinct customer tokens in 24 hours
- **Reporting SLA:** a simplified invoice not reported within 24 hours of issue

## Phase 10 — Fabric deployment

Everything created by script, all idempotent: `fabric_provision.py` (capacity, workspace, lakehouse schemas,
warehouse, eventhouse, eventstream), `fabric_deploy.py` (OneLake upload, notebook, job runs),
`fabric_streaming.py`, `fabric_powerbi.py` (TMDL Direct Lake model + PBIR report as code).

**Result:** all six notebook steps Completed with the same numbers as local; `dbt build --target fabric`
65/65 PASS on WH_MIZAN; 91,513 events accepted by the Eventstream.

**A real bug found here, worth repeating:** the Eventstream delivered zero rows. The destination runtime logs
showed the Kusto writer cannot write a KQL `decimal` column. The fix was to land `amount_sar` as exact text
and convert with `todecimal()` in a typed function — **float was not used as the escape hatch**, which would
have been the easy and wrong answer.

## Phase 11 — Proof artifacts

HTML proof boards built from real runs on scratch copies and screenshotted with Playwright: the ZATCA chain
tape, the halala reconciliation board (with the breaker failing), the PDPL shred/restore panels, the Arabic
MDM board, plus live UI captures of the Spark UI, Airflow and Marquez.

## Phase 12 — The Command Center

An owner-approved presentation layer outside the original tool list (ADR-011): a Three.js + GSAP + D3 single
page where every figure is exported from Gold by a build script, money is handled as integer halalas in
JavaScript, and IDs are masked. Fourteen scenes, a story mode, a command palette, role switching, Arabic
RTL, and reduced-motion support.

## Phase 13 — The Fabric App (five stages)

The same page shipped as a real Fabric App (Rayfin SDK) where the figures come from **live DAX** against the
Direct Lake semantic model rather than a snapshot — with the snapshot clearly labelled when it falls back.

Stage 1 was a truth audit that found and fixed nine display or data defects — including a ZATCA ledger that
silently dropped the one rejected document, and DAX filters overriding the visual's own category.

## Recent work (last four days)

- **Ask MIZAN** — a governed chat assistant, first deterministic, then a real Azure OpenAI agent behind an
  Azure Function with managed identity. Every number in an answer must appear in a tool result. ADR-012,
  ADR-013.
- **Wave 1** — hero rewritten around three proof numbers, a recruiter tour, a chaos bar, a crash slider
  showing identical bytes either side of a crash, and 16 recorded agent runs so the assistant still works
  after the Azure credit expires.
- **Wave 2** — a public no-login site, and validation against **ZATCA's own SDK**, which found **nine real
  defects**, all fixed. XSD and EN 16931 now pass.
- **Disaster recovery drill** — source and lake rebuilt from scratch (9.8 min), Gold rebuilt (18.2 s), RTO
  604.7 s, all 9 tables and 35,668 rows fingerprinted by SHA-256 and **identical to the live warehouse**.
- **Follow one riyal** — one real capture traced through four systems, chosen by a stated rule rather than
  hand-picked.
- **Open mirroring** (ADR-014) — a real OneLake landing zone feeding `erp.merchant_master`, proven with an
  initial load and a CDC batch, deliberately **not** wired into Gold.
- **Dispute monitoring** — the newest model, described in full below because it is the clearest example of
  how this project tries to think.

---

# PART 5 — CODE TOUR

## Money (`src/mizan/common/money.py`)

```python
HALALA = Decimal("0.01")

def q2(value: Decimal) -> Decimal:
    """Round to the halala, half-up. Refuses floats so binary drift can never enter."""
    if not isinstance(value, Decimal):
        raise TypeError(f"money must be Decimal, got {type(value).__name__}")
    return value.quantize(HALALA, rounding=ROUND_HALF_UP)
```

It raises on a float rather than converting. Combined with the `no_float_columns` dbt test, money cannot
become a float by accident anywhere in the stack.

## The genesis hash (`src/mizan/clearance/tlv_qr_and_state_machine.py`)

```python
GENESIS_PIH = base64.b64encode(hashlib.sha256(b"0").hexdigest().encode("ascii")).decode("ascii")

_EXCLUDED = ("//ext:UBLExtensions", "//cac:Signature",
             "//cac:AdditionalDocumentReference[cbc:ID='QR']")
```

This is a detail almost everyone gets wrong. The genesis value is base64 of the **hex string** of
`sha256("0")`, not base64 of the raw digest. And the invoice hash is computed over canonicalised XML with
three elements removed — otherwise the hash would cover the signature that is derived from it.

## The GL posting rule

```python
def gl_action(flow: str, state: str) -> str:
    """GL key = invoice_uuid (idempotent). B2C revenue is posted at the point of sale,
    never held on a ZATCA timeout. B2B posts only once ZATCA has cleared it."""
    if flow == "REPORTING":
        return "POSTED_AT_SALE"
    return "POST_ONCE" if state in ("CLEARED", "ACCEPTED_WITH_WARNINGS") else "HOLD"
```

Simplified (B2C) invoices are *reported* after the fact, so revenue is booked at the sale and a tax-portal
timeout must never block it. Standard (B2B) invoices are *cleared* in advance, so revenue waits. Getting this
backwards would either overstate revenue or stall the shop's books.

## The newest model (`dbt/models/gold/fact_merchant_dispute_monitor.sql`)

Card schemes put merchants with too many chargebacks into a monitoring programme — fines, reserves, and
eventually losing the ability to accept cards. An acquiring and settlement platform is exactly the thing that
has to run that check, and MIZAN already carries CAPTURE, REFUND and CHARGEBACK as native event types.

**The point of the model is the count floor, not the ratio:**

| Rule | Merchants flagged |
|---|---|
| Ratio ≥ 1.5% alone | **71** of 121 (59% of the portfolio — a noise generator, not a control) |
| Ratio ≥ 1.5% **and** ≥ 100 disputes | **1** |

```
MID900001 · 10,530 captures · 200 disputes · 1.90% · SAR 319,280.25 taken back
```

A merchant with 43 captures and 3 disputes reads 6.98% and means nothing. That is precisely why the real
programmes require both a ratio and a minimum count. The model emits `breaches_ratio`, `meets_count_floor`
and `in_monitoring_programme` **separately**, so the gap between the naive and correct answers is visible on
screen rather than asserted in prose.

A dbt test fails if the floor ever stops suppressing anything — because that is how this model would rot: it
would not error, it would quietly become the naive version while still returning rows.

**Stated on the page, not buried:** the thresholds come from secondary industry write-ups, not Visa's or
Mastercard's rulebooks, and they move (Visa replaced its programme in 2025 and cut the merchant line from
2.2% to 1.5% in April 2026). They are dbt vars. The window is this dataset's 20 days, not a calendar month.

---

# PART 6 — TESTS AND PROOFS

## The invariants

Fourteen numbered invariants, each bound to named tests. A sample:

| ID | Claim |
|---|---|
| I-01 | Per device, ICVs are strictly sequential with zero gaps, chaining from the genesis PIH |
| I-02 | `PIH[n] == invoice_hash[n-1]`, computed once at signing |
| I-03 | Only 200/202/400/401/403 are definitive; everything else retries identical bytes. `accounting_postings == 1` per invoice |
| I-04 | QR TLV length is the UTF-8 **byte** length — property-tested over random Arabic strings |
| I-05 | Expected Net == Bank Paid + In-Transit + Quarantined, and `unclassified_events == 0` |
| I-06 | Net Sales == GL card clearing, and **zero FLOAT columns** in financial schemas |
| I-07 | A shredded identity is unrecoverable — **including via vault time travel** |
| I-09 | Zero false merges on conflicting National IDs (the brother test) |
| I-11 | Salted join row count and SAR checksum match the unsalted baseline exactly |
| I-13 | 100% of Gold columns traced, with run_id and git_sha |

## Proof artifacts

- `docs/PROOF_MANIFEST.md` — 13 claims, each with the proof file behind it and that file's SHA-256
- `docs/artifacts/` — JSON and HTML evidence from real runs, plus Spark UI, Airflow and Marquez captures
- `docs/artifacts/13_dr_drill.json` — the disaster recovery fingerprints

## Tests that deserve mention

- **The chaos suite** — eight ZATCA failure scenarios, not unit tests
- **The brother test** — a hard negative that a fuzzy matcher fails
- **Vault time travel** — restores an old vault version and proves the key is still gone
- **The checksum test** — three join strategies, one SAR total
- **The DR fingerprint test** — proves the drill detects a one-halala difference, because a restore check
  blind to a halala proves nothing
- **`test_cards_respond_to_their_own_page_slicer`** — written after a Power BI card was found ignoring its
  own page filter; it caught the same class of bug a second time, on the newest page, two days ago

---

# PART 7 — WHAT IS DEPLOYED AND RUNNING

| Thing | Where | State |
|---|---|---|
| Public snapshot site | Azure Static Web App, no login | Live |
| Fabric App | `mizan-ksa-dev` workspace, Fabric sign-in | Live |
| Power BI report | 5 pages: CFO Settlement, Tax ZATCA Health, CDO Data Trust, Payments & Calendar, Merchant Risk | Live |
| Semantic model | Direct Lake over WH_MIZAN | Live |
| Lakehouse + Warehouse | `LH_MIZAN`, `WH_MIZAN` | Built |
| Eventstream + Eventhouse | `ES_MIZAN`, `EH_MIZAN` | Built, idle unless replayed |
| Mirrored database | `MR_MIZAN` | Replicating |
| Ask MIZAN agent | Azure Function + Azure OpenAI, owner's personal tenant | Live until credit expires 2026-12-14 |
| Airflow + Marquez | Docker, local | Built; not currently running |
| CI | GitHub Actions: ruff, pytest (non-Spark), dbt parse, Fabric App tsc + vitest, full suite | Green |

---

# PART 8 — HONEST LIMITATIONS

All 17 are in `HONESTY.md`. The ones a reviewer should weigh:

1. **All data is synthetic.** ~99K generated rows. The 20M figure is a local Docker stress benchmark, not a
   Fabric workload.
2. **Not a certified tax product.** Standards-informed, not ZATCA-certified, and it talks to a mock portal.
3. **Signing uses a self-generated secp256k1 test key.** The full XAdES signed-properties structure and real
   ZATCA certification are out of scope (ADR-006).
4. **ERP lines are ACDOCA-*shaped*.** No SAP system is involved.
5. **The Fabric evidence file predates a price correction.** It records a genuine run whose gross captures
   were SAR 22,390,730.16; local Gold is now SAR 22,391,236.23. The dbt result still stands; the money
   figures are from the earlier dataset. Refreshing needs a full re-run on the tenant.
6. **15 of 184 app tests skip** for that same reason, and the README says so rather than implying all pass.
7. **The agent's number check is lexical.** It proves a number appeared in a tool result; it cannot prove the
   number is used in the right sentence.
8. **The agent endpoint is origin-guarded, not authenticated** (ADR-013). An Origin header is trivially
   forged. Rate limits and a budget alert bound the loss, which is Azure credit and never data.
9. **Two ZATCA SDK checks still fail, and both are defects in the SDK**, reproduced in HONESTY.md:
   `BR-KSA-50` compares line VAT in IEEE doubles (96.00 × 0.15 = 14.399999999999999) and rejects our exact
   14.40; and the QR stage is unsatisfiable because two other rules force two `TaxTotal` elements which the
   QR check then sums.
10. **Open mirroring is demonstrated, not load-bearing** (ADR-014). Gold reads the dbt seed. Pointing it at
    the mirror would make the models depend on a Fabric-only feature and stop them building on DuckDB in CI.
11. **Dispute thresholds are from secondary sources**, not scheme rulebooks, and the window is 20 days, not
    a calendar month.
12. **The Fabric capacity is a trial the owner does not control**, so the live Fabric surfaces are not permanent.
    What is permanent: the public site has no tenant dependency, and `scripts/fabric_provision.py`,
    `fabric_deploy.py`, `fabric_streaming.py` and `fabric_powerbi.py` rebuild the entire workspace from this
    repository on any capacity.
13. **The Fabric Data Agent could not be created** — the trial SKU is unsupported.
14. **Arabic headings were written by the builder**, not reviewed by a native speaker.

## Claims that rest on reasoning rather than measurement

Stated explicitly because a reviewer should know which is which:

- The fix to two broken Power BI cards (comparing `int64` columns to `TRUE()`) was verified **by eye on the
  deployed report**, not by a query, because `executeQueries` needs a token for the tenant Fabric runs in and
  the local Azure CLI session is on a different tenant.

---

# PART 9 — THINGS THIS PROJECT GOT WRONG, AND FIXED

Included because a reviewer learns more from these than from the successes.

1. **A card that ignored its own page slicer.** Found once on the payments page, fixed, and a test written.
   That test caught the identical mistake again two days ago on the brand-new Merchant Risk page.
2. **Two cards rendering as errors.** The new dispute measures compared `int64` columns to `TRUE()`. DAX does
   not return false there — it errors, and the card shows "See details". The page shipped broken and was only
   caught by looking at it.
3. **A model that did not run on Fabric at all.** `DATE_DIFF` is DuckDB syntax; T-SQL wants `DATEDIFF`. Now
   behind a macro, like the existing boolean macro.
4. **A dbt test that did not run on Fabric either** — twice, for different dialect reasons (a CTE inside the
   derived table dbt wraps tests in, then `GROUP BY 'x'`).
5. **An Eventstream that delivered zero rows** because the Kusto writer cannot write a KQL `decimal`.
   Resisted the temptation to use float.
6. **A headline that claimed too much.** The hero used to say every halala was reconciled while 112
   merchant-days were pending. Rewritten.
7. **A scene caption reading "64 of 64 Gold columns traced"** while the generated hero said 76 and the truth
   was 91. The generated number was right; the hand-typed caption had drifted. An argument for the project's
   own rule that every figure must be generated.
8. **Three stale test counts** in the README, the one-pager and the LinkedIn draft, repeated from memory
   rather than counted.
9. **Windows Smart App Control blocked DuckDB's unsigned delta extension**, breaking the build and 15 tests.
   Fixed by writing a `_delta_log` replay that uses DuckDB's built-in Parquet reader — rather than weakening
   the machine's security settings.

---

# PART 10 — WHAT IS LEFT

**Requiring a human:**

1. An eight-shot screenshot set for the README (the placeholders exist and currently render broken)
2. A 2:30 demo video (shot list written; it does not yet show the Airflow DAG or the Marquez lineage graph,
   which is arguably the biggest gap in it for a data engineering audience)
3. A native Arabic speaker to review the Arabic headings
4. A re-run on the Fabric tenant to refresh the stale evidence file and un-skip 15 app tests

**Considered and deliberately not built:**

- **Impossible-travel fraud detection** — it is the card issuer's job, not an acquirer's, and it would have
  needed a planted case plus a new coordinates seed
- **IBAN 3-hop circular mule rings** — needs a whole second data domain (bank accounts and transfers) that
  would connect to nothing else in the project
- **A Fabric deployment pipeline** — needs three workspaces and a paid capacity; ALM here is git plus
  scripts that rebuild the whole workspace from the repo, which a deployment pipeline cannot do
- **Fabric Activator alerts** — alerts created on a trial capacity keep firing after the trial expires and
  cannot be edited, on a tenant the owner does not control

---

# PART 11 — WHERE REVIEW IS MOST WANTED

Specific questions, rather than "what do you think":

1. **Is the scope too wide?** The project spans e-invoicing, reconciliation, privacy, master data,
   classification, streaming, skew, orchestration, lineage, AI governance, mirroring and dispute monitoring.
   Does that read as breadth or as a lack of focus? Which two or three would you cut?

2. **Is the "honesty" framing an asset or a liability?** `HONESTY.md` lists 17 limitations. Does that build
   credibility with an interviewer, or does it hand them a list of objections?

3. **Scale.** 99K rows generated, 20M in a benchmark. A competing blueprint claims 98.5M rows (unbuilt). Is
   the measured-but-smaller number a real disadvantage in hiring, and if so, is generating more rows worth
   it or is it theatre?

4. **The presentation layer.** The Command Center (Three.js, GSAP, D3) is outside the frozen stack and is
   presentation-only. Is it a differentiator, or does it signal a portfolio project rather than engineering?

5. **What should be deleted?** Which parts add surface area without adding evidence?

6. **What would you rewrite?** Particularly: the reconciliation model, the ZATCA engine's state machine, or
   the governed-AI layer.

7. **What is missing that a Saudi/GCC data engineering interviewer would expect to see?**

8. **Is any claim in this document overstated, or any number unsupported?** That question is sincere; the
   project's stated value is that it does not overclaim, so a caught overclaim is the most useful feedback
   available.

---

*Every figure in this document is taken from the repository, a generated export, or a named proof run. Where
a figure could not be verified, the text says so. Sources: `PROGRESS.md`, `HONESTY.md`, `invariants.md`,
`docs/adr/ADR-001…014`, `docs/PROOF_MANIFEST.md`, `docs/artifacts/`, and the test suite itself.*

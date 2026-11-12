# CLAUDE.md — standing rules for every session on MIZAN-KSA

**Read `PROGRESS.md` first, every session.** Resume from the next unfinished phase. Never redo finished work.

Spec: `MIZAN-KSA_Final_Master_Engineering_Blueprint_v1.1.pdf` (repo root, git-ignored). It is the
design-frozen spec **v1.1 — Design Freeze**. If a spec file does not say that on page 1, stop and ask.
The project owner is learning: explain decisions plainly.

## FROZEN — never change without asking the owner

- **Stack:** Microsoft Fabric (data plane) + Apache Airflow, dbt-fabric, OpenLineage (+ Marquez), pytest,
  Docker, GitHub Actions. No other tools, databases, Great Expectations, Kubernetes or extra domains.
  A local DuckDB target for dbt tests/CI is allowed.
- **Schemas:** `LH_MIZAN` = `brz, ctl, slv, quarantine, security, audit, meta, ai`; `WH_MIZAN` = `gld`.
- **Table and module names** exactly as in the spec (Section 7 diagram, Section 7.1 key contract).
- **ADR-001..006** (spec Section 5.1, `docs/adr/`) are decisions, not suggestions.

## Non-negotiable correctness rules (spec Sections 8 and 12)

### Money
- Python `Decimal`, SQL `DECIMAL(18,2)`. **Never float/double**.
- Amounts are **positive**; `event_type` carries the sign (CAPTURE / REFUND / CHARGEBACK).
- MDR fees and VAT on fees come **from the bank file**, at the bank's grain — never recomputed per line.
- Timezone **Asia/Riyadh** (Spark session TZ too). Settlement date comes **from the bank file**.

### ZATCA
- Genesis PIH = `base64(hex(sha256("0")))` = `NWZlY2Vi...OQ==` (NOT base64 of the raw digest).
- `invoice_hash` = base64(SHA-256(C14N 1.0 XML with `ext:UBLExtensions`, `cac:Signature` and the QR
  `cac:AdditionalDocumentReference` removed)). Computed **once at signing**, stored in
  `ctl.invoice_outbox.invoice_hash`, and becomes the next PIH whatever ZATCA answers.
- Persist **SUBMITTING before any HTTP call**. A worker restart in SUBMITTING -> UNKNOWN_OUTCOME.
- Only **200 / 202 / 400 / 401 / 403** are definitive. 200 -> CLEARED|REPORTED, 202 -> ACCEPTED_WITH_WARNINGS,
  400 -> CONFIRMED_REJECTION (stays in chain; fix is a NEW doc with a new ICV), 401/403 -> AUTH_HOLD.
  Everything else -> UNKNOWN_OUTCOME and **retry identical UUID + bytes**.
- B2C (REPORTING) posts GL at sale; B2B (CLEARANCE) posts after clearance. GL idempotency key = `invoice_uuid`.
  `accounting_postings == 1` per invoice_uuid.
- TLV length = **UTF-8 byte** length; tags 1-7 text, **tags 8-9 raw bytes**; each value <= 255 bytes.
- Signed XML stored as BINARY, only in `audit.zatca_chain_journal`.

### Reconciliation
- **Key spine** (UNION of keys from payments, settlement and GL). No LEFT JOIN that can drop rows.
- `IN_TRANSIT` expectation rows for events whose bank file has not arrived.
- `unclassified_events` counted; **bank variance AND GL variance must be 0.00**.

### PDPL
- `legal_hold_class` uppercase (`TAX`/`SAMA`/`CONSENT`), **fail closed on unknown**.
- Encrypt PII **at the Bronze write** (HMAC-SHA256 token + AES-256-GCM per-subject DEK).
- Vault table: zero deleted-file retention + **VACUUM after shred**.
- Remove the token -> ID link on erasure. Tombstones in `ctl.deletion_tombstones`.
- Restore Guard tested against **data AND vault** time travel.

### Fabric Warehouse
- No `NVARCHAR`, `DATETIME`, `MONEY`. `VARCHAR(n)` is sized in **bytes** (Arabic = 2x chars, more for safety).
- Gold models materialized as **tables**.

### General
- Enums **UPPERCASE** with `accepted_values` tests; unknown values raise or go to quarantine — never an else branch.
- Arabic literals in code as `\uXXXX` escapes.
- No "AI refinement" wording in code/README/CV; say "transport failure (5xx/timeout)".
- **Secrets only in `.env`** (git-ignored). Never commit them.

## How to work

- Each phase: tests for everything built; `.\.venv\Scripts\python.exe -m pytest -q` and
  `.\.venv\Scripts\python.exe -m ruff check src tests` green; update `PROGRESS.md`; **one git commit**.
- After each phase, tell the owner in 3 plain sentences: what was built, what it proves, one interview point.
- Ask before: installing anything globally, deleting files, changing system settings, touching git remotes.
  **Never change the PowerShell execution policy** — call `.\.venv\Scripts\python.exe` directly.
- Stop only for credentials, an account action, or a decision the spec does not settle.
- Windows: edit files with the Edit/Write tools or Python, never PowerShell `Get-Content`/`Set-Content`
  (they corrupt UTF-8). Use `git commit -F <file>` for messages with quotes.
- Determinism: generators use a fixed seed and must produce byte-identical output on rerun.

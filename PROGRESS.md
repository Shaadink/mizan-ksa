# PROGRESS.md

Read this first every session. Resume from the first phase that is not DONE.

| Phase | Name | Status | Tests (cumulative) |
|-------|------|--------|--------------------|
| 0 | Scaffold | DONE | 7 |
| 1 | Deterministic generator | DONE | 48 |
| 2 | ZATCA engine (M1-2) | DONE | 93 |
| 3 | Bronze + Silver (PySpark) | DONE | 133 |
| 4 | Gold (dbt) | DONE | 140 |
| 5 | MDM (M4) | DONE | 177 (with 6) |
| 6 | PDPL + NDMO (M5-6) | DONE | 177 |
| 7 | Skew (M7) | TODO (Docker installed; reboot pending) | |
| 8 | Orchestration | TODO | |
| 9 | Governed AI (M8) | IN PROGRESS (unit layer done, 18 tests) | |
| 10 | Fabric deployment | TODO — needs tenant credentials in .env | |
| 9b | Streaming (replay, KQL, docs) | TODO | |
| 11 | Packaging | TODO | |

## Environment (checked 2026-11-13)

- Windows 11, Python 3.12.10, project venv `.venv` (call `.\.venv\Scripts\python.exe` directly).
- git 2.56. Repo-local author is a **placeholder** (`MIZAN Builder <mizan@localhost>`): the owner will supply
  their GitHub noreply identity; rewrite all commit authors before any push (no remote exists yet).
- Java: portable Temurin JDK 17.0.21 + community winutils in `.tools/` (git-ignored; owner chose portable).
  Spark 3.5.9 + delta-spark 3.2.1 in the venv (`[spark]` extra). **Docker: not installed** (owner installs before Phase 7).

## Phase 0 — Scaffold (DONE)

`pyproject.toml`, `.gitignore`, `.gitattributes` (LF), `.env.example`, `CLAUDE.md`, `README.md`, `HONESTY.md`,
`invariants.md` (I-01..I-14), `docs/adr/ADR-001..006`, `src/mizan/__init__.py`, `tests/test_scaffold.py`.

## Phase 1 — Deterministic generator (DONE)

Run: `.\.venv\Scripts\python.exe -m mizan.generator --out data/generated` (seed 20261112, ~3 s).

Built: `src/mizan/common/money.py` (Decimal-only, refuses float), `common/saudi_ids.py` (checksum IDs, VAT, 700),
`generator/catalog.py` (escaped Arabic names/items, synthetic fee schedule, GL accounts), `generator/build.py`,
`scripts/escape_non_ascii.py`.

Output (period 2026-02-12..2026-03-03 KSA, 99,418 rows):

| File | Rows |
|------|------|
| orders/commerce_events.csv | 25,000 (23,500 ORDER_PLACED + 1,500 RETURN_REQUESTED) |
| zatca/invoice_requests.jsonl | 25,000 (23,500 INVOICE + 1,500 CREDIT_NOTE; EGS-01..05; EGS-05 = e-com, B2C only) |
| payments/payment_events.csv | 18,000 (16,200 CAPTURE, 1,500 partial REFUND, 300 CHARGEBACK) |
| settlement/NAJDACQ_SETTLEMENT_*.csv | 17,000 (19 T+1 files; last day's 1,000 events IN_TRANSIT) + 1 byte-identical resend |
| erp/erp_gl_acdoca.csv | 9,418 (store x day x account; HSL positive + DRCRK) |
| crm/ (POS cp1256, ECOM utf8, SPL obs) | 5,000 |
| demo/ | orphan settlement line, 0.01 float-bug GL line (overlay, NOT in main build) |
| zatca/fatoora_fault_plan.json, defect_manifest.json, _control.json (sha256 per file), reference/*.csv | |

Planted defects D01-D12 (`defect_manifest.json`): D01 transport timeout, D02 ICV gap (journal tamper, EGS-03
ICV 500), D03 crash in SUBMITTING, D04 HTTP 400 (VAT +0.01), D05 orphan settlement (demo), D06 0.01 float drift
(demo), D07 duplicate settlement batch, D08 CP1256 mojibake, D09 '?????' unrecoverable, D10 brothers + ID-less
third, D11 five spellings one customer, D12 65% mega-MID + WALK_IN.
ZATCA tape: EGS-05 positions 101-104 (102 = timeout -> crash -> 200; 103 = 400).

Key design facts for later phases:
- Settlement `net_amount` positive with `dr_cr` (CR purchase, DR refund/chargeback); fees per line from the bank.
- GL card clearing (113100) per MID-day = captures - refunds - chargebacks; tests prove both legs close to 0.00
  in Python (`test_bank_leg_closes_to_zero`, `test_gl_leg_closes_to_zero`).
- Gold must sign GL by DRCRK (S = +, H = -) and settlement by dr_cr, since amounts are positive.
- Timestamps in source files are UTC (`...Z`); business dates must be derived in Asia/Riyadh (>100 events cross midnight).

Tests: 48 passed. Ruff: clean.

## Phase 2 — ZATCA engine, Modules 1-2 (DONE)

Run: `.\.venv\Scripts\python.exe -m mizan.clearance --data data/generated --out data/out/zatca` (~45 s).

Built in `src/mizan/clearance/`: `tlv_qr_and_state_machine.py` (spec reference code: GENESIS_PIH, hash, TLV,
state machine, gl_action + hardened DOCTYPE-refusing parser, QR builder/decoder), `ubl.py` (two-step UBL builder:
unsigned -> hash -> sign -> attach UBLExtensions/Signature/QR), `signing.py` (ECDSA secp256k1 deterministic test
key per EGS + generation, self-signed cert for tags 8/9), `engine.py` (ChainStore = ctl.egs_chain_state /
ctl.invoice_outbox / audit.zatca_chain_journal; per-EGS lock sequencer; worker with SUBMITTING-before-HTTP,
restart recovery, AUTH_HOLD CSID renewal, corrections as new docs; idempotent GL sink keyed on sale uuid),
`mock_fatoora.py` (verifies QR hash, signature, VAT sums; scripted faults), `chain_verifier.py`, `__main__.py`.

Full-run result: 25,001 docs (1 correction), 23,913 REPORTED / 1,087 CLEARED / 1 CONFIRMED_REJECTION, 1 worker
restart, 0 chain violations, 25,000 GL postings with max 1 call per sale; tamper demo -> 2 violations
(ICV_GAP + PIH_MISMATCH at EGS-03 ICV 501). Artifact 1 source table: `data/out/zatca/chain_tape.md`.

Chaos tests (tests/test_zatca_chaos.py): 1 timeout retry identical bytes, 2 crash in SUBMITTING -> recover,
3 rejection retained + correction chains from it, 4 verify from genesis (+ tamper, + XML edit), 5 non-definitive
statuses (408/409/429/500/502/503/504/302), 6 401/403 AUTH_HOLD -> renew -> identical bytes, 7 B2B held / B2C
posted despite timeout, 8 eight concurrent lanes on one EGS -> ICV 1..240 gapless.

Tests: 93 passed. Ruff: clean.

## Phase 3 — Bronze + Silver, PySpark (DONE)

Run: `.\.venv\Scripts\python.exe -m mizan.spark.pipeline --data data/generated --lake data/lake [--demo-breaks]`
(about 6 min locally, ZATCA included). Dev keys: `scripts/init_local_env.py` writes them to `.env`.

Built: `spark/session.py` (one factory local|fabric, Asia/Riyadh, TableLocator), `spark/lake.py` (Delta helpers,
`rows_to_df` staging without Python workers), `spark/contracts.py` (7 source contracts), `spark/bronze.py`
(Python adapter: sha256 vs _control.json, decode, CP1256 repair, HMAC token, AES-GCM PII, ciphertext-only staging;
Spark: contracts -> quarantine.schema_rejections (idempotent), ctl.applied_event_ledger dedup + corrections,
ctl.ingestion_watermarks, security.pii_vault_metadata with zero file retention), `spark/silver.py`
(slv.payment_lifecycle, slv.settlement_lines with IN_TRANSIT estimates + QUARANTINED breaks ->
quarantine.settlement_breaks, slv.erp_gl_journal_lines; Delta CHECK constraints), `spark/zatca_land.py`
(ctl.egs_chain_state, ctl.invoice_outbox, audit.zatca_chain_journal BINARY XML, slv.zatca_invoice_documents,
quarantine.zatca_chain_violations; reruns continue the chain), `privacy/crypto.py`, `ingest/cp1256.py`,
`mdm/arabic_norm_and_privacy.py` (spec reference code for Modules 4-6), ADR-007, ADR-008.

Full-run result: every file sha256 matches; RESEND file ALL_DUPLICATE (995 rows); 15 '?????' rows quarantined;
41 mojibake repaired; slv.settlement_lines 17,000 PAID_BANK + 1,000 IN_TRANSIT, 0 QUARANTINED on main data;
bank leg closes to 0.00 per MID-day in Spark; ZATCA 25,001 docs, 0 violations. Demo overlay: orphan ->
QUARANTINED + ORPHAN_BANK_LINE; float-bug GL line lands as a correction (0.01 lower).

Decisions taken without asking (veto-able): added `brz.crm_party_raw` and `brz.spl_address_raw` (spec names no
Bronze table for CRM/SPL); ADR-007 sign convention; ADR-008 adapter design. All in HONESTY.md.

Tests: 133 passed (full suite about 12 min; `-m "not spark"` skips the Spark module). Ruff: clean.

## Phase 4 — Gold in dbt (DONE)

Run: `cd dbt; $env:MIZAN_LAKE_ROOT="../data/lake"; ..\.venv\Scripts\dbt.exe build --profiles-dir . --target duckdb`.

Built in `dbt/`: one project, two targets (`duckdb` local/CI reading Silver Delta via `delta_scan`; `fabric` = WH_MIZAN
via service principal from env vars). Models (all `table`, schema `gld`): `fact_merchant_settlement_recon` (key spine
UNION of payments/settlement/GL keys, IN_TRANSIT + QUARANTINED legs, bank AND GL variance, unclassified_events),
`fact_zatca_clearance_ledger`, `dim_date_saudi` (Fri+Sat weekend; Hijri added in Phase 5). ONE recon SQL file for both
adapters (only `date_spine` dispatches per dialect). Generic tests `unique_combination`, `no_float_columns`; singular
circuit breaker `assert_zero_unexplained_halala_variance`; source tests with accepted_values on every enum.
`tests/test_gold_dbt.py` runs dbt in a child process (dbt-duckdb holds its file open in-process).

Tests: 140 passed (full suite ~7 min). Ruff: clean. Local Spark pins the driver to 127.0.0.1 (WSL2 adapter broke hostname resolution).

Result: main build green, recon closes to 0.00 on every MID-day; demo overlay fails ONLY the circuit breaker, on exactly
the two planted MID-days (D05 orphan bank line, D06 0.01 GL drift).

## Phase 5 — MDM, Module 4 (DONE; committed together with Phase 6)

Built: `mdm/engine.py` (pure Python: Typed Identifier Registry 1x/2x Modulo-10, VAT 3..3, 700 format-only;
deterministic ladder ANCHOR -> ID-less name-compatible + shared phone with exactly ONE candidate -> else steward queue;
append-only ledger fold = membership; steward pins; survivorship: clean source, plain spelling over tashkeel/ligature,
full English name), `spark/mdm_land.py` (decrypts in driver memory only; writes slv.golden_party_scd2 (SCD2),
slv.identifier_registry, slv.entity_merge_ledger, slv.address_observations (SPL 4L+4D, canonicalised),
quarantine.mdm_match_conflicts; `apply_steward_decision`). dbt: `dim_party_golden`, `dim_date_saudi` with versioned
Umm al-Qura seed (`scripts/build_hijri_seed.py`, .NET UmAlQuraCalendar, `UAQ_DOTNET_V1`) + announcement-override seed
(shipped empty; mechanism tested with a test-only row). ADR-009.

Result: 3,985 records -> 2,552 golden profiles; D11 five spellings -> 1 golden (anchor = IQAMA); D10 brothers separate;
ID-less third -> 1 OPEN conflict; replay appends 0 ledger events; partition equals an independent answer key built from
the CSVs (54 cross-script ID-less records stay separate by design: no transliteration).

## Phase 6 — PDPL + NDMO, Modules 5-6 (DONE)

Built: Bronze writes `security.subject_token_map` (KEK-encrypted token -> source ref) and refuses DEKs for tombstoned
tokens; `privacy/pdpl.py` (`execute_dsr`: resolve via ID HMAC + golden membership to every token, reference decision
fails closed, vault NULL+SHREDDED, VACUUM 0h on vault and token map, tombstones, MDM re-resolve, audit.pdpl_dsr_evidence
with tax totals before/after; `restore_guard`), `governance/catalog.py` (NDMO 4 tiers by ordered rules, table inherits max
tier, over-classification, fail-closed legal_hold_class per table, residency policy + gate), `governance/residency_gate.py`
(CLI), `config/residency_policy.yml`, `spark/governance_land.py` (meta.column_classification). dbt: `mart_ndmo_scorecard`
(6 quality dimensions + over-classification). ADR-010. Extra tests asked by the owner: CREDIT_NOTE posts under its own
uuid and a full replay posts/sends nothing; slv.zatca_invoice_documents holds no cleartext buyer PII.

Result: DSR on the D11 customer shreds 5 linked tokens, 18 journal rows LEGAL_HOLD_RETAINED, tax totals identical;
vault time travel cannot return the key; restoring a pre-erasure vault backup + RESTORE of Silver is re-shredded by the
guard; demo dbt build fails only the circuit breaker and SKIPS the downstream scorecard. Residency gate: 0 violations.

Tests: 177 passed (full ~11 min). Ruff: clean.

## Open issues

1. 2026-11-14: installed via winget — GitHub CLI 2.104, WSL2 (`wsl --install --no-distribution`), Docker Desktop
   4.99, Azure CLI 2.92. **Windows reboot was pending** after WSL2.
2. GitHub: signed in as Shaadink (2026-11-14); repo-local identity `Shadin K <207139190+Shaadink@users.noreply.github.com>`;
   `gh auth setup-git` done. Commit authors rewritten before the first push.

## Next step

Owner's end-to-end plan (2026-11-14), in order:
1. After reboot: start Docker Desktop once (accept its terms), check `docker run hello-world`.
2. Step C: `gh auth login --web` -> git identity -> rewrite commit authors -> create PRIVATE repo `mizan-ksa`,
   add GitHub Actions CI, push, confirm CI green. Push after every phase.
3. Step D: Phases 5 MDM -> 6 PDPL+NDMO -> 7 Skew (Docker) -> 8 Airflow+OpenLineage/Marquez (Docker) -> 9 Governed AI
   -> 9b Streaming. Add tests if missing: CREDIT_NOTE posts to GL under its own uuid and replays post nothing;
   slv.zatca_invoice_documents holds no cleartext buyer PII.
4. Step E: `az login`; Fabric REST: workspace mizan-ksa-dev (trial capacity), LH_MIZAN (schemas enabled), WH_MIZAN,
   EH_MIZAN, ES_MIZAN; service principal values only in .env; Phase 10 deploy + dbt build on WH_MIZAN + stream replay;
   Power BI Control Tower (3 pages, PBIP/TMDL) + Fabric Data Agent; portal-only parts -> docs/PORTAL_STEPS.md.
5. Step F / Phase 11: Playwright screenshots into docs/artifacts/, README, 10 ADRs, HONESTY.md, final list for owner.

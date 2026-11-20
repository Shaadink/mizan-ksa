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
| 7 | Skew (M7) | DONE | 221 |
| 8 | Orchestration (Airflow + OpenLineage/Marquez) | DONE | 221 |
| 9 | Governed AI (M8) | DONE | 220 (all phases so far) |
| 10 | Fabric deployment | DONE (Data Agent needs paid capacity: docs/PORTAL_STEPS.md) | 222 |
| 9b | Streaming (replay, KQL, docs) | DONE (local + Fabric: rows in EH_MIZAN, rules 1/1/2) | 222 |
| 11 | Packaging (artifacts, README, ADRs, HONESTY) | DONE | 221 |
| 12 | MIZAN Command Center (cinematic web control tower, ADR-011) | DONE | 231 |
| 13 | Fabric App plan, Stage 1 "Truth" (bugs 1-9) | DONE | 241 |
| 13 | Stage 2 Fabric App foundation | DONE (deployed) | 248 py + 170 vitest |
| 13 | Stage 3 app upgrade | DONE (payment-method cards need a Gold change) | 249 py + 180 vitest |
| 13 | Stage 4 spec rules and polish | DONE | 250 py + 180 vitest |
| 13 | Stage 5 ship (standalone copy, LinkedIn kit) | DONE | 250 py + 180 vitest |

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

## Phase 9 — Governed AI, Module 8 (DONE)

Built: `ai/governed.py` (policy chunker with tier/ACL inheritance, section markers only raise; entitlement filter BEFORE
TF-IDF ranking; tombstone suppression; money questions only via allow-listed read-only Gold SQL templates guarded by
`validate_readonly_sql`; refusals NOT_ENTITLED / NO_MATCH / TEXT_MATH_FORBIDDEN; audit rows store a question hash only),
`spark/ai_land.py` (ai.policy_chunks = 4 bilingual policies + ~1,350 case notes from RETURN_REQUESTED events keyed by
subject token; ai.agent_audit_log; DuckDB runner for Gold), `docs/policies/*.md`. Deterministic stand-in, no LLM (HONESTY).
Proof: junior refused MDR negotiation, finance answered; DPO never ranked the SECRET section; CFO's variance answer comes
from gld.fact_merchant_settlement_recon (0.00 / 0.00 / 0); a care agent sees a case note, the subject is erased via the
token map, and the note is no longer served (query time) and gone from the rebuilt index.

## Phase 9b — Streaming (DONE locally)

Built: `streaming/replay.py` (CHECKOUT / PAYMENT / INVOICE events, HMAC tokens only, deterministic, Event Hubs REST + SAS
from `EVENTSTREAM_CONNECTION` in .env, batches < 1 MB, `--dry-run`, `--inject-velocity-burst`), `streaming/rules.py`
(reference velocity / mule-ring / 24 h reporting SLA), `kql/01..04` (table + JSON mapping + rule functions + lag tile),
`docs/STREAMING.md`. Proof: rules catch exactly the injected customer + mobile and the two SLA cases (IR-0000102 late,
IR-0000103 rejected); quiet without injection. Sending into ES_MIZAN happens in Phase 10.

Tests: 220 passed (full suite ~14 min). Ruff: clean.

## Phase 7 — Skew, Module 7 (DONE)

Run: `docker compose -f docker/docker-compose.skew.yml run --rm --service-ports spark-bench` (ROWS=20000000 default;
HOLD=600 keeps the Spark UI on http://localhost:4040 for screenshots). Image `mizan-spark-bench:3.5.3` = apache/spark
3.5.3 + delta-spark 3.2.1, repo mounted at /work.

Built: `spark/skew.py` (WALK_IN/NULL isolation, deterministic xxhash64 salt mod 16 with dimension replication, hash-based
skewed generator, three-mode benchmark with task stats from the Spark REST API, Delta OPTIMIZE compaction,
`record_benchmarks` -> audit.benchmarks), `docker/spark/Dockerfile`, `docker/docker-compose.skew.yml`.
Result (20M rows, screenshot run): identical rows + SAR checksum in all three modes; straggler factor AQE off 61.8x
(15.3 s vs 0.25 s median), AQE skew-join 6.0x, salted slowest task 3.2 s; compaction 400 -> 1 file (first, quieter run:
20.3x / 3.4x / 2.1 s). JSON: `docs/artifacts/05_skew_benchmark_20m.json`.

## Phase 8 — Airflow + OpenLineage + Marquez (DONE)

Run: `docker compose -f docker/docker-compose.airflow.yml up -d --build` -> Airflow http://localhost:8080 (admin /
AIRFLOW_ADMIN_PASSWORD from .env), Marquez UI http://localhost:3000, API :5000.
Prereqs for a meaningful run: `data/lake` current (pipeline), `tmp/mizan_gold.duckdb` (dbt build), and
`data/out/lineage/gold_column_lineage.json` (`python -m mizan.lineage.openlineage --duckdb tmp/mizan_gold.duckdb
--lake data/lake`).

Built: `airflow/dags/mizan_daily.py` (4 Fabric jobs -> restore guard -> freshness gate -> dbt build -> AI index + NDMO
catalog -> residency gate -> lineage + run manifest), `orchestration/fabric_client.py` (REST: submit RunNotebook, poll
Location; SP token; mock), `orchestration/freshness.py`, `lineage/openlineage.py` (Gold column lineage 100% from the
dbt manifest + `dbt/lineage_overrides.json`, typed schema facets, run facet with git_sha + snapshot versions, HTTP POST),
`docker/airflow/*`, `docker/docker-compose.airflow.yml`. `scripts/init_local_env.py` now also writes
AIRFLOW_ADMIN_PASSWORD.
Result: DAG run all 11 tasks success (mock mode); Marquez has the job graph and the Bronze -> Silver -> Gold dataset graph
(22 nodes); column lineage for gld.fact_merchant_settlement_recon shows 28 nodes / 37 edges; run manifest carries the
real git sha.

## Phase 10 — Fabric deployment (DONE, with 2 portal items)

Where: workspace `mizan-ksa-dev` on Fabric trial FTL64 (UAE North), tenant hinducollege.ac.in (owner's college work
account). Azure CLI profiles: `%USERPROFILE%\.azure-college` (workspace owner, used for items owned by the user),
service principal `mizan-ksa-automation` (FABRIC_CLIENT_ID / SECRET in .env, workspace Contributor) for jobs and dbt.
The owner's personal tenant `shadinkarangadangmail.onmicrosoft.com` (profile `.azure-fabric`) holds an unused workspace;
Microsoft refused a Fabric trial there.

Scripts (all idempotent): `scripts/fabric_provision.py` (capacity + workspace + LH_MIZAN schemas + WH_MIZAN + EH_MIZAN +
ES_MIZAN, ids into .env), `scripts/fabric_deploy.py upload|notebook|run [steps]` (OneLake upload of code/policies/data
+ dev keys; notebook `nb_mizan_step`; runs `mizan.spark.pipeline.run_step` per step as Fabric jobs with the SP; reads
`Files/_logs/<step>.txt`), `scripts/fabric_streaming.py setup|conn|replay|check`, `scripts/fabric_powerbi.py`
(TMDL Direct Lake model + PBIR 3-page report; definitions saved in `powerbi/`).
Code changes for Fabric: `run_step` per pipeline step; env-driven paths (`MIZAN_ONELAKE_ROOT`, `MIZAN_FILES_MOUNT/URI`,
`MIZAN_STAGING_DIR/SPARK_PREFIX`) so Spark executors read OneLake while Python uses the mount.

Result (`docs/artifacts/10_fabric_run_evidence.json`): all 6 notebook steps Completed; same numbers as local (2,552
goldens, 25,001 ZATCA docs, 0 violations); `dbt build --target fabric` 65/65 PASS on WH_MIZAN; Gold recon 2,233 rows,
bank + GL variance 0.00; Power BI model answers DAX with the same totals; 91,513 events accepted by ES_MIZAN.
Not done by API (docs/PORTAL_STEPS.md): Data Agent (trial SKU unsupported).
2026-11-15: Eventstream -> Eventhouse fixed. Destination runtime logs showed the Kusto writer cannot write a KQL
`decimal` column; `MizanEvents.amount_sar` is now `string` (exact text) with `MizanEventsTyped()` doing `todecimal()`.
After `fabric_streaming.py setup` (republish) + `conn` + `replay`: CHECKOUT 23,511, INVOICE 50,002, PAYMENT 18,000;
VelocityAlerts 1, MuleRingAlerts 1, InvoiceReportingSlaBreaches 2; typed payment total SAR 23,782,562.35 (decimal).
2026-11-15: Control Tower report redesigned as code (`scripts/fabric_powerbi.py`): per page KPI cards, line/bar/
column/donut charts, slicer and detail table; Saudi-green styling; new measures (Merchants, MID Days, Retried
Documents, EGS Devices, Quality Score Pct, Classified Tables); ZATCA issue date related to dim_date_saudi.
`tests/test_powerbi_report.py` checks every visual field exists in the model. Local: hypothesis pinned <6.136
(its native DLL is blocked by Windows Smart App Control).

## Phase 11 — Proof artifacts + packaging (DONE)

`scripts/build_artifacts.py boards|shots|ui` builds HTML boards from real runs on scratch lake copies and screenshots
them with Playwright (venv): 01 ZATCA chain tape, 02 halala recon board (+ demo breaks, breaker FAIL), 03 PDPL
shred/restore (3 panels), 04 Arabic MDM board; live UIs: 05 Spark UI (jobs + AQE off / AQE skew-join / salted stage
pages, from a 20M Docker run held open with HOLD=900), 06 Airflow DAG, 07 Marquez lineage. All in `docs/artifacts/`,
embedded in README. README rewritten (artifacts first, Fabric results, architecture, run instructions). ADR-001..010.
HONESTY.md covers every phase. Not produced: the spec's animated GIF of the Power BI Control Tower (the report lives in
the owner's Fabric tenant behind their login; PNGs of the local UIs are provided instead).

## Phase 12 — MIZAN Command Center (DONE, owner-approved addition 2026-11-15)

`scripts/build_command_center.py` exports every figure (Gold DuckDB, Delta lake, ZATCA engine re-run on EGS-05,
stream replay + rules, dbt manifest lineage, Phase 11 proof boards, Fabric evidence) into `command_center/data.json`
and builds `command_center/index.html` from `template.html`. The page: Three.js golden scales hero (captures pan fills
first, bank pan T+1, settles level at variance 0.00), 10 scenes (pulse, money-flow sankey with particles, Hijri daily
ledger, 121 x 20 halala heatmap with planted-defect circuit breaker, ZATCA chain + ICV 102 incident replay, PDPL
erasure theatre, Arabic MDM convergence, stream river replay with alerts, lineage + NDMO, Spark race + Fabric run),
story mode with captions, Ctrl+K palette, CFO/TAX/CDO roles, reduced-motion support. Money = integer halalas in JS.
`tests/test_command_center.py` (6): exact money, identities, story facts vs sources, PII masking, embedded data and
pinned scripts, determinism (skips without the local lake). Published privately:
https://claude.ai/artifact/HeSui14YJRiTUwiFDAkXqD (rebuild: run the script, then republish index.html).
Screenshots: `docs/artifacts/08_command_center_*.png`. ADR-011; HONESTY row 12.

## Phase 13 — Fabric App plan (owner's 5-stage brief, 2026-11-15)

Stage 1 "Truth" DONE (tests `tests/test_stage1_truth.py`, one per bug; findings `docs/design/DATA_NOTES.md`):
1. `gld.fact_zatca_clearance_ledger` now keeps CONFIRMED_REJECTION: 25,001 docs (dbt model + accepted_values; no
   column change). Power BI: Documents in Chain / Accepted / Rejected. Rebuilt on WH_MIZAN (5/5 pass).
2. NDMO donut 27/27/27 -> 17/1/6/3: every CALCULATE filter wrapped in KEEPFILTERS (test parses all measures).
3./4. One shared `Checks Passing`; DQ 6/6 at 99.07% vs classification 1/27 at 22.09%, separate measures.
5. Not assessed = `in_transit_sar <> 0`: 112 MID-days on 2026-03-03 (2,121 assessed); `Bank Paid SAR (Assessed)`
   blank that day. Measures + export only (a Gold `assessment_status` column would need owner approval).
6. MID900001 = 73.8% of SAR (measure + export) vs skew test 65% of rows (read from skew.py).
7. Tax SAR 30,917,841.76 = card invoices 22,390,730.16 (= gross captures; corrections inherit the original's
   capture) + cash 7,545,182.44 + credit notes 981,929.16. New Invoices / Credit Notes / Net Invoiced measures.
8. EGS-05 = MID900001 only (Silver join). 9. Published run (dbt run_results + Fabric 65/65) vs candidate (demo build,
   breaker FAIL) in export `runs` and Command Center footer.
Verified on Fabric by DAX (executeQueries). Store city exists only in `data/generated/reference/merchants.csv`;
proposal: dbt seed `merchant_store_reference` (needs owner yes). Windows now blocks `dbt.exe`: run dbt as
`python -c "from dbt.cli.main import dbtRunner; ..."`. Design reference saved: `docs/design/MIZAN_Command_Center.html`.
`docs/design/FINAL_DESIGN_SPEC.md` not yet provided by the owner (needed for Stages 3-4 tokens/mirroring rules).

Stage 2 "Fabric App foundation" DONE (2026-11-15):
- Seed `merchant_store_reference` (owner-approved): unchanged copy of `reference/merchants.csv`, tests; built on
  DuckDB and WH_MIZAN (7/7 pass). For the Stage 3 map.
- `docs/fabric-app/RESEARCH.md`: Rayfin CLI 1.36.2, template `dataapp`, `fabric-semanticmodel` connector (DAX via
  `executeQuery`, delegated only, viewer needs Build), UAE North supported, `rayfin dev` creates a backend item.
- `apps/command-center/`: Data App scaffold (Node 24, deps pinned incl. gsap 3.12.5, d3 7.9.0, d3-sankey 0.12.3,
  three 0.128.0). 5 DAX queries (`src/command-center/queries/*.dax`, money as integer halalas) replace the embedded
  JSON for recon, daily, calendar, heatmap, ZATCA, NDMO, Stage-1 truth; proof-run sections ship in `proof.json`
  with sources. `shape.ts` (BigInt money) + `shape.spec.ts`: shaped live results == export, every section.
  `scripts/record_app_dax.py` records fixtures from the live model; `scripts/build_command_center.py` now also
  generates the app's `legacy/page.html|css|scenes.js` + `snapshot.json` + `proof.json` from `template.html`
  (standalone HTML unchanged). Snapshot fallback is labelled on screen. `preview.html` = local visual check.
- Rayfin: `npx rayfin login` (owner), connector `mizan` -> "MIZAN Control Tower Model" (delegated); all 5 queries
  pass through `fabric-app-semantic-model-tools run-dax-query`. `npx rayfin dev --yes` created dev backend item
  `command-center` in mizan-ksa-dev; local app at http://localhost:5173 (owner signs in to see "Live").
- Tests: `tests/test_fabric_app.py`, `tests/test_stage2_seed.py`; CI job `fabric-app` (tsc + vitest).
- Connectors do not run under `rayfin dev`; owner approved `npx rayfin up` (dry run shown first). DEPLOYED
  2026-11-15 to the same item `command-center` (protected asset access, no database):
  https://fond-gulf-57cbbd6a65-uaenorth.webapp.fabricapps.net . Redeploy: `cd apps/command-center; npx rayfin up
  --workspace-id <ws>` (or `npx rayfin up staticapp deploy` for frontend-only changes).

Stage 3a "interactivity" DONE (2026-11-15), deployed (`npx rayfin up staticapp deploy`):
- Semantic model: + `merchant_store_reference` and relationship recon[merchant_id] -> store (city filter; city
  gross sums to the total, verified by DAX).
- template.html (shared by standalone + app): filter bar (From/To, MID, City, Bank file assessed/not assessed, EGS,
  Invoice Simplified/Standard, Outcome), chips with remove, Clear; click-to-filter (ledger day, heatmap cell,
  EGS bar, donut slice, flow row); MID-day drill panel (all legs, "Awaiting bank file"/"Not assessed" honesty);
  scenes re-render on new data (render generation stops old animation loops). Standalone: bar disabled with
  "Filters need the live Fabric App". Host hook `window.MIZAN_QUERY(filters)`.
- App: `filters.ts` wraps each base query in CALCULATETABLE with validated predicates (no DAX injection);
  `filters.spec.ts`: injection rejected, 4 example filter sets committed (`queries/examples`) and recorded live
  (`__fixtures__/filtered`, `scripts/record_app_dax.py`), results agree with unfiltered Gold (MID-day, city sum,
  EGS+flow, 112 not-assessed). Payment-method filter NOT built: no payment method in Gold (needs owner approval).

Stage 3b "app shell" DONE (2026-11-15), deployed:
- Left icon menu (Home + the 12 requested scenes, collapsible; overlay on phones), header search (MID, EGS, city,
  ICV, invoice UUID/request id, golden id -> filter/jump/flash), profile from `config/profile.json` (Shadin K,
  LinkedIn link restricted to linkedin.com; initials until a photo is added).
- EGS picture cards: documents, last ICV, retries, chain breaks (Fabric chain run), docs vs prior 7 days (live DAX:
  zatca.dax EGSLAST/EGSRETRY/EGSDAY rows; export `zatca.egs_detail`; fixtures re-recorded, equality holds).
- Hover cards: MID 7-day captures trend + channel/city/EGS; map store and city cards.
- Store map scene: schematic KSA outline, stores by city (spread for visibility; reference has city only),
  coloured reconciled / awaiting bank file / no activity, routes store -> acquirer hub -> settlement bank, city
  click = city filter; city list.
- Data Life Cycle scene: sources -> Bronze -> Silver -> Gold -> serve, plus Airflow, ZATCA engine, circuit breaker,
  OpenLineage, Eventstream; live counts; every box jumps to its scene.
- Not built: payment-method picture cards (no payment method in Gold; needs owner approval for a new Gold model).

Stage 4 "spec rules and polish" DONE (2026-11-15), deployed (spec file still not provided; rules from the brief):
- Honesty: 03 Mar bank line breaks over a hatched "awaiting bank file, not assessed" day; not-assessed heatmap cells
  hatched with their own tooltip; hero stamp "BALANCED - 2,121 assessed MID-days"; recon panel shows net residual,
  gross absolute residual, broken keys, not assessed, plus Publishing (published PASS / candidate FAIL).
  New data: recon bank_net_residual, gl_net_residual, broken_keys (export + recon_totals.dax); stream SLA
  lag_minutes (IR-0000102 1,560 min).
- Colour: captures neutral (sankey, ledger, pulse, hero particles, map routes), heatmap volume in gold, refunds
  violet, fees grey, checkout violet; green only for pass/reconciled; every status has an icon or sign.
- ZATCA: "Simplified: reporting (B2C)" / "Standard: clearance (B2B)"; 3-part outcome bar (rejection <0.01%);
  24 h reporting window rings (historical replay).
- Defects (button or B) tilt the 3D scale, stamp "UNBALANCED - SAR 2,536.34 - candidate run", flash candidate run.
- Calendar: Ramadan band, Fri-Sat shading, "Govt payday (27th)", Hijri on its own tooltip line.
- EN/AR toggle (button or L): RTL layout, menu right, scale left; charts/IDs/numbers stay LTR, Western digits;
  menu, scene headings, hero and controls in Arabic (escapes / HTML entities, never raw); body text stays English.
- Provenance line on every scene (live/snapshot, published + candidate run, git SHA, data as-of; proof sources;
  "Historical replay" on the stream). Presenter keys: P chrome off, 1-9 scenes, T trace one riyal, B break a
  halala, L Arabic. Test: test_stage4_honesty_colour_zatca_language_and_presenter_rules.

Stage 5 "ship" DONE (2026-11-15):
- Standalone portfolio copy `command_center/index.html` (same template; filters disabled offline with a note):
  checked at desktop and phone width (fixed a life-cycle grid overflow on phones); republished to the private
  link https://claude.ai/artifact/HeSui14YJRiTUwiFDAkXqD.
- Fabric App live (protected): https://fond-gulf-57cbbd6a65-uaenorth.webapp.fabricapps.net
  (open from mizan-ksa-dev -> command-center -> Open).
- `docs/linkedin/VIDEO_SHOT_LIST.md` (2:30: Fabric + dbt green, app tour, story mode; clicks + captions),
  `docs/linkedin/LINKEDIN_POST.md` (164 words), README "Demo" section with 8 screenshot placeholders
  (`docs/artifacts/demo/`), README/HONESTY updated (Fabric App row).

Ask MIZAN (scene 13, 2026-11-16, owner request): guided questions over Gold in the Fabric App and the standalone page.
- No language model. A question matches one of 10 fixed intents (day status, variance, not assessed, settlement, sales,
  ZATCA rejections, ZATCA outcomes, payment-method fee rate, data quality, Ramadan); anything else is declined.
- Role picker (Finance / Tax / Data office / All staff) checked against the same tiers and groups as
  `mizan.ai.governed.GOLD_ACL` (test enforces parity); `fact_payment_method_daily` inherits the reconciliation ACL.
- Personal data (national ID, iqama, phone, email, names, IBAN) and write requests are refused before anything is read;
  forecasts are declined. Counters: role, blocked tiers, answers verified, declined.
- Evidence panel: Gold table, query file, fields, filters, source and as-of. In the Fabric App the host passes the exact
  DAX that ran (`window.MIZAN_DAX`, filtered with the bar); the standalone copy says it reads the export.
- Tests: tests/test_ask_mizan.py (ACL parity, routing of 20 questions incl. Arabic, refusals leak no SAR, every answer
  figure equals the Gold snapshot) via tests/ask_mizan_harness.cjs (node). Redeployed (`npx rayfin up staticapp deploy`).
- The Fabric Data Agent is still blocked by the trial capacity; Fabric Apps have no data-agent connector (connectors doc,
  2026-11-03), so a real agent chat cannot be embedded yet.

Ask MIZAN agent (2026-11-16, owner-approved: Azure OpenAI + Azure Function; ADR-012):
- Owner's personal Azure subscription (Default Directory; free credit expires 2026-12-14), signed in as the work
  user `mizan-admin@...onmicrosoft.com` (security defaults block CLI sign-in for the Gmail account; MFA set up).
  CLI profile: `AZURE_CONFIG_DIR=%USERPROFILE%\.azure-personal` (broker off).
- Created in `rg-mizan-agent` (UAE North): `aoai-mizan-41a4ca` (gpt-4.1-mini, GlobalStandard, 30K TPM, keys
  disabled), `func-mizan-agent-41a4ca` (Flex Consumption, Python 3.12, managed identity -> OpenAI User, CORS = app
  origin), `stmizanagent41a4ca`, budget `budget-mizan-5usd` (50/80/100% -> owners).
- Code: `apps/ask-agent/` (agent_core.py = governed step: role-filtered tools, pre-checks, number verification with
  one retry; function_app.py = HTTP + identity + rate limits). Browser side in command_center/template.html
  (AGENT_TOOLS run on live DAX via `window.MIZAN_AGENT.query`, agentVerify, Agent/Guided switch, plan + DAX in the
  evidence panel). Redeploy the Function: zip the 4 files in apps/ask-agent and
  `az functionapp deployment source config-zip --build-remote true` (see ADR-012).
- Tests: tests/test_ask_agent.py (fake model: entitlements, pre-checks, retry then block, sanitize; node harness:
  tools return Gold figures, role refusals, number check). Live end-to-end run: 7 questions incl. Arabic, a
  two-query chain (BNPL vs mada), role refusal, forecast decline; all answers verified.

Ask MIZAN redesign + glossary (2026-11-16, owner feedback):
- Section rebuilt chat-first: big headline, role switcher + Agent/Guided pill, welcome screen with role-aware starter
  cards, chat bubbles with badges, composer; right panel "How this answer was found" (numbered steps, DAX behind
  "Show DAX", agent failure reason in an amber box). Status strip and counter cards removed.
- New agent tool `explain_term` (curated glossary: MIZAN, ZATCA, mada, PDPL, settlement...; reads no data, open to all
  roles; MIZAN described honestly as a portfolio project with synthetic data). Prompt: role-to-topic map checked first,
  no clarifying questions about dates, off-topic declined. Badges: "no data used" / "glossary" instead of a verified
  badge when no data was read. Live re-test: ZATCA and MIZAN explained, weather declined, Arabic Data-office question
  answered "needs the Finance role", "not assessed" chained glossary + live query (112, SAR 1,125,184.70).

Wave 1 - first impression (2026-11-16, owner-approved):
- Hero: headline corrected to "Every assessed halala, reconciled. / Everything else, honestly flagged." (the old line
  claimed 112 pending merchant-days were checked), plus three proof cards (0.00 variance, 25,001 invoices / 0 chain
  breaks, 76/76 Gold columns) read live from the export.
- Equilibrium ring + "Press B" invite after the scales settle; 5-chapter recruiter tour with a bottom dock;
  jump-to-proof dock; "?" keyboard overlay; chaos bar (4 failure buttons naming what MIZAN catches and the test).
- ZATCA scene: 3-step crash slider showing the identical bytes either side of the crash (distinct_bytes = 1).
- Ask MIZAN: 4 gates light during planning, hover-a-number traces to its tool result, lock on refusal, "Show me on
  the page"; 16 recorded, number-verified agent runs (command_center/agent_runs.json) replay when the live agent is
  unreachable, so the assistant keeps working after the Azure credit expires 2026-12-14.
- Verified-build badge -> docs/PROOF_MANIFEST.md (13 claims, each with its proof file's SHA-256,
  scripts/build_proof_manifest.py). README hero rewritten around the three numbers.
- Agent bug: "hi" was answered in Arabic; prompt rule 8 now names English as the default and Arabic script as the
  only trigger (test_prompt_defaults_to_english_for_short_messages). Function redeployed and re-verified live.

Wave 2 - public page + ZATCA SDK (2026-11-16, owner-approved):
- Public snapshot site: scripts/build_public_site.py (refuses to build if the page contains an e-mail, the Function
  endpoint, a tenant domain or a secret) -> Azure Static Web App `swa-mizan-public` (Free, eastus2, in rg-mizan-agent).
  https://delightful-field-01a948c0f.4.azurestaticapps.net - no login. The rail footer now says "exported Gold
  snapshot" off-host instead of claiming live DAX.
- Smart App Control blocks DuckDB's unsigned `delta` extension on this machine, which broke the build and 15 tests.
  Fixed without weakening the machine: src/mizan/common/delta_snapshot.py replays the _delta_log and reads the
  current Parquet files with DuckDB's built-in reader. No new dependency; SAC stays on.
- ZATCA SDK 3.0.8 (LGPL v3, downloaded by hand, git-ignored under vendor/): scripts/validate_with_zatca_sdk.py runs
  it (finds Java in .tools, writes Configuration/config.json itself - the shipped install.bat runs `SETX PATH ""`
  and would wipe the user PATH, so it is never used). tests/test_zatca_sdk_validation.py skips when absent.
- Nine real defects the SDK found and we fixed: missing ds:SignedInfo (XSD); seller postal address (BR-08); 4-digit
  additional number (BR-KSA-64); TaxSubtotal VAT breakdown (BR-CO-18/15); second TaxTotal (BR-KSA-EN16931-09);
  UBLDocumentSignatures wrapper with both signature IDs (BR-KSA-28/29); QR timestamp needs the ISO "Z"; QR over the
  500-char cap, fixed with the bare EC point and fixed-width r||s (BR-CL-KSA-14); six item prices whose 15% VAT was
  not expressible in halalas (prices are now multiples of 0.20 SAR).
- Result: XSD and EN 16931 PASS. The two residual failures are defects in the SDK, reproduced in HONESTY.md:
  BR-KSA-50 compares line VAT in IEEE doubles (96.00 x 0.15 = 14.399999999999999) so it rejects our exact 14.40;
  and the QR stage is unsatisfiable because BR-KSA-68 + BR-KSA-EN16931-09 force two TaxTotal elements which the QR
  check then sums. Adding ds:SignedInfo changed 0 of 25,001 hashes (it lives inside UBLExtensions, which the digest
  excludes); the price change deliberately changed every money figure, so the pipeline was regenerated.

Follow one riyal (2026-11-18, owner request): press T, or "Follow one riyal" in the command palette.
- One real capture followed through four systems, side by side with the keys that join them: till capture
  PE-0014375 (ORD-0018737, MID100044, MASTERCARD, SAR 898.38, 2026-02-28 11:06:28 Asia/Riyadh) -> ZATCA invoice
  df824688-9c99-438b-9db2-6e19bf33e917 (ICV 2724, EGS-02, REPORTING, REPORTED, hash + PIH shown) -> bank line
  STL-20260301-NAJDACQ (gross 898.38 - MDR 17.52 - VAT on fee 2.63 = net 878.23, fees taken from the bank file,
  never recomputed) -> GL document 1900001962 (CARD_CLEARING SAR 2,632.35, 4 lines).
- Chosen by rule, and the panel says the rule: largest PAID_BANK card capture between SAR 300 and 900, ordered by
  payment_event_id. Nobody has to trust that a flattering row was hand-picked; re-running the query reproduces it.
- Honest about grain: capture, invoice and bank line join on exact keys (payment_event_id, invoice_uuid), but the
  ERP posts one journal per merchant-day, so the panel states this sale is part of that posting, not the whole of
  it, rather than implying a 1:1 GL line.
- scripts/build_command_center.py gains trace_section() (reads slv.payment_lifecycle, slv.settlement_lines,
  slv.zatca_invoice_documents and slv.erp_gl_journal_lines through delta_rel); riyalJourney() in template.html
  falls back to the old per-riyal averages if no trace is exported. Ships in the Fabric App and the public page.

Open mirroring (2026-11-19, owner request; ADR-014):
- `MR_MIZAN` (MirroredDatabase, created through the REST API) mirrors `erp.merchant_master` from a real
  OneLake landing zone. `scripts/fabric_open_mirror.py` has create / seed / change / verify / status / reset.
- Proven against the live workspace, not described: 121-row initial load with no `__rowMarker__` ingested
  ("Replicating", 121 rows), then an incremental batch of one UPDATE, one DELETE and one INSERT applied in
  order. `verify` reads the table back over its SQL endpoint with a service-principal access token:
  121 rows, MID100044 register count 4 -> 6, MID100120 gone, MID100121 present in Abha. Fabric applied the
  delete with a Delta deletion vector.
- **Gold still reads the dbt seed, not the mirror.** Pointing dbt at a mirrored database would make the
  models depend on a Fabric-only feature and stop them building on DuckDB locally and in CI; "the same
  models run locally and on Fabric" is worth more. Stated in ADR-014 and HONESTY row 16.
- One real constraint, found by hitting it: DuckDB writes a Parquet column as REQUIRED when the data it is
  given has no nulls, so the initial load produced a non-nullable schema. A delete row padded with nulls --
  which the format explicitly permits, since only key columns are required -- then arrives as nullable, and
  Fabric rejects the batch with `SchemaMergeFailure` and **stops replicating that table** with nothing in
  the pipeline to surface it. Every CDC row now carries every column; `reset` recreates the table folder,
  which is the documented way to restart one table.
- tests/test_open_mirroring.py (9): 20-digit continuous file names that sort numerically, keyColumns
  declared and unique in the source, `__rowMarker__` last or raise, the initial load carrying no marker,
  and every CDC row carrying every column. The landing-zone contract fails silently, so it is pinned.

Card-scheme dispute monitoring (2026-11-19, owner-approved Gold addition):
- `gld.fact_merchant_dispute_monitor` (grain: merchant_id over the dataset window) from `slv.payment_lifecycle`
  alone -- CAPTURE, REFUND and CHARGEBACK are already native event types, so no new source, seed or column.
  Chosen over impossible-travel and IBAN ring detection after research: this is the control an acquiring and
  settlement platform actually runs, and unlike the other two the finding is already in the data rather than
  planted.
- The model's point is the **count floor**, not the ratio. On this data the ratio alone flags 71 of 121
  merchants (59% of the portfolio -- not a control, a noise generator), because a merchant with 43 captures and
  3 disputes reads 6.98%. Requiring a minimum dispute count as well, which is why the real programmes have one,
  flags 1: MID900001, 200 disputes on 10,530 captures, 1.90%, SAR 319,280.25 taken back. `breaches_ratio`,
  `meets_count_floor` and `in_monitoring_programme` are all exported so the difference is shown, not claimed.
- Thresholds are dbt vars (1.5%, 100 disputes) read from secondary industry sources, **not** the Visa or
  Mastercard rulebooks, and the window is the dataset's 20-day span, not a calendar month. Both caveats are on
  screen and in HONESTY row 17; no scheme or regulator clause is cited.
- Tests: dbt `assert_dispute_floor_suppresses_small_merchants` fails if the floor ever stops suppressing anything
  (the way this model would rot silently), plus `no_float_columns`, uniqueness and not-null; and
  tests/test_dispute_monitor.py (7) pins the exported figures the panel shows, including that the window is
  declared and the note does not claim the thresholds are authoritative.
- The column-lineage guard caught the addition immediately (14 derived columns with no same-named source), which
  is what it is for; `dbt/lineage_overrides.json` now maps each to its real inputs. Gold lineage is 91/91.
- Shown on the Risk stream scene as a 71-versus-1 panel with three suppressed examples.

Making the dispute monitor visible (2026-11-19, owner feedback: "backend doesn't mean done"):
- Fair hit, twice over. In the Command Center the panel was built but sat at the BOTTOM of scene 08 below a
  chart -- built and buried is invisible. Moved to the top of the Risk stream scene; the scene heading and the
  sidebar caption now lead with it instead of only mentioning the KQL rules.
- In Power BI there was nothing at all. New **Merchant Risk** page (11 visuals): six cards, a scatter of
  dispute ratio vs capture volume, a portfolio gauge, disputes by merchant, a programme slicer and the full
  per-merchant table with both tests shown as separate columns. Scatter rather than bars on purpose -- the
  argument is that a ratio means nothing without volume, and only two axes show a 6.98% ratio sitting on 43
  captures.
- `gld.fact_merchant_dispute_monitor` is now built on **WH_MIZAN** (`dbt build --target fabric`, 10/10 PASS) and
  verified through the SQL endpoint: 121 rows, 71 ratio-only, 1 in programme, MID900001 -- identical to local.
  Semantic model and report redeployed.
- Three bugs that only a real Fabric build could surface:
  1. the model did not run on Fabric at all -- `DATE_DIFF` is DuckDB syntax, T-SQL wants `DATEDIFF`. New
     `date_diff_days()` macro, same pattern as `bool_true()`.
  2. the dbt test did not run on Fabric either, twice: dbt wraps a test in a derived table and T-SQL rejects a
     `WITH` clause inside one ("Invalid object name 'm'"), then `GROUP BY 'x'` turned out to be a DuckDB-ism.
     Rewritten with a repeated ref() and `HAVING` with no `GROUP BY`; builds on both targets.
  3. `test_cards_respond_to_their_own_page_slicer` caught six cards that would have ignored their own page
     slicer -- the same defect found once before on the payments page. The new measures were homed on the recon
     table; moved onto the dispute table.
- The non-ascii guard caught a raw em dash typed into fabric_powerbi.py; escaped. CI now lints `scripts` too.
- 302 passed, dbt 91/91 local and 10/10 on Fabric for the new model.

## Left for the owner after Phase 13
0a. ~~Public snapshot site not deployed~~ DONE 2026-11-19: https://delightful-field-01a948c0f.4.azurestaticapps.net
   (no login, serves "follow one riyal", verified HTTP 200 + content). Redeploy after any rebuild with
   `scripts/build_public_site.py` then the SWA CLI; `az login` needs interactive MFA on this tenant, so the owner
   signs in first.
0b. **The private claude.ai artifact copy is retired.** https://claude.ai/artifact/HeSui14YJRiTUwiFDAkXqD lives on
   the owner's previous Claude account; this machine is signed in to a different one, so it reads "not found" here
   and can no longer be updated. It was NOT republished to a new URL. The public Static Web App above replaces it
   and is strictly better: no account needed to view, and it redeploys from a script. ADR-011 recorded the artifact
   as the chosen hosting; that choice is superseded, the front end itself is unchanged.
0c. ~~Workspace task flow~~ DONE 2026-11-19: six tasks, all eleven items assigned (PORTAL_STEPS.md section 4).
0. **Re-run the pipeline on the Fabric tenant** so `docs/artifacts/10_fabric_run_evidence.json` matches the
   corrected prices (it still records the 2026-11-14 run: gross SAR 22,390,730.16 vs SAR 22,391,236.23 locally).
   The dbt 65/65 PASS result is unaffected; only the money figures are from the earlier dataset. See HONESTY.md.
   Also `data/lake.stale/` (135 MB, the pre-rebuild lake) can be deleted once you are happy with the new one.
1. Record the video from the shot list; save as docs/linkedin/demo.mp4 (or link it).
2. Capture the 8 demo screenshots into docs/artifacts/demo/ with the README file names (green "Live" label visible).
3. Optional: profile photo -> apps/command-center/public/profile.jpg and "photo": "profile.jpg" in config/profile.json,
   then `python scripts/build_command_center.py` and `npx rayfin up staticapp deploy`.
4. DONE 2026-11-15 (owner approved): gld.fact_payment_method_daily + payment-method cards and Method filter
   (dbt test reconciles it to the recon per MID-day; built on DuckDB and WH_MIZAN; in the semantic model; live DAX).
5. Have a native Arabic speaker review the Arabic headings before posting.
6. Sharing the app: give viewers "Run and interact" on the app item and Build on "MIZAN Control Tower Model".

## Open issues

1. 2026-11-14: installed via winget — GitHub CLI 2.104, WSL2 (`wsl --install --no-distribution`), Docker Desktop
   4.99, Azure CLI 2.92. **Windows reboot was pending** after WSL2.
2. GitHub: signed in as Shaadink (2026-11-14); repo-local identity `Shadin K <207139190+Shaadink@users.noreply.github.com>`;
   `gh auth setup-git` done. Commit authors rewritten before the first push.

## Left for the owner (everything else is done)

1. ~~Eventstream -> Eventhouse delivery~~ DONE 2026-11-15 (see Phase 10).
2. **Fabric Data Agent** (optional, needs a paid F2+ capacity): docs/PORTAL_STEPS.md section 2. Not possible on the trial.
   Ask MIZAN now has its own governed agent (ADR-012); its Azure credit expires 2026-12-14 (then guided mode only,
   unless the subscription is upgraded). Delete everything with `az group delete -n rg-mizan-agent`.
3. **Optional polish**: restyle the generated Power BI report in the portal; record the 60-second GIF / walkthrough video
   (spec Day 10) from the portal.
4. **Housekeeping**: the Fabric trial ends after 60 days and lives in the college tenant (can be disabled by the
   college); rebuild anywhere with the four `scripts/fabric_*.py` scripts. Rotate the service principal secret (1 year).
   Stop Docker when not demoing: `docker compose -f docker/docker-compose.airflow.yml down`.

## 2026-11-19 — External review round: packaging fixes, measured scale boundary, chain-head guard test

The blueprint went out to six AI reviewers. One reviewed a different project entirely (a Flask/ChromaDB app)
and was discarded; the other five converged, and their verified findings were acted on here. Findings that
turned out to be wrong are recorded too, because the fact that several reviewers independently *suspected* a
bug is itself a defect in the documentation.

**The repository is now public** (it returned 404 to anyone unauthenticated, which two reviewers hit). Checked
first that no `.env`, key or credential file is tracked and that no secret-shaped string appears in tracked
content; the only matches were a `...` placeholder in `docs/STREAMING.md` and `c2VjcmV0` (base64 "secret") in a
test fixture.

**Front page.** The live Command Center URL is now in the first five lines of `README.md` (it appeared in no
`.md` file a stranger would open). The eight broken screenshot placeholders are replaced by the same content as
text. `76 / 76` corrected to `91 / 91` in `README.md` and `docs/ONE_PAGER.md` -- the stale figure sat in both
headline tables while `ONE_PAGER.md:47` already said 91/91. `ADR-001...013` -> `...014`. The stale Fabric figure
at `README.md:137` now carries the live figure and the HONESTY pointer in the same cell. The 20M benchmark is
labelled a local Spark benchmark where the number appears, not only in HONESTY.

**Numbers that invited the wrong question.** The merchant-day denominator is stated: 121 merchants x 20 days =
2,420 possible = 2,233 with activity (2,121 assessed + 112 in transit) + 187 with no trading. "25,001 in an
unbroken chain" is five chains (EGS-01..05), now said. CRM 5,000 = 4,000 party records + 1,000 address
observations, and MDM's 3,985 = 4,000 minus the 15 quarantined `?????` rows.

**Per-phase test counts removed from the blueprint.** They were carried forward by hand rather than counted, and
it showed: two consecutive pairs were identical and one phase appeared to reduce the suite. PROGRESS records
only 133, 140, 177, 220, 302, so the per-phase figures are gone rather than guessed.

**Settlement date documented, not changed.** Four reviewers independently assumed the recon joined on the bank
file's arrival date. It does not -- it keys on `settlement_for_date_ksa`, the originating capture date the bank
line pays for -- but nothing said so. Now in the model header and the blueprint, along with the two things the
model does *not* do: an independent bank value date (scheme, MCC and the Fri/Sat KSA weekend), and cross-period
chargeback matching to the original capture.

**ADR-008 now carries a measurement instead of an argument.** `scripts/bench_adapter.py` (new): ~170,000
fields/sec combined HMAC + AES-256-GCM, which at 3 to 7 PII columns per row is 24,000-57,000 rows/sec, or
90M-200M rows/hour on one core. The adapter is not the bottleneck at this volume; driver *memory* binds first,
because staged rows accumulate in a list. Migration path recorded in order, naming which step gives up the
property the ADR exists to protect (`mapPartitions` puts per-subject DEKs in executor memory).

**A reviewer's cryptographic worry, checked and answered:** if the generator is byte-deterministic, are the
AES-GCM nonces deterministic too? They are not -- `secrets.token_bytes(12)` per field, AAD `token|column`.
Determinism is a property of the generator, never of the ciphertext. Recorded in the blueprint because it is
the right question to ask.

**Spark skew reframed, because the benchmark does not say what the section implied.** AQE skew-join (15.52 s)
beat the hand-written 16-bucket salt (17.62 s). That is now stated outright, with the real reasons to have
written the salt anyway: it is what remains when AQE cannot split a partition (stream-to-static joins, skewed
pre-shuffle aggregations), and implementing it is how you learn why the built-in wins. Also flagged: the skew
ratios are `max/median` task duration measured on different stages with 64 tasks vs 5, so they are not
comparable and should not be quoted as a result until the harness is rerun on matched stages.

**Chain-head guard test (new, `test_zatca_chaos.py`).** Reviewers said the per-EGS sequencer was a read-then-write
that would fork the chain across two worker processes. Half right. `commit_signed` already does compare-and-set
-- it re-reads the head and raises `single-writer violated` if it moved -- but nothing proved the refusal fires,
because the eight-lane test is eight threads sharing one store and can only exercise the happy path. The new
test simulates the lost race by advancing the head out of band and asserts the stale write is refused and
nothing is written. **Verified to fail when the guard is removed**, then the guard restored. The remaining gap
is narrower than the reviewers thought and is now HONESTY row 18: the CAS logic is right, but it runs over a
Python dict, and a multi-worker deployment needs it in a transactional store.

**Framing.** The duration ("over roughly one week") is deleted rather than replaced -- three reviewers suggested
claiming three to four months instead, which would be a false claim in the same document as HONESTY.md. The
attribution stays: AI-assisted development throughout, with decisions in `docs/adr/` and claims bound to tests.
"Portfolio project for a Data Analyst moving into Data Engineering" and the trial countdown are gone; what
replaces the countdown is the reproducibility statement, which is the part that matters.

Tests: 303 passed (302 + the new guard test), ruff clean on `src tests scripts`. The non-ascii guard caught
`scripts/bench_adapter.py` -- the Write tool had turned its `\uXXXX` Arabic escapes into raw characters, exactly
the failure mode CLAUDE.md warns about; `escape_non_ascii.py src tests scripts` fixed it.

Still open and owner-only: the Fabric re-run (kills HONESTY #5 and #6 and the 65-vs-91 dbt gap), the ZATCA SDK
minimal repro, the eight screenshots, the video, and a measured FinOps/residency note. Still open and buildable:
a reconciliation fault-injection test (the answer to "your generator and your reconciler share the same rules,
so SAR 0.00 holds by construction" -- the one criticism that cannot be argued away), pairwise precision/recall
for the MDM ladder against generator ground truth, and a check of whether HTTP 409 belongs in the retry-forever
set or should reconcile as already-accepted.

## 2026-11-19 (evening) — Fabric re-run, and the three defects it exposed

The Fabric tenant had not been re-run since 2026-11-14, so its Gold disagreed with local Gold by SAR 506.07
and its `dbt build --target fabric` stood at 65 tests against the local 91. Re-running it closed both, and
cost three defects on the way -- all three found by the project's own guards rather than by reading code.

**1. A corrected re-send doubled the ZATCA documents in Silver** (`9b68374`, HONESTY row 26). Six item prices
had changed locally, so all 25,000 ZATCA requests re-landed as corrections and Bronze -- append-only by design
-- held two versions of each. `zatca_land` joined `ctl.invoice_outbox` to `brz.zatca_invoices_raw` on
`request_id`, matched both, and fanned every outbox row into two: `slv.zatca_invoice_documents` reached 50,002
rows and `invoice_uuid` stopped being unique. dbt's `source_unique` test failed and **refused to publish Gold**.
Every other Bronze reader already went through `_latest()`; this one did not. Fixed, and pinned by
`test_a_corrected_zatca_resend_does_not_double_the_silver_documents`, verified to fail without the fix. Why no
test caught it first: the existing replay test re-runs the *same bytes*, so Bronze dedup drops everything.
Idempotency on identical input was proven; idempotency on corrected input was not, and those are different
claims. Fabric then reached **91/91**, full parity with local, gross SAR 22,391,236.23, both variances 0.00.

**2. The signed ZATCA chain never received the price correction** (`9381dde`, HONESTY row 29, **still open**).
CI caught the live DAX results disagreeing with exported Gold on ZATCA money only -- SAR 30,919,828.86 against
30,920,225.04 -- while every count, state, ICV and flow matched. That is `run_zatca` behaving correctly: it
skips every `request_id` already in the outbox, so a signed invoice is never re-priced, and the Fabric figure
is exactly the local total from before the correction. The gap it exposes is real: correcting a price moved
Silver, Gold and the bank reconciliation and left the tax ledger on the old amount **with no credit note
raised**. The model supports corrections as new documents; nothing routes an upstream price change into one.
Closing it is new behaviour in the clearance engine, so it is the owner's call, not a patch.

**3. The QR guard had drifted from the engine it guards** (`6709904`, HONESTY row 25). The 500-character cap
test failed about one run in four and had been logged as unexplained. It built the QR fields itself and still
used raw signature bytes, a DER public key and a DER certificate signature after the engine had moved to
base64 tag 7, the bare EC point and raw r||s. Measured over 5,000 signatures: the stale shape breaches at
**1,236 / 5,000 (24.7%)**, always at 504 when the ECDSA signature DER-encodes to 72 bytes; the shipped
encoding tops out at **496**. Both now go through one `build_invoice_qr`. The ledger keeps the correction that
"3,000 probes never exceeded 500" was not evidence -- those probes shared the stale shape's assumptions.

**Also fixed: the local Fabric App test runner** (HONESTY row 28), which had been written off as a corrupted
install. Vite evaluated spec files under `file:///D:/...` while the vitest CLI, started from a shell whose
working directory read `d:\`, loaded its own modules under `file:///d:/...`; Node loads those as different
modules, so `@vitest/runner` was loaded twice and every `describe()` reached a runner that was never
registered. `src/test/setup.ts` now turns that into the instruction. From `D:\` the app suite runs clean.

**State:** 331 Python tests, 183 app tests (1 skipped), ruff clean, dbt 91/91 on DuckDB and on Fabric, and
**all three CI jobs green** on `6709904` -- the first fully green run since 2026-11-15.

Still owner-only: HONESTY row 29 (credit note on price correction -- a decision, not a task), the eight README
screenshots, the 2:30 video, a native Arabic read of the headings, the ZATCA SDK sample-invoice repro, measured
FinOps CU figures, and the AF_MIZAN Airflow job, which remains an unopened experiment.

## 2026-11-20 — AF_MIZAN: the schedule moves into Fabric

The nightly schedule lived in Docker on the owner's laptop, so it only existed while the laptop was on.
Fabric can host Airflow itself (the portal calls it an **Apache Airflow job**, formerly **Data workflows**),
and `AF_MIZAN` now does.

**Built.** `dags/mizan_fabric_daily.py` runs the six lakehouse jobs -- bronze_land, silver_build, mdm_resolve,
zatca_chain, then ai_index and ndmo_catalog in parallel -- over the Fabric REST API, at 03:00 Asia/Riyadh,
one run at a time. It imports **nothing but the standard library and Airflow**, so there is no requirements
install that can fail inside a worker nobody can debug, and `tests/test_fabric_airflow_dag.py` fails the build
if an import ever creeps in. It sits in a top-level `dags/` folder because that is where Fabric looks.

It is **not** a port of the Docker DAG. Microsoft states that private networks are not supported for Airflow
jobs, so Marquez on a laptop is unreachable; the freshness gate, residency gate, dbt build and OpenLineage
stay in `airflow/dags/mizan_daily.py`. Both files say so at the top rather than leaving a reader to notice
the gates are missing.

**Deployed, by API rather than by clicking.** `scripts/fabric_airflow.py` creates the item, uploads the DAG,
and reports status. Run on 2026-11-20: item `f6f1fec2`, DAG 9,630 bytes, environment `Started`, all read back
to confirm. That settles an open question -- the FTL64 capacity does support Airflow jobs. Git sync is
deliberately unused: Microsoft documents no REST surface for it, and uploading from the repository keeps the
deployment to one command without giving Fabric a GitHub credential.

**One documented API does not work** (HONESTY row 31): `environment/updateSettings` answers 401 "does not have
Write permissions" to the same service principal that had just created the item and uploaded a file through
the sibling beta API, and its GET answers 500. Both reproduce. The workaround is better anyway -- the DAG
reads an Airflow Variable first, and Airflow masks any variable named `*secret*`, while that API returns
stored values in plain text. The client secret was never going to be sent through it.

**Still owner-only, and the honest limit** (HONESTY row 30): six Airflow Variables and one Trigger DAG click.
Until that happens nothing has actually run in Fabric's Airflow, and the Docker DAG remains the only one that
has. `docs/FABRIC_AIRFLOW.md` is the walkthrough.

**Also:** `scripts/render_dag_graph.py` draws `docs/artifacts/06_fabric_airflow_dag.svg` from the DAG's own
`edges()` and the recorded run timings, with a test that re-renders and fails if the committed picture drifts.
It labels itself "not a screenshot", because `06_airflow_dag.png` is evidence of a run and a diagram is only
an explanation of a shape. Drawing it caught a stale 16m 19s in the new doc; the real total is 19m 23s.

**Presentation:** the "Synthetic data" caption is gone from the Command Center rail and footer, and the
capacity panel no longer says "trial" (`Fabric FTL64, UAE North`, `not metered on this capacity`). The word
stays in README, HONESTY and BLUEPRINT, where it is the stated reason no cost figure is claimed.

Tests: **341 passed**, ruff clean on `src tests scripts dags`, 183 app tests. CI now lints `dags/` too.

## 2026-11-20 (afternoon) — AF_MIZAN runs the whole pipeline

A triggered run of `mizan_fabric_daily` completed all six jobs in **15 minutes**: bronze_land 7m09s, then
silver_build, mdm_resolve, zatca_chain, and ai_index with ndmo_catalog in parallel (both started 14:02:22).
Confirmed from both sides -- Airflow's task list, and the Fabric notebook job instances showing six
`Completed` runs submitted by the DAG rather than by hand. HONESTY row 30 moves to Fixed.

The first attempt failed in four seconds: `AADSTS7000215: Invalid client secret provided`. The value in
`.env` was correct and a clipboard round-trip was byte-identical to it, so the wrong value had been stored in
the Airflow Variable; re-entering it fixed the run. Worth recording because it exercised the error path --
the log named the step, the app registration and the cause, in one read, which is what the DAG's failure
handling was written for.

Still true and still stated: the job runs on Fabric's starter pool, which pauses when idle, so the 03:00
schedule is not dependable until an always-on custom pool is chosen, and that bills capacity continuously.

`docs/linkedin/VIDEO_SHOT_LIST.md` now opens on the orchestrator rather than the data -- the Airflow Graph at
0:06-0:15, because "it runs itself in the cloud" is the claim most portfolio projects cannot make. It also
had a stale `PASS=65` where the Fabric target now stands at 91.

## 2026-11-20 (late) — closing the production gaps that can be closed

An external review of the blueprint made the point that "production" in regulated payments is mostly the
things that are not code, and that almost none of them existed here. It was right. Four of its seven gaps are
now closed or materially narrowed; three cannot be closed by writing code and are stated instead.

**The operational layer** (HONESTY row 33). `src/mizan/orchestration/oncall.py` turns a failure into an alert
that names the step, the run, the git SHA and the runbook heading that answers it, with severity by blast
radius -- the money path pages, the AI index and the NDMO catalogue raise a ticket, because a pager that fires
for a stale search index is a pager people learn to ignore. Wired into both DAGs. Alerting never raises: a
webhook that is down must not turn a failed task into a crashed one, and the task log is the delivery that
cannot fail.

`docs/RUNBOOKS.md` covers the ten failures that actually happen, including the two that must **not** be met by
re-running -- a uniqueness failure (re-running reproduces it) and a ZATCA unknown outcome (never re-sign,
never re-UUID). A test fails the build if an alert ever points at a heading that does not exist, because a
dead link at 03:00 costs the time it was meant to save.

The close now has a stated deadline, 06:00 Asia/Riyadh, a task that measures it and reports a breach without
failing the run, and timezone handling with a test -- 03:30 UTC is 06:30 Riyadh, and comparing raw clocks
would call a late close three hours early.

`scripts/backfill.py` is the tested re-run procedure. It deliberately does not re-run a date range, because
this pipeline has no date-range rebuild and inventing one would add the question that is easiest to get wrong
under pressure. It fingerprints Gold, rebuilds, fingerprints again, and fails if anything moved that should
not have. Run: **10/10 Gold tables identical**. A tripped circuit breaker is reported as a correct outcome
with its runbook, not as a tool failure.

**Caller authentication** (HONESTY row 15, rewritten). The Function could not verify its caller; now it can
and does not, which is a different claim. `apps/ask-agent/entra_auth.py` validates an Entra access token end
to end -- RS256 against the tenant's published keys, issuer, audience, directory, expiry, with two minutes of
skew -- in about 120 lines and **no new dependency**, because `cryptography` is already here for ZATCA
signing and adding a library to a security boundary is a decision rather than a default. Sixteen tests attack
it, each removing one protection: unsigned, foreign key, payload edited after signing, Graph audience, another
directory, expired, not yet valid, rotated key id. Rate limiting keys on the verified object id rather than a
forwardable IP. It ships behind `REQUIRE_ENTRA_AUTH=0` and fails closed if the flag is set without a tenant
configured, because "authentication required" must never silently become "authentication skipped".

**The compliance pack** (HONESTY row 34). `docs/compliance/DPIA.md`: purpose, lawful basis, minimisation with
the test behind each claim, the PDPL-versus-tax retention conflict and how crypto-shredding resolves it,
cross-border transfer, subject rights, and nine ranked residual risks. Three are High and open -- residency
declared KSA against a capacity in UAE North, the agent API shipping unauthenticated, and no legal review.
`tests/test_compliance_docs.py` pins the claims most likely to drift optimistic.

**Not done, and why.** Incremental Gold models would close the scale gap and would also break a frozen
decision (Gold materialised as tables, spec rule 3), so that is the owner's call, not a refactor to slip in.
Real data, live ZATCA onboarding, a lawyer's review and a second engineer cannot be supplied by code at all.

Tests: 4 new files, 48 new tests.

## 2026-11-20 (night) — right of access, and three bugs found by running it

The DPIA written earlier the same day listed four of six PDPL subject rights as absent. Two are now built:
`src/mizan/privacy/access.py` and `scripts/subject_access.py` answer a right-of-access or portability
request, reusing the same subject resolution erasure uses so every linked Arabic spelling is found.

**The case that matters is the interaction with erasure.** An erased subject returns `ERASED` with the
tombstone and nothing else. Reassembling a shredded person from the rows erasure left behind would quietly
undo the stronger right in the name of the weaker one; the test asserts their Arabic name appears nowhere in
the report. Portability deliberately excludes the golden record: how two records were decided to be one
person is our processing, not the subject's data, and disclosing it would leak the other spellings matched.

Access is treated as the dangerous right it is -- it creates a cleartext copy of personal data outside every
control that protects it at rest. The tool prints a summary by default and writes a file only when asked;
`docs/RUNBOOKS.md#answering-a-right-of-access-request` requires authenticating the requester first and
destroying the file after delivery.

**Three real bugs, all found by running against the real lake, all mine.**

1. The source map claimed `brz.payment_events_raw` holds a subject token. It does not -- payments carry no
   customer reference and reach a person only through an order. Had it passed, every access request would
   have silently under-disclosed. The map is now derived from the Bronze contracts rather than assumed.
2. Bronze writes PII to `<column>_enc` but binds the ciphertext to the **plain** name, so the stored column
   and the associated data are different strings. Conflating them fails authentication rather than returning
   wrong plaintext, which is the right way round, but it would have failed on every field.
3. The golden record encrypts the Arabic and English names under **different source tokens** -- MDM picks
   the best Arabic name from one member record and the best English name from another, and each stays under
   the token it came from. One row therefore holds two subjects' ciphertext, and decrypting both with one
   key authenticates for neither. Keys are now resolved per column, and a column whose key has been shredded
   is dropped and named rather than returned as ciphertext labelled as somebody's name.

The honest lesson is about order of work, not about the tests: this was written from assumptions about the
schema instead of from reading what Bronze and MDM actually write, and the tests paid for that in four
eleven-minute runs. They caught all three, against the real lake, which is the only reason it is not
shipping as a privacy feature that quietly returns nothing useful.

Also added: `docs/RUNBOOKS.md` sections for answering an access request and for a personal data breach
(DPIA residual risk 8 -- the procedure now exists; the detection, the template and the escalation contact
still do not, and the section says so).

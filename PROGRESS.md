# PROGRESS.md

Read this first every session. Resume from the first phase that is not DONE.

| Phase | Name | Status | Tests (cumulative) |
|-------|------|--------|--------------------|
| 0 | Scaffold | DONE | 7 |
| 1 | Deterministic generator | DONE | 48 |
| 2 | ZATCA engine (M1-2) | TODO | |
| 3 | Bronze + Silver (PySpark) | TODO — needs Java (ask owner) | |
| 4 | Gold (dbt) | TODO | |
| 5 | MDM (M4) | TODO | |
| 6 | PDPL + NDMO (M5-6) | TODO | |
| 7 | Skew (M7) | TODO — needs Docker | |
| 8 | Orchestration | TODO — needs Docker | |
| 9 | Governed AI (M8) | TODO | |
| 10 | Fabric deployment | TODO — needs tenant credentials in .env | |
| 11 | Packaging | TODO | |

## Environment (checked 2026-11-13)

- Windows 11, Python 3.12.10, project venv `.venv` (call `.\.venv\Scripts\python.exe` directly).
- git 2.56. Repo-local author is a **placeholder** (`MIZAN Builder <mizan@localhost>`): the owner will supply
  their GitHub noreply identity; rewrite all commit authors before any push (no remote exists yet).
- **Java: not installed. Docker: not installed.**

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

## Open issues

1. Java (Phase 3 local PySpark) and Docker (Phases 7-8) are global installs: ask owner.
2. Owner to supply GitHub noreply identity; then rewrite commit authors.

## Next step

Phase 2: ZATCA engine (Modules 1-2) — pure Python, needs `lxml` + `cryptography` in the venv.

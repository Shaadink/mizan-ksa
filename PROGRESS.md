# PROGRESS.md

Read this first every session. Resume from the first phase that is not DONE.

| Phase | Name | Status | Tests (cumulative) |
|-------|------|--------|--------------------|
| 0 | Scaffold | DONE | 7 |
| 1 | Deterministic generator | TODO | |
| 2 | ZATCA engine (M1-2) | TODO | |
| 3 | Bronze + Silver (PySpark) | TODO | |
| 4 | Gold (dbt) | TODO | |
| 5 | MDM (M4) | TODO | |
| 6 | PDPL + NDMO (M5-6) | TODO | |
| 7 | Skew (M7) | TODO | |
| 8 | Orchestration | TODO | |
| 9 | Governed AI (M8) | TODO | |
| 10 | Fabric deployment | TODO | |
| 11 | Packaging | TODO | |

## Environment (checked 2026-11-13)

- Windows 11, Python 3.12.10, project venv `.venv` (call `.\.venv\Scripts\python.exe` directly).
- git 2.56 available. **Java: not installed. Docker: not installed.**

## Phase 0 — Scaffold (DONE)

Built: `pyproject.toml` (src layout, dev extras pytest/hypothesis/ruff/duckdb), `.gitignore` (.env, generated
data, spec PDF), `.env.example`, `CLAUDE.md`, `README.md`, `HONESTY.md`, `invariants.md` (I-01..I-14),
`docs/adr/ADR-001..006`, `src/mizan/__init__.py` (frozen namespaces), `tests/test_scaffold.py`.

Tests: 7 passed. Ruff: clean.

## Open issues

1. **Java** is required for local PySpark (Phase 3) and **Docker** for the Spark benchmark / Airflow
   (Phases 7-8). Both are global installs: ask the owner before Phase 3.
2. The spec names 6 of the "12 planted defects" explicitly (Day 1 row); the other 6 are taken from
   Section 9 artifact descriptions. The full list is fixed in Phase 1's `defect_manifest.json`.

## Next step

Phase 1: deterministic generator.

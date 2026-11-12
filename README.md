# MIZAN-KSA — Saudi Regulated Commerce & Payments Data Integrity Platform

*MIZAN* (Arabic: "the balance / the scales").

MIZAN-KSA follows one commercial transaction from order capture through a ZATCA Phase-2 e-invoice, mada/SADAD
T+1 bank settlement and an ACDOCA-shaped ERP general ledger. Every halala (0.01 SAR) reconciles, every invoice
chain stays intact through transport failures, and every customer's PII is encrypted at landing and erasable
under PDPL without touching signed tax evidence.

> Status: under construction — see [PROGRESS.md](PROGRESS.md). The six proof artifacts will be embedded here.

## Stack

Microsoft Fabric (OneLake Delta `LH_MIZAN`, PySpark, Warehouse `WH_MIZAN`, Direct Lake) as the data plane;
Apache Airflow, dbt-fabric, OpenLineage + Marquez, pytest, Docker and GitHub Actions as the control plane.

## Layout

| Path | Contents |
|------|----------|
| `src/mizan/` | Python package (generator, ZATCA engine, Bronze/Silver, MDM, PDPL, skew, AI) |
| `tests/` | pytest suite — one test per invariant (see [invariants.md](invariants.md)) |
| `docs/adr/` | Architecture Decision Records |
| `HONESTY.md` | What the project does and does not claim |

## Local setup (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
```

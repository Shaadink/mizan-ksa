r"""Write docs/artifacts/10_fabric_run_evidence.json from the live tenant, instead of by hand.

    .\.venv\Scripts\python.exe scripts\fabric_evidence.py --run-date 2026-11-21 --note "..."

**Why this exists.** Every other figure in this project is derived and never typed -- that rule has its own
test (`tests/test_doc_facts_sync.py`). The Fabric evidence file was the exception: it was maintained by
hand, and it is the file the Command Center, the README and the video all read for "what happened on
Fabric". A hand-kept number in the one document that describes a cloud run is the number most likely to
drift from the cloud, and it did: it sat at the 2026-11-14 figures for five days while the tenant moved on.

Everything here is read back over the SQL endpoints with the service principal. Nothing is passed in except
the run date, the note, and the per-step timings, which only the run itself knows.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mizan.privacy.crypto import load_dotenv  # noqa: E402

ART = REPO / "docs" / "artifacts"


def _conn(database: str):
    import pyodbc
    e = os.environ
    return pyodbc.connect(
        f"Driver={{ODBC Driver 18 for SQL Server}};Server={e['FABRIC_SQL_ENDPOINT']},1433;Database={database};"
        f"Authentication=ActiveDirectoryServicePrincipal;UID={e['FABRIC_CLIENT_ID']};"
        f"PWD={e['FABRIC_CLIENT_SECRET']};Encrypt=yes", timeout=180)


def _one(cur, sql: str):
    row = cur.execute(sql).fetchone()
    return row[0] if row else None


def warehouse_facts() -> dict:
    """Gold, read back over WH_MIZAN. Money as text, never float (CLAUDE.md)."""
    con = _conn("WH_MIZAN")
    cur = con.cursor()
    try:
        recon = {
            "rows": _one(cur, "SELECT COUNT(*) FROM gld.fact_merchant_settlement_recon"),
            "merchants": _one(cur, "SELECT COUNT(DISTINCT merchant_id) FROM gld.fact_merchant_settlement_recon"),
            "gross_captures_sar": str(_one(
                cur, "SELECT CAST(SUM(gross_captures_sar) AS DECIMAL(18,2)) FROM gld.fact_merchant_settlement_recon")),
            "bank_paid_sar": str(_one(
                cur, "SELECT CAST(SUM(bank_paid_sar) AS DECIMAL(18,2)) FROM gld.fact_merchant_settlement_recon")),
            "in_transit_sar": str(_one(
                cur, "SELECT CAST(SUM(in_transit_sar) AS DECIMAL(18,2)) FROM gld.fact_merchant_settlement_recon")),
            # The circuit breaker's own question, asked of the warehouse rather than of dbt's exit code.
            "sum_abs_bank_variance_sar": str(_one(
                cur, "SELECT CAST(SUM(ABS(unexplained_bank_variance_sar)) AS DECIMAL(18,2)) "
                     "FROM gld.fact_merchant_settlement_recon")),
            "sum_abs_gl_variance_sar": str(_one(
                cur, "SELECT CAST(SUM(ABS(unexplained_gl_variance_sar)) AS DECIMAL(18,2)) "
                     "FROM gld.fact_merchant_settlement_recon")),
        }
        zatca = {"rows": _one(cur, "SELECT COUNT(*) FROM gld.fact_zatca_clearance_ledger"),
                 "total_incl_vat_sar": str(_one(
                     cur, "SELECT CAST(SUM(total_incl_vat_sar) AS DECIMAL(18,2)) "
                          "FROM gld.fact_zatca_clearance_ledger"))}
        for state in ("CLEARED", "REPORTED", "ACCEPTED_WITH_WARNINGS", "CONFIRMED_REJECTION"):
            # Parameterised, not interpolated: these are constants here, but a query builder that
            # interpolates is one edit away from doing it with something that is not.
            row = cur.execute(
                "SELECT COUNT(*) FROM gld.fact_zatca_clearance_ledger WHERE state = ?", state).fetchone()
            zatca[state] = row[0] if row else None
        return {
            "fact_merchant_settlement_recon": recon,
            "fact_zatca_clearance_ledger": zatca,
            "fact_merchant_dispute_monitor": {
                "merchants": _one(cur, "SELECT COUNT(*) FROM gld.fact_merchant_dispute_monitor"),
                "breaches_ratio_only": _one(
                    cur, "SELECT COUNT(*) FROM gld.fact_merchant_dispute_monitor WHERE breaches_ratio = 1"),
                "in_monitoring_programme": _one(
                    cur, "SELECT COUNT(*) FROM gld.fact_merchant_dispute_monitor WHERE in_monitoring_programme = 1")},
            "dim_party_golden": {
                "rows": _one(cur, "SELECT COUNT(*) FROM gld.dim_party_golden"),
                "max_member_count": _one(cur, "SELECT MAX(member_count) FROM gld.dim_party_golden")},
            "gold_tables": _one(
                cur, "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'gld' "
                     "AND TABLE_TYPE = 'BASE TABLE'"),
        }
    finally:
        con.close()


def lakehouse_facts() -> dict:
    """LH_MIZAN. The uniqueness counts are here because a doubled table is what row 26 was."""
    con = _conn("LH_MIZAN")
    cur = con.cursor()
    try:
        out = {
            "slv.zatca_invoice_documents": {
                "rows": _one(cur, "SELECT COUNT(*) FROM slv.zatca_invoice_documents"),
                "distinct_invoice_uuid": _one(
                    cur, "SELECT COUNT(DISTINCT invoice_uuid) FROM slv.zatca_invoice_documents")},
            "ctl.invoice_outbox": {
                "rows": _one(cur, "SELECT COUNT(*) FROM ctl.invoice_outbox"),
                "distinct_invoice_uuid": _one(cur, "SELECT COUNT(DISTINCT invoice_uuid) FROM ctl.invoice_outbox")},
            "brz.zatca_invoices_raw": {
                "rows": _one(cur, "SELECT COUNT(*) FROM brz.zatca_invoices_raw"),
                "distinct_request_id": _one(cur, "SELECT COUNT(DISTINCT request_id) FROM brz.zatca_invoices_raw"),
                "note": "Append-only: two versions of every request since the 2026-11-16 price correction."},
            "slv.golden_party_scd2": {"rows": _one(cur, "SELECT COUNT(*) FROM slv.golden_party_scd2")},
            "meta.column_classification": {
                "columns": _one(cur, "SELECT COUNT(*) FROM meta.column_classification"),
                "tables": _one(cur, "SELECT COUNT(DISTINCT CONCAT(schema_name, '.', table_name)) "
                                    "FROM meta.column_classification")},
        }
        # The gate (HONESTY rows 38/40): correction documents carry a -PC suffix on their request id.
        out["price_corrections"] = {
            "documents_issued": _one(
                cur, "SELECT COUNT(*) FROM slv.zatca_invoice_documents WHERE request_id LIKE '%-PC%'"),
            "detector": "enabled",
            "issuance": "gated off (MIZAN_ISSUE_PRICE_CORRECTIONS unset)",
            "would_issue_if_enabled": _one(cur, """
                SELECT 2 * COUNT(DISTINCT o.request_id)
                FROM ctl.invoice_outbox o
                JOIN brz.zatca_invoices_raw r ON r.request_id = o.request_id
                WHERE o.document_type = 'INVOICE'
                  AND TRY_CAST(JSON_VALUE(r.payload_json, '$.total_incl_vat_sar') AS DECIMAL(18,2))
                      <> o.total_incl_vat_sar"""),
            "why": "The document TYPE is unreviewed (HONESTY row 38) and the differences are halala rounding "
                   "from this project's own 2026-11-16 price fix, not a business event (row 40).",
        }
        return out
    finally:
        con.close()


def dbt_result() -> dict:
    """dbt's own run_results.json for the fabric target, if one is present."""
    rr = REPO / "dbt" / "target" / "run_results.json"
    if not rr.exists():
        return {"status": "not run in this session"}
    results = json.loads(rr.read_text(encoding="utf-8"))["results"]
    # dbt says "success" for a model and "pass" for a test; both mean the node is fine. The consumers of
    # this file (build_command_center.py, the Command Center footer) read `pass` and `error`, so those two
    # keys are the contract and the raw statuses are kept alongside rather than instead.
    good = {"success", "pass"}
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"target": "fabric",
            "total": len(results),
            "pass": sum(n for st, n in counts.items() if st in good),
            "error": sum(n for st, n in counts.items() if st not in good | {"skipped"}),
            "skipped": counts.get("skipped", 0),
            "by_status": counts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-date", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--jobs", default="", help="JSON mapping step -> {status, seconds, ...} from the run")
    args = ap.parse_args()
    load_dotenv()

    doc = {
        "run_date": args.run_date,
        "capacity": "Fabric FTL64, UAE North",
        "workspace": "mizan-ksa-dev",
        "note": args.note,
        "notebook_jobs": json.loads(args.jobs) if args.jobs else {},
        "dbt_build_WH_MIZAN": dbt_result(),
        "warehouse_checks_WH_MIZAN": warehouse_facts(),
        "lakehouse_checks_LH_MIZAN": lakehouse_facts(),
        "generated_by": "scripts/fabric_evidence.py (read back from the tenant, not typed)",
    }
    out = ART / "10_fabric_run_evidence.json"
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(REPO)}")
    wh = doc["warehouse_checks_WH_MIZAN"]
    recon, zatca = wh["fact_merchant_settlement_recon"], wh["fact_zatca_clearance_ledger"]
    print(f"  ZATCA documents        {zatca['rows']}")
    print(f"  invoiced value     SAR {zatca['total_incl_vat_sar']}")
    print(f"  gross captures     SAR {recon['gross_captures_sar']}")
    print(f"  bank variance      SAR {recon['sum_abs_bank_variance_sar']}")
    print(f"  GL variance        SAR {recon['sum_abs_gl_variance_sar']}")
    print(f"  corrections issued     "
          f"{doc['lakehouse_checks_LH_MIZAN']['price_corrections']['documents_issued']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

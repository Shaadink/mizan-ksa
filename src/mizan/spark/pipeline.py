"""Bronze -> Silver pipeline, same code for local and Fabric (Phase 3).

.\\.venv\\Scripts\\python.exe -m mizan.spark.pipeline --data data/generated --lake data/lake [--demo-breaks]

--demo-breaks also lands the demo overlay (orphan settlement line, 0.01 float-drift GL line) so the Gold
circuit breaker can be shown failing on exactly those two MID-days (spec Artifact 2). Off by default.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mizan.privacy.crypto import Keys
from mizan.spark import contracts as C
from mizan.spark.ai_land import build_index
from mizan.spark.bronze import land_files, land_invoice_requests
from mizan.spark.governance_land import run_governance
from mizan.spark.lake import Lake, cleanup_staging
from mizan.spark.mdm_land import run_mdm
from mizan.spark.session import TableLocator, get_spark
from mizan.spark.silver import build_erp_gl_journal_lines, build_payment_lifecycle, build_settlement_lines
from mizan.spark.zatca_land import run_zatca


def run_pipeline(data_dir: Path | str, lake_root: Path | str | None = None, *, mode: str = "local",
                 include_demo: bool = False, zatca: bool = True, mdm: bool = True, spark=None,
                 keys: Keys | None = None) -> dict:
    data = Path(data_dir)
    spark = spark or get_spark(mode)
    lake = Lake(spark, TableLocator(mode, Path(lake_root) if lake_root else None))
    keys = keys or Keys.from_env()
    plan = [(C.COMMERCE, [data / "orders/commerce_events.csv"]),
            (C.PAYMENTS, [data / "payments/payment_events.csv"]),
            (C.SETTLEMENT, sorted((data / "settlement").glob("*.csv"))),
            (C.ERP_GL, [data / "erp/erp_gl_acdoca.csv"])]
    if include_demo:
        plan += [(C.SETTLEMENT, [data / "demo/settlement_demo_orphan.csv"]),
                 (C.ERP_GL, [data / "demo/erp_gl_demo_float_bug.csv"])]
    plan += [(C.CRM_POS, [data / "crm/crm_pos_cp1256.csv"]), (C.CRM_ECOM, [data / "crm/crm_ecom_utf8.csv"]),
             (C.SPL, [data / "crm/spl_address_observations.csv"])]
    stats = [land_invoice_requests(lake, keys, data / "zatca/invoice_requests.jsonl", data)]
    cleanup_staging(spark)
    for contract, files in plan:
        stats += land_files(lake, keys, contract, files, data)
        cleanup_staging(spark)
    for build in (build_payment_lifecycle, lambda lk: build_settlement_lines(lk, data),
                  lambda lk: build_erp_gl_journal_lines(lk, data)):
        build(lake)
        cleanup_staging(spark)
    m = run_mdm(lake, keys) if mdm else None
    cleanup_staging(spark)
    z = run_zatca(lake, data / "zatca/fatoora_fault_plan.json") if zatca else None
    cleanup_staging(spark)
    ai = build_index(lake)                   # governed AI chunks (policies + case notes, tombstones skipped)
    cleanup_staging(spark)
    g = run_governance(lake)                 # NDMO catalog last: it must see every table the run wrote
    cleanup_staging(spark)
    return {"files": stats, "zatca": z, "mdm": m, "ai": ai, "governance": g}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/generated")
    ap.add_argument("--lake", default="data/lake")
    ap.add_argument("--mode", default="local", choices=("local", "fabric"))
    ap.add_argument("--demo-breaks", action="store_true")
    ap.add_argument("--skip-zatca", action="store_true")
    a = ap.parse_args()
    res = run_pipeline(a.data, a.lake if a.mode == "local" else None, mode=a.mode, include_demo=a.demo_breaks,
                       zatca=not a.skip_zatca)
    for s in res["files"]:
        print(f"{s['status']:>22} {s['source_file']:<52} rows={s['source_rows']:>6} landed={s['landed_rows']:>6} "
              f"dup={s['duplicate_rows']:>5} rej={s['rejected_rows']:>3} sha_ok={s['sha_match']}")
    print(json.dumps(res["mdm"]))
    print(json.dumps(res["governance"]))
    print(json.dumps(res["zatca"]))


if __name__ == "__main__":
    main()

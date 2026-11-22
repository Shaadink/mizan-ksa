r"""Run a third-party dataset through MIZAN and report what it found, without touching anything real.

    .\.venv\Scripts\python.exe scripts\blind_adversary.py --data data\external\round1
    .\.venv\Scripts\python.exe scripts\blind_adversary.py --data data\external\round1 --keep

**What this is for.** The strongest criticism of a pipeline tested on its own generated data is that the
author invented both the defects and the detector, so a pass proves only that the two agree. Every edge
case handled is one that was already imagined.

`docs/testing/EXTERNAL_DATA_CONTRACT.md` is a brief that can be handed to someone who has not seen this
code, asking for a realistic month of Saudi retail data across all seven source files. They also write a
**sealed note** of what they deliberately made wrong, which stays sealed until after the first run.

This script is the run. It lands their files, builds Silver, resolves identities, runs the tax chain and
builds Gold, then prints everything the pipeline objected to. That report is what gets compared against
their sealed note:

    in their note and found       -> detection worked
    in their note and NOT found   -> a real gap. The valuable outcome
    found, not in their note      -> their accident, or a false positive here

**It never touches the real lake.** Everything happens in a scratch directory that is deleted afterwards
unless `--keep` is passed. A run that could corrupt `data/lake` would be an expensive way to learn
something about a stranger's CSV.

**It does not fail on their defects.** A quarantined row, a tripped circuit breaker and a chain violation
are the *output* of this exercise, not errors in it. The script exits non-zero only if the pipeline itself
could not run -- the distinction matters, because "the data was bad" and "the tool broke" are different
findings and only one of them is interesting.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

EXPECTED = (
    "orders/commerce_events.csv",
    "payments/payment_events.csv",
    "erp/erp_gl_acdoca.csv",
    "crm/crm_pos_cp1256.csv",
    "crm/crm_ecom_utf8.csv",
    "crm/spl_address_observations.csv",
    "zatca/invoice_requests.jsonl",
)

# Reference data the pipeline needs but the outside author is not asked for: fee schedules and the GL
# account map are the receiving organisation's own configuration, not something a data supplier sends.
REFERENCE = ("reference/acquirer_fee_schedule.csv", "reference/gl_account_roles.csv", "reference/merchants.csv")


def check_inputs(data: Path) -> list[str]:
    """What is missing or empty. Reported rather than raised: a partial delivery is still worth running."""
    problems = []
    for rel in EXPECTED:
        p = data / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
        elif p.stat().st_size == 0:
            problems.append(f"empty: {rel}")
    if not list(data.glob("settlement/*.csv")):
        problems.append("missing: settlement/*.csv (at least one payout file)")
    return problems


def borrow_reference(data: Path, scratch: Path) -> list[str]:
    """Copy the receiving organisation's own reference data in, if the supplier did not send it."""
    borrowed = []
    for rel in REFERENCE:
        dst = scratch / rel
        if dst.exists():
            continue
        src = REPO / "data" / "generated" / rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            borrowed.append(rel)
    return borrowed


def count(lake, schema: str, table: str) -> int | None:
    return lake.read(schema, table).count() if lake.exists(schema, table) else None


def findings(lake) -> dict:
    """Everything the pipeline objected to. This is the report, not a failure list."""
    from pyspark.sql import functions as F
    out: dict = {}

    if lake.exists("quarantine", "schema_rejections"):
        df = lake.read("quarantine", "schema_rejections")
        out["schema_rejections"] = {
            "rows": df.count(),
            "by_reason": {r["reject_reason"]: r["n"] for r in
                          df.groupBy("reject_reason").agg(F.count("*").alias("n"))
                            .orderBy(F.desc("n")).limit(25).collect()}}

    if lake.exists("quarantine", "settlement_breaks"):
        df = lake.read("quarantine", "settlement_breaks")
        out["settlement_breaks"] = {
            "rows": df.count(),
            "by_type": {r["break_type"]: r["n"] for r in
                        df.groupBy("break_type").agg(F.count("*").alias("n"))
                          .orderBy(F.desc("n")).collect()}}

    if lake.exists("quarantine", "zatca_chain_violations"):
        df = lake.read("quarantine", "zatca_chain_violations")
        out["zatca_chain_violations"] = {
            "rows": df.count(),
            "by_type": {r["violation_type"]: r["n"] for r in
                        df.groupBy("violation_type").agg(F.count("*").alias("n"))
                          .orderBy(F.desc("n")).collect()}}

    if lake.exists("quarantine", "mdm_match_conflicts"):
        df = lake.read("quarantine", "mdm_match_conflicts")
        out["mdm_match_conflicts"] = {
            "rows": df.count(),
            "by_type": {r["conflict_type"]: r["n"] for r in
                        df.groupBy("conflict_type").agg(F.count("*").alias("n")).collect()}}

    if lake.exists("slv", "settlement_lines"):
        df = lake.read("slv", "settlement_lines")
        out["settlement_status"] = {r["settlement_status"]: r["n"] for r in
                                    df.groupBy("settlement_status").agg(F.count("*").alias("n")).collect()}

    if lake.exists("slv", "zatca_invoice_documents"):
        df = lake.read("slv", "zatca_invoice_documents")
        out["zatca_states"] = {r["state"]: r["n"] for r in
                               df.groupBy("state").agg(F.count("*").alias("n")).collect()}
        out["zatca_uuid_unique"] = df.select("invoice_uuid").distinct().count() == df.count()

    out["row_counts"] = {f"{s}.{t}": count(lake, s, t) for s, t in (
        ("brz", "commerce_events_raw"), ("brz", "payment_events_raw"),
        ("brz", "settlement_batches_raw"), ("brz", "erp_gl_raw"),
        ("brz", "crm_party_raw"), ("brz", "spl_address_raw"), ("brz", "zatca_invoices_raw"),
        ("slv", "payment_lifecycle"), ("slv", "settlement_lines"), ("slv", "erp_gl_journal_lines"),
        ("slv", "golden_party_scd2"), ("slv", "zatca_invoice_documents"))}
    return out


def build_gold(lake_root: Path, scratch: Path) -> dict:
    """dbt on DuckDB against their Silver. A failing circuit breaker is a FINDING, not an error."""
    import os
    import subprocess
    duck = scratch / "gold.duckdb"
    env = {**os.environ, "MIZAN_LAKE_ROOT": Path(lake_root).as_posix(),
           "MIZAN_DUCKDB_PATH": duck.as_posix(), "MIZAN_DBT_TARGET": "duckdb"}
    code = ("import sys; from dbt.cli.main import dbtRunner; "
            "r = dbtRunner().invoke(sys.argv[1:]); sys.exit(0 if r.success else 1)")
    proc = subprocess.run(  # noqa: S603 (fixed argv)
        [sys.executable, "-c", code, "build", "--project-dir", str(REPO / "dbt"),
         "--profiles-dir", str(REPO / "dbt"), "--target-path", str(scratch / "target"),
         "--log-path", str(scratch / "logs"), "--quiet"],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2400)
    rr = scratch / "target" / "run_results.json"
    if not rr.exists():
        return {"ran": False, "detail": (proc.stdout + proc.stderr)[-3000:]}
    results = json.loads(rr.read_text(encoding="utf-8"))["results"]
    failed = [r["unique_id"].split(".")[2] for r in results if r["status"] not in ("success", "pass")]
    return {"ran": True, "total": len(results), "failed_count": len(failed), "failed": sorted(failed)[:40]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path, help="folder holding the outside author's files")
    ap.add_argument("--keep", action="store_true", help="keep the scratch lake for inspection")
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "artifacts" / "15_blind_adversary.json")
    args = ap.parse_args()

    data = args.data.resolve()
    if not data.is_dir():
        raise SystemExit(f"{data} is not a directory")

    problems = check_inputs(data)
    print(f"=== inputs from {data} ===")
    for rel in EXPECTED:
        p = data / rel
        print(f"  {'OK  ' if p.exists() and p.stat().st_size else 'MISS'}  {rel}")
    print(f"  {len(list(data.glob('settlement/*.csv')))} settlement file(s)")
    for p in problems:
        print(f"  ! {p}")
    if len(problems) >= len(EXPECTED):
        raise SystemExit("nothing usable in that folder -- check the layout in "
                         "docs/testing/EXTERNAL_DATA_CONTRACT.md")

    scratch = Path(tempfile.mkdtemp(prefix="mizan-adversary-"))
    staged, lake_root = scratch / "data", scratch / "lake"
    shutil.copytree(data, staged)
    borrowed = borrow_reference(data, staged)
    if borrowed:
        print(f"\nborrowed our own reference data (not asked of the supplier): {', '.join(borrowed)}")

    report: dict = {"source": str(data), "input_problems": problems, "borrowed_reference": borrowed}
    t0 = time.perf_counter()
    try:
        from mizan.privacy.crypto import Keys, load_dotenv
        from mizan.spark.lake import Lake
        from mizan.spark.pipeline import run_pipeline
        from mizan.spark.session import TableLocator, get_spark
        load_dotenv()

        print("\n=== running the pipeline on their data ===")
        spark = get_spark("local", shuffle_partitions=4)
        try:
            run_pipeline(staged, lake_root, spark=spark, keys=Keys.from_env())
            report["pipeline"] = {"ran": True}
        except Exception as e:
            # Their data stopping the pipeline is itself a finding, and the most severe kind.
            report["pipeline"] = {"ran": False, "error": f"{type(e).__name__}: {e}",
                                  "traceback": traceback.format_exc()[-3000:]}
            print(f"  pipeline STOPPED: {type(e).__name__}: {e}")

        lake = Lake(spark, TableLocator("local", lake_root))
        report["findings"] = findings(lake)
        print("\n=== building Gold ===")
        report["gold"] = build_gold(lake_root, scratch)
    finally:
        report["seconds"] = round(time.perf_counter() - t0, 1)
        if args.keep:
            print(f"\nscratch kept at {scratch}")
            report["scratch"] = str(scratch)
        else:
            shutil.rmtree(scratch, ignore_errors=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    print("\n" + "=" * 68)
    print("  WHAT THE PIPELINE OBJECTED TO")
    print("=" * 68)
    f = report.get("findings", {})
    for key in ("schema_rejections", "settlement_breaks", "zatca_chain_violations", "mdm_match_conflicts"):
        if key in f:
            print(f"  {key:<24} {f[key]['rows']:>8,}")
            for k, v in list(f[key].get("by_reason", f[key].get("by_type", {})).items())[:10]:
                print(f"      {k:<40} {v:>8,}")
    if "settlement_status" in f:
        print(f"  settlement_status        {f['settlement_status']}")
    if "zatca_states" in f:
        print(f"  zatca_states             {f['zatca_states']}")
        print(f"  zatca invoice_uuid unique{'  yes' if f.get('zatca_uuid_unique') else '  NO -- duplicates'}")
    g = report.get("gold", {})
    if g.get("ran"):
        print(f"  dbt                      {g['total'] - g['failed_count']}/{g['total']} passed")
        for name in g["failed"]:
            print(f"      FAILED  {name}")
    else:
        print("  dbt                      did not run")
    print("=" * 68)
    print(f"\nwrote {args.out.relative_to(REPO)}")
    print("\nNow open their sealed note and compare. What is in the note and NOT above is the finding.")
    # Their defects are the point. Only a pipeline that could not run at all is a failure of this script.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

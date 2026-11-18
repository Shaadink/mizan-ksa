r"""Disaster recovery drill: rebuild Gold and prove it came back identical.

Backups are a claim until someone restores from them. This drill makes the claim checkable: it
fingerprints every Gold table, rebuilds Gold from scratch, fingerprints again, and fails if a single
value moved. It also times the rebuild, which is the RTO figure anyone will actually ask for.

A DuckDB file is never byte-identical between builds -- it carries timestamps and its own page layout --
so the fingerprint is taken over table *contents*: every row of every Gold table, each value rendered
in a canonical text form, sorted so row order cannot matter, then SHA-256 per table.

Two depths:

    --from gold     (default) re-run dbt against the existing Silver lake.
                    Proves Gold is reproducible from Silver. Seconds, safe for CI.

    --from source   regenerate the source data from the fixed seed first, then Bronze/Silver through
                    Spark, then Gold. Proves the whole chain from seed to warehouse. Minutes.

Run:
    .\.venv\Scripts\python.exe scripts\dr_drill.py                 # Gold from Silver
    .\.venv\Scripts\python.exe scripts\dr_drill.py --from source   # seed to warehouse
    .\.venv\Scripts\python.exe scripts\dr_drill.py --write-baseline

Writes docs/artifacts/13_dr_drill.json. --write-baseline records today's fingerprints as the baseline
to compare against; without it, the drill compares to the committed baseline and fails on any drift.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

GOLD = REPO / "tmp" / "mizan_gold.duckdb"
LAKE = REPO / "data" / "lake"
GEN = REPO / "data" / "generated"
DBT = REPO / "dbt"
BASELINE = REPO / "docs" / "artifacts" / "13_dr_drill_baseline.json"
REPORT = REPO / "docs" / "artifacts" / "13_dr_drill.json"

# Built by dbt from Silver. Seeds are inputs, not outputs, so they are not part of the claim.
SEEDS = {"umm_al_qura_calendar", "hijri_announcement_overrides", "merchant_store_reference"}


def _canon(v) -> str:
    """One value, rendered so the same data always renders the same way.

    Decimal("0.00") and Decimal("0.0000") are the same money but different strings, so money is
    normalised to two places. None must not collide with the literal string "None".
    """
    if v is None:
        return "\x00NULL"
    if isinstance(v, Decimal):
        return str(v.quantize(Decimal("0.01"))) if -1e15 < v < 1e15 else str(v)
    if isinstance(v, float):                       # money is never float here; be explicit if it appears
        return repr(round(v, 6))
    if isinstance(v, (bytes, bytearray)):
        return hashlib.sha256(bytes(v)).hexdigest()
    return str(v)


def fingerprint(duck: Path) -> dict[str, dict]:
    """SHA-256 over the contents of every Gold table, independent of row order and file layout."""
    import duckdb
    con = duckdb.connect(duck.as_posix(), read_only=True)
    try:
        tables = [t for t, in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'gld' ORDER BY 1").fetchall()]
        out = {}
        for t in tables:
            cols = [c for c, in con.execute(
                "SELECT column_name FROM duckdb_columns() WHERE schema_name = 'gld' "
                "AND table_name = ? ORDER BY column_index", [t]).fetchall()]
            rows = con.execute(f'SELECT * FROM gld."{t}"').fetchall()      # noqa: S608 (name from catalog)
            lines = sorted("\x1f".join(_canon(v) for v in row) for row in rows)
            h = hashlib.sha256()
            h.update(("\x1e".join(cols) + "\x1d").encode("utf-8"))         # schema is part of the identity
            for line in lines:
                h.update(line.encode("utf-8"))
                h.update(b"\x1e")
            out[t] = {"rows": len(rows), "columns": len(cols), "sha256": h.hexdigest()}
        return out
    finally:
        con.close()


def run_dbt(duck: Path, lake: Path) -> tuple[bool, str]:
    """dbt build in a child process: dbt-duckdb holds its connection for the life of the process."""
    env = dict(os.environ, MIZAN_DUCKDB_PATH=str(duck), MIZAN_LAKE_ROOT=str(lake))
    code = ("import sys; from dbt.cli.main import dbtRunner; "
            "r = dbtRunner().invoke(sys.argv[1:]); sys.exit(0 if r.success else 1)")
    proc = subprocess.run([sys.executable, "-c", code, "build",            # noqa: S603 (fixed argv)
                           "--project-dir", str(DBT), "--profiles-dir", str(DBT)],
                          env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=1800)
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def rebuild_source() -> float:
    """Regenerate the source data from the fixed seed, then Bronze/Silver through Spark."""
    t0 = time.perf_counter()
    for args in (["-m", "mizan.generator", "--out", str(GEN)],
                 ["-m", "mizan.spark.pipeline", "--data", str(GEN), "--lake", str(LAKE)]):
        proc = subprocess.run([sys.executable, *args], cwd=REPO,            # noqa: S603 (fixed argv)
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=5400)
        if proc.returncode != 0:
            raise RuntimeError(f"{args[1]} failed:\n{(proc.stdout or '')[-2000:]}{(proc.stderr or '')[-2000:]}")
    return time.perf_counter() - t0


def compare(before: dict, after: dict) -> list[str]:
    drift = []
    for t in sorted(set(before) | set(after)):
        b, a = before.get(t), after.get(t)
        if b is None:
            drift.append(f"{t}: appeared only after the rebuild")
        elif a is None:
            drift.append(f"{t}: did not come back")
        elif b["sha256"] != a["sha256"]:
            drift.append(f"{t}: contents changed ({b['rows']} rows -> {a['rows']}, "
                         f"{b['sha256'][:12]} -> {a['sha256'][:12]})")
    return drift


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="depth", choices=("gold", "source"), default="gold",
                    help="gold: rebuild Gold from Silver (default). source: regenerate from the seed first.")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the current fingerprints as the baseline instead of comparing")
    args = ap.parse_args()

    if not GOLD.exists():
        print(f"{GOLD} not found: build Gold once before running the drill.")
        return 2

    print(f"Fingerprinting the Gold we have ({GOLD.name})...")
    before = fingerprint(GOLD)
    for t, m in before.items():
        print(f"  {t:38s} {m['rows']:>6} rows  {m['sha256'][:16]}")

    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps({"recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "tables": before}, indent=1) + "\n",
                            encoding="utf-8", newline="\n")
        print(f"\nwrote {BASELINE.relative_to(REPO)}")
        return 0

    source_secs = 0.0
    if args.depth == "source":
        print("\nRegenerating from the fixed seed, then Bronze and Silver through Spark...")
        source_secs = rebuild_source()
        print(f"  source and lake rebuilt in {source_secs / 60:.1f} min")

    print("\nRebuilding Gold into a scratch database...")
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="mizan_dr_") as tmp:
        duck = Path(tmp) / "gold_restored.duckdb"
        ok, log = run_dbt(duck, LAKE)
        gold_secs = time.perf_counter() - t0
        if not ok:
            print("dbt build failed:\n" + log[-2500:])
            return 1
        after = fingerprint(duck)
    print(f"  Gold rebuilt in {gold_secs:.1f}s")

    drift = compare(before, after)
    baseline_drift = []
    if BASELINE.exists():
        baseline_drift = compare(json.loads(BASELINE.read_text(encoding="utf-8"))["tables"], after)

    report = {
        "drilled_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "depth": args.depth,
        "rto_seconds": {"source_and_lake": round(source_secs, 1), "gold": round(gold_secs, 1),
                        "total": round(source_secs + gold_secs, 1)},
        "tables": after,
        "rows_total": sum(m["rows"] for m in after.values()),
        "identical_to_live": not drift,
        "identical_to_baseline": not baseline_drift if BASELINE.exists() else None,
        "drift": drift + [f"(baseline) {d}" for d in baseline_drift],
        "note": "Fingerprints are SHA-256 over table contents in a canonical text form, sorted so row "
                "order cannot matter. Seeds are inputs, not outputs: " + ", ".join(sorted(SEEDS)) + ".",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")

    print(f"\n{'=' * 64}")
    print(f"  tables {len(after)}   rows {report['rows_total']:,}   "
          f"RTO {report['rto_seconds']['total']:.1f}s")
    if drift:
        print("  DRIFT against the live Gold:")
        for d in drift:
            print(f"    - {d}")
    else:
        print("  every Gold table came back identical to the live warehouse")
    if baseline_drift:
        print("  DRIFT against the committed baseline:")
        for d in baseline_drift:
            print(f"    - {d}")
    print(f"{'=' * 64}\nwrote {REPORT.relative_to(REPO)}")
    return 1 if (drift or baseline_drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())

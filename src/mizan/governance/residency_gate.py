"""CI / pre-publish gate (I-14): fail when a column's NDMO tier exceeds its zone ceiling or region.

    python -m mizan.governance.residency_gate --lake data/lake --duckdb tmp/mizan_gold.duckdb
Reads meta.column_classification (Delta, via DuckDB) for LH_MIZAN zones and classifies the Gold tables in the
DuckDB/Warehouse output with the same rules. Exit code 1 on any violation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mizan.governance.catalog import classify_column, load_policy, residency_violations

REPO = Path(__file__).resolve().parents[3]


def collect_columns(lake_root: Path | None, duck_path: Path | None) -> list[dict]:
    import duckdb
    cols: list[dict] = []
    con = duckdb.connect()
    try:
        if lake_root is not None:
            con.execute("INSTALL delta; LOAD delta")
            loc = (Path(lake_root) / "LH_MIZAN" / "meta" / "column_classification").as_posix()
            rows = con.execute("SELECT schema_name, table_name, column_name, classification FROM delta_scan(?)",
                               [loc]).fetchall()
            for s, t, c, k in rows:
                cols.append({"zone": f"LH_MIZAN.{s}", "schema_name": s, "table_name": t, "column_name": c,
                             "classification": k})
        if duck_path is not None:
            con.execute(f"ATTACH '{Path(duck_path).as_posix()}' AS gold (READ_ONLY)")
            for t, c in con.execute("SELECT table_name, column_name FROM information_schema.columns "
                                    "WHERE table_catalog = 'gold' AND table_schema = 'gld'").fetchall():
                cols.append({"zone": "WH_MIZAN.gld", "schema_name": "gld", "table_name": t, "column_name": c,
                             "classification": classify_column("gld", t, c).tier})
    finally:
        con.close()
    return cols


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", type=Path)
    ap.add_argument("--duckdb", type=Path)
    ap.add_argument("--policy", type=Path, default=REPO / "config" / "residency_policy.yml")
    a = ap.parse_args(argv)
    zones, approved = load_policy(a.policy)
    cols = collect_columns(a.lake, a.duckdb)
    bad = residency_violations(cols, zones, approved)
    for b in bad:
        print("VIOLATION", b)
    print(f"residency gate: {len(cols)} columns checked, {len(bad)} violations")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

"""Freshness gate (spec Module 3): before `dbt build`, the Lakehouse must show the batch ids this run landed.

The Fabric SQL analytics endpoint can lag the Delta log; reading Gold before Silver is visible would silently build
on stale data. The gate compares expected batch ids with ctl.ingestion_watermarks as the reader sees it.
"""

from __future__ import annotations

from pathlib import Path


class StaleLakehouse(RuntimeError):
    pass


def check(expected: set[str], visible: set[str]) -> dict:
    missing = sorted(expected - visible)
    if missing:
        raise StaleLakehouse(f"{len(missing)} expected batch(es) not visible yet: {missing[:5]}")
    return {"expected": len(expected), "visible": len(visible & expected), "status": "FRESH"}


def visible_batches_local(lake_root: Path) -> set[str]:
    """Local / Docker reader: the Delta table through DuckDB (what dbt-duckdb will read)."""
    import duckdb
    con = duckdb.connect()
    try:
        con.execute("INSTALL delta; LOAD delta")
        loc = (Path(lake_root) / "LH_MIZAN" / "ctl" / "ingestion_watermarks").as_posix()
        return {r[0] for r in con.execute("SELECT DISTINCT batch_id FROM delta_scan(?)", [loc]).fetchall()}
    finally:
        con.close()


def gate(lake_root: Path, expected: set[str], *, retries: int = 1, wait_s: float = 0) -> dict:
    import time
    for attempt in range(retries):
        try:
            return check(expected, visible_batches_local(lake_root))
        except StaleLakehouse:
            if attempt == retries - 1:
                raise
            time.sleep(wait_s)
    raise AssertionError("unreachable")

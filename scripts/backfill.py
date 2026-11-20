"""The tested re-run procedure: rebuild, then prove what did and did not change.

    .\\.venv\\Scripts\\python.exe scripts\\backfill.py                 # dry run: say what would happen
    .\\.venv\\Scripts\\python.exe scripts\\backfill.py --execute       # rebuild Gold and compare
    .\\.venv\\Scripts\\python.exe scripts\\backfill.py --execute --expect-changes

"Backfill the last 30 days" is the question every operator asks and this pipeline deliberately cannot
answer, because it does not rebuild *days* -- it rebuilds Silver and Gold from the whole of Bronze every
time. That is slower and it removes the question that is easiest to get wrong under pressure at 03:00:
which days do I re-run, and what happens to the ones either side of the boundary.

So the procedure is not "re-run a range". It is "re-run everything, and prove exactly what moved":

  1. fingerprint every Gold table (contents, not row counts -- a swapped pair of rows must show),
  2. rebuild,
  3. fingerprint again and report every table and value that differs.

**A backfill that changes nothing is the expected result** when the source data has not changed, and that
is worth stating because it is the opposite of most people's instinct. If a fingerprint moves and nobody
changed source data, that is a finding.

The fingerprint and comparison are `scripts/dr_drill.py`'s, reused rather than reimplemented: a second
definition of "did Gold come back the same" would be a second thing to keep in step. Writes
`docs/artifacts/14_backfill.json`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

GOLD = REPO / "tmp" / "mizan_gold.duckdb"
LAKE = REPO / "data" / "lake"
OUT = REPO / "docs" / "artifacts" / "14_backfill.json"


def _dr_drill():
    """Import scripts/dr_drill.py as a module, so fingerprint/compare have exactly one definition."""
    spec = importlib.util.spec_from_file_location("dr_drill", REPO / "scripts" / "dr_drill.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["dr_drill"] = module
    spec.loader.exec_module(module)
    return module


def summarise(before: dict, after: dict, differences: list[str]) -> dict:
    """What moved, in the words an operator needs, not a diff dump."""
    tables = sorted(set(before) | set(after))
    return {
        "tables_compared": len(tables),
        "tables_unchanged": sum(1 for t in tables if before.get(t) == after.get(t)),
        "tables_changed": sorted(t for t in tables if before.get(t) != after.get(t)),
        "tables_lost": sorted(t for t in before if t not in after),
        "tables_new": sorted(t for t in after if t not in before),
        "differences": differences[:50],
        "difference_count": len(differences),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true",
                        help="actually rebuild. Without it nothing is run and nothing is written.")
    parser.add_argument("--expect-changes", action="store_true",
                        help="succeed only if something changed. Use after a deliberate source correction; "
                             "without it, any change is reported as a failure to investigate.")
    args = parser.parse_args(argv)

    if not GOLD.exists() or not LAKE.exists():
        print("local Gold database and lake are not built; nothing to compare against")
        return 2

    drill = _dr_drill()
    before = drill.fingerprint(GOLD)
    print(f"before: {len(before)} Gold tables fingerprinted")

    if not args.execute:
        print("\nDRY RUN. Nothing has been rebuilt and nothing written.")
        print("This procedure rebuilds Silver and Gold from the whole of Bronze -- it does not re-run a")
        print("date range, because this pipeline has no date-range rebuild. Re-landing identical source")
        print("files changes nothing; re-landing corrected files lands only the rows whose payload moved.")
        print("\nRe-run with --execute to rebuild and compare.")
        return 0

    started = datetime.now(UTC)
    ok, log = drill.run_dbt(GOLD, LAKE)
    if not ok:
        # The circuit breaker refusing to publish is a correct outcome, not a backfill failure. Say which.
        print("dbt build FAILED -- Gold was not republished, so the previous good version still stands.")
        print("Work docs/RUNBOOKS.md#the-circuit-breaker-tripped before re-running.")
        print(log[-3000:])
        return 1

    after = drill.fingerprint(GOLD)
    differences = drill.compare(before, after)
    result = {
        "ran_at": started.isoformat(timespec="seconds"),
        "seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        "expected_changes": args.expect_changes,
        **summarise(before, after, differences),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"\n{result['tables_unchanged']}/{result['tables_compared']} Gold tables identical "
          f"in {result['seconds']}s")
    for line in differences[:20]:
        print(f"  {line}")
    if result["difference_count"] > 20:
        print(f"  ... and {result['difference_count'] - 20} more (see {OUT.relative_to(REPO).as_posix()})")

    if args.expect_changes and not differences:
        print("\nNothing changed, but --expect-changes was given. The correction did not reach Gold.")
        return 1
    if differences and not args.expect_changes:
        print("\nGold changed on a re-run of unchanged source data. That is a finding, not noise:")
        print("either the source did change, or something in the build is not deterministic.")
        return 1
    print("\nOK" + (" -- changes as expected" if args.expect_changes else " -- Gold is reproducible"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

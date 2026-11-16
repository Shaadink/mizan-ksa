"""Read a Delta table's current files without DuckDB's `delta` extension.

Why this exists
---------------
`INSTALL delta; LOAD delta` downloads an unsigned binary into ~/.duckdb/extensions. Windows Smart App
Control blocks unsigned binaries, so on a protected machine every `delta_scan()` fails with
"An Application Control policy has blocked this file" and the whole build stops.

A Delta table is just Parquet files plus a JSON transaction log, and DuckDB reads Parquet natively. So
we resolve the current file set ourselves by replaying the log: apply each commit in order, honouring
`add` and `remove`. That is a snapshot read -- no time travel, no schema evolution handling -- which is
all the build and lineage need. Code that needs time travel must still use the extension.
"""

from __future__ import annotations

import json
from pathlib import Path


def delta_files(table_dir: str | Path) -> list[str]:
    """Absolute paths of the Parquet files that make up the table's current version."""
    root = Path(table_dir)
    log = root / "_delta_log"
    if not log.is_dir():
        raise FileNotFoundError(f"{root} is not a Delta table (no _delta_log)")
    active: dict[str, None] = {}
    for commit in sorted(log.glob("*.json")):
        for line in commit.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            action = json.loads(line)
            if "add" in action:
                active[action["add"]["path"]] = None
            elif "remove" in action:
                active.pop(action["remove"]["path"], None)
    files = [str((root / p).resolve()) for p in active]
    if not files:
        raise ValueError(f"{root} has no active Parquet files")
    return files


def delta_rel(table_dir: str | Path) -> str:
    """A SQL fragment reading those files; a drop-in replacement for `delta_scan('<dir>')`.

    Paths are embedded as single-quoted literals with quotes doubled, so a path containing an
    apostrophe cannot break out of the string.
    """
    quoted = ", ".join("'" + f.replace("'", "''") + "'" for f in delta_files(table_dir))
    return f"read_parquet([{quoted}])"

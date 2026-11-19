"""The open mirroring landing zone is a contract with Fabric, and it fails quietly.

Get the file name wrong and the batch is simply never read. Put `__rowMarker__` anywhere but last and
the rows are misapplied. Pad a delete row with nulls and replication for that table stops with a schema
merge error that nothing in the pipeline surfaces. None of that raises in our code, so the rules are
pinned here instead.

No network: these cover the file-format decisions, which is where the mistakes actually live.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fabric_open_mirror", REPO / "scripts" / "fabric_open_mirror.py")
OM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(OM)


def test_file_name_is_twenty_digits_and_starts_at_one():
    """Fabric applies files in name order; a short or zero name is skipped without an error."""
    assert OM.landing_file_name(1) == "00000000000000000001.parquet"
    assert OM.landing_file_name(42) == "00000000000000000042.parquet"
    assert len(Path(OM.landing_file_name(7)).stem) == 20
    with pytest.raises(ValueError):
        OM.landing_file_name(0)


def test_file_names_sort_in_numeric_order():
    """Zero padding is the whole point: without it file 10 sorts before file 2."""
    names = [OM.landing_file_name(n) for n in (1, 2, 10, 11, 100)]
    assert names == sorted(names)


def test_metadata_declares_the_key_columns():
    """Without keyColumns, every file is append-only -- updates and deletes silently become inserts."""
    meta = json.loads(OM.metadata_file())
    assert meta == {"keyColumns": ["merchant_id"]}


def test_row_marker_must_be_the_final_column():
    """Fabric reads the marker positionally; a misplaced one corrupts the table rather than erroring."""
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "x.parquet"
        with pytest.raises(ValueError):
            OM.write_parquet([{"a": "1", OM.ROW_MARKER: 0, "b": "2"}], ["a", OM.ROW_MARKER, "b"], out)


def test_cdc_batch_is_one_update_one_delete_one_insert():
    rows = OM.read_seed()
    batch = OM.cdc_batch(rows)
    assert [r[OM.ROW_MARKER] for r in batch] == [OM.UPDATE, OM.DELETE, OM.INSERT]


def test_every_cdc_row_carries_every_column():
    """Including the delete.

    The format allows a delete to carry only the key columns, but DuckDB marks a Parquet column
    REQUIRED when the data it is handed has no nulls -- so the initial load produced a non-nullable
    schema, and a null-padded delete row arrives as nullable. Fabric then rejects the batch with
    SchemaMergeFailure and stops replicating the table. This was found by hitting it in the live
    workspace, so it is pinned here rather than left to be rediscovered.
    """
    rows = OM.read_seed()
    source_columns = set(rows[0])
    for row in OM.cdc_batch(rows):
        assert set(row) == source_columns | {OM.ROW_MARKER}
        assert all(row[c] not in (None, "") for c in source_columns), row


def test_initial_load_has_no_row_marker():
    """Mirroring treats a file with no marker as all-INSERT, which is what an initial load is.

    Including the marker would make the first file an incremental batch and change how it is counted.
    """
    rows = OM.read_seed()
    assert OM.ROW_MARKER not in rows[0]


def test_written_parquet_round_trips_with_the_marker_last():
    duckdb = pytest.importorskip("duckdb")
    rows = OM.read_seed()
    batch = OM.cdc_batch(rows)
    columns = [*rows[0], OM.ROW_MARKER]
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / OM.landing_file_name(2)
        OM.write_parquet(batch, columns, out)
        con = duckdb.connect()
        try:
            got = con.execute(f"SELECT * FROM read_parquet('{out.as_posix()}')").fetchall()
            names = [d[0] for d in con.description]
        finally:
            con.close()
    assert names == columns and names[-1] == OM.ROW_MARKER
    assert [r[-1] for r in got] == [OM.UPDATE, OM.DELETE, OM.INSERT]


def test_key_column_is_unique_in_the_source():
    """keyColumns cannot be changed after the first write, so the choice has to be right first time."""
    rows = OM.read_seed()
    keys = [tuple(r[c] for c in OM.KEY_COLUMNS) for r in rows]
    assert len(set(keys)) == len(keys)

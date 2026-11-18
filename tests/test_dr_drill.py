"""The disaster recovery drill must notice when Gold comes back wrong.

A drill that always passes is worse than no drill: it converts an untested claim into a tested-looking
one. These tests check the fingerprint reacts to the smallest change this project cares about -- one
halala -- and that the comparison reports a table that did not come back.

The drill itself (scripts/dr_drill.py) needs a built warehouse, so it is not run here; what is tested
is the part that decides whether a restore was faithful.
"""

from __future__ import annotations

import importlib.util
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dr_drill", REPO / "scripts" / "dr_drill.py")
DR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DR)


def _fingerprint_with(tmp: Path, name: str, amount: str) -> dict:
    """Build a one-table Gold database with the given amount, and fingerprint it."""
    import duckdb
    d = tmp / name
    d.mkdir()
    db = d / "gold.duckdb"
    con = duckdb.connect(db.as_posix())
    try:
        con.execute("CREATE SCHEMA gld")
        con.execute("CREATE TABLE gld.fact_x (id INTEGER, amount_sar DECIMAL(18,2), note VARCHAR)")
        con.execute("INSERT INTO gld.fact_x VALUES (1, 10.00, 'a'), (2, ?, 'b'), (3, 30.00, NULL)",
                    [Decimal(amount)])
    finally:
        con.close()
    return DR.fingerprint(db)


def test_one_halala_changes_the_fingerprint():
    """The whole project reconciles to 0.01 SAR; a restore check blind to a halala proves nothing."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        same = _fingerprint_with(tmp, "a", "20.00")
        other = _fingerprint_with(tmp, "b", "20.01")
    assert same["fact_x"]["sha256"] != other["fact_x"]["sha256"]


def test_fingerprint_is_stable_for_identical_data():
    """Same data, different file: the hash is over contents, not over the DuckDB file."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        a = _fingerprint_with(tmp, "a", "20.00")
        b = _fingerprint_with(tmp, "b", "20.00")
    assert a["fact_x"]["sha256"] == b["fact_x"]["sha256"]
    assert a["fact_x"]["rows"] == 3


def test_null_does_not_collide_with_the_text_none():
    """A NULL note and a note reading "None" are different data and must hash differently."""
    import duckdb
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        hashes = []
        for i, note in enumerate(("NULL", "'None'")):
            d = tmp / str(i)
            d.mkdir()
            db = d / "gold.duckdb"
            con = duckdb.connect(db.as_posix())
            try:
                con.execute("CREATE SCHEMA gld")
                con.execute("CREATE TABLE gld.fact_x (id INTEGER, note VARCHAR)")
                con.execute(f"INSERT INTO gld.fact_x VALUES (1, {note})")
            finally:
                con.close()
            hashes.append(DR.fingerprint(db)["fact_x"]["sha256"])
    assert hashes[0] != hashes[1]


@pytest.mark.parametrize("mutate,expect", [
    (lambda d: d.update(fact_x={**d["fact_x"], "sha256": "0" * 64}), "contents changed"),
    (lambda d: d.pop("fact_x"), "did not come back"),
])
def test_compare_reports_drift(mutate, expect):
    before = {"fact_x": {"rows": 3, "columns": 3, "sha256": "a" * 64}}
    after = {k: dict(v) for k, v in before.items()}
    mutate(after)
    drift = DR.compare(before, after)
    assert drift and expect in drift[0]


def test_compare_is_clean_when_nothing_moved():
    before = {"fact_x": {"rows": 3, "columns": 3, "sha256": "a" * 64}}
    assert DR.compare(before, {k: dict(v) for k, v in before.items()}) == []

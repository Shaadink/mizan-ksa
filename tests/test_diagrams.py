"""The diagrams are claims about the system, so they are tested like any other claim.

A drawing drifts from the code the moment either changes, and nobody notices until a stranger reads it.
These tests do not check that a picture is pretty. They check the three things that would make it a lie:
that the files exist, that the dbt lineage really is read from the manifest rather than drawn by hand,
and that every table named in the schema map is a table the Spark layer actually writes.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DIAGRAMS = REPO / "docs" / "diagrams"
EXPECTED = ("01_architecture", "02_dataflow_one_sale", "03_schema_map",
            "04_zatca_state_machine", "05_reconciliation_spine", "06_dbt_lineage")


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_diagrams", REPO / "scripts" / "build_diagrams.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("stem", EXPECTED)
def test_every_diagram_is_built(stem: str) -> None:
    svg = DIAGRAMS / f"{stem}.svg"
    assert svg.exists(), f"{svg.relative_to(REPO)} missing -- run scripts/build_diagrams.py"
    text = svg.read_text(encoding="utf-8")
    assert text.startswith("<svg") and text.rstrip().endswith("</svg>")
    assert "<title>" in text, "a diagram with no title is unreadable to a screen reader"


def test_diagrams_are_ascii_only() -> None:
    """Arabic and other non-ASCII belong in escapes, not raw in a generated file (CLAUDE.md)."""
    for stem in EXPECTED:
        text = (DIAGRAMS / f"{stem}.svg").read_text(encoding="utf-8")
        bad = sorted({c for c in text if ord(c) > 127})
        assert not bad, f"{stem}.svg carries raw non-ASCII: {bad}"


def test_dbt_lineage_matches_the_manifest() -> None:
    """Every model box in the lineage picture is a model dbt actually has, and none is missing."""
    manifest = REPO / "dbt" / "target" / "manifest.json"
    if not manifest.exists():
        pytest.skip("dbt/target/manifest.json not present -- run dbt first")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    models = {n["name"] for n in m["nodes"].values() if n["resource_type"] == "model"}
    svg = (DIAGRAMS / "06_dbt_lineage.svg").read_text(encoding="utf-8")
    drawn = {name for name in models if f">{name}<" in svg}
    assert drawn == models, f"lineage picture disagrees with the manifest: {models ^ drawn}"


def test_the_node_count_in_the_subtitle_is_the_real_one() -> None:
    """99 is a dbt BUILD's node count, not a test count. The front pages said 'tests' until 2026-11-22."""
    manifest = REPO / "dbt" / "target" / "manifest.json"
    if not manifest.exists():
        pytest.skip("dbt/target/manifest.json not present")
    kinds = [n["resource_type"] for n in json.loads(manifest.read_text(encoding="utf-8"))["nodes"].values()]
    svg = (DIAGRAMS / "06_dbt_lineage.svg").read_text(encoding="utf-8")
    for kind, word in (("model", "models"), ("test", "tests"), ("seed", "seeds")):
        assert f"{kinds.count(kind)} {word}" in svg, f"subtitle disagrees with the manifest on {word}"
    assert f"runs {len(kinds)} nodes" in svg


def test_schema_map_names_only_tables_the_code_writes(builder) -> None:
    """Guards the failure this picture exists to prevent: a box for a table that does not exist.

    Checked against the generator's own spec rather than against text scraped out of the SVG, so a
    table drawn with an ordinary-looking name cannot slip past for want of a recognisable suffix."""
    written = set()
    for py in (REPO / "src" / "mizan" / "spark").glob("*.py"):
        src = py.read_text(encoding="utf-8")
        written |= set(re.findall(
            r'"(?:brz|ctl|slv|quarantine|security|audit|meta|ai)",\s*"([a-z_0-9]+)"', src))
    assert len(written) > 20, "found almost no lake writes -- the regex has gone stale"

    drawn = {t for _schema, _c, _note, tables in builder.LAKEHOUSE_TABLES for t in tables}
    assert not drawn - written, f"the schema map draws tables nothing writes: {sorted(drawn - written)}"
    assert not written - drawn, f"tables the code writes are missing from the map: {sorted(written - drawn)}"


def test_schema_map_covers_the_frozen_schema_list(builder) -> None:
    """LH_MIZAN's eight schemas are frozen by the blueprint. All eight are drawn, and only those."""
    from mizan.spark.session import LAKEHOUSE_SCHEMAS
    assert {s for s, *_ in builder.LAKEHOUSE_TABLES} == set(LAKEHOUSE_SCHEMAS)


def test_the_generator_is_the_only_author(builder) -> None:
    """A hand-edited SVG would silently stop matching its spec, so the stamp says not to."""
    for stem in EXPECTED:
        assert "do not edit the SVG by hand" in (DIAGRAMS / f"{stem}.svg").read_text(encoding="utf-8")
    assert builder.STAMP.startswith("MIZAN-KSA")

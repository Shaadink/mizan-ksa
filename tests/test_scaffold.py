"""Phase 0: the frozen scaffold contract."""

from pathlib import Path

import mizan

ROOT = Path(__file__).resolve().parents[1]


def test_spec_revision_is_design_freeze():
    assert mizan.SPEC_REVISION == "v1.1 - Design Freeze"


def test_nine_namespaces_exactly():
    assert mizan.LAKEHOUSE_SCHEMAS == (
        "brz", "ctl", "slv", "quarantine", "security", "audit", "meta", "ai",
    )
    assert mizan.WAREHOUSE_SCHEMAS == ("gld",)
    assert len(mizan.LAKEHOUSE_SCHEMAS) + len(mizan.WAREHOUSE_SCHEMAS) == 9


def test_timezone_is_riyadh():
    assert mizan.TIMEZONE == "Asia/Riyadh"


def test_required_docs_exist():
    for rel in ["CLAUDE.md", "PROGRESS.md", "README.md", "HONESTY.md", "invariants.md"]:
        assert (ROOT / rel).is_file(), rel


def test_six_adrs_exist():
    adrs = sorted((ROOT / "docs" / "adr").glob("ADR-00[1-6]-*.md"))
    assert [p.name[:7] for p in adrs] == [f"ADR-00{i}" for i in range(1, 7)]


def test_fourteen_invariants_declared():
    text = (ROOT / "invariants.md").read_text(encoding="utf-8")
    for i in range(1, 15):
        assert f"I-{i:02d}" in text


def test_env_is_gitignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines

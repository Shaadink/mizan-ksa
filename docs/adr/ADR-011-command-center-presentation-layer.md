# ADR-011: A cinematic web Command Center beside Power BI, as a presentation layer only

- **Status:** Accepted (owner-approved addition to the frozen stack, 2026-11-15)
- **Date:** 2026-11-15

## Context

The Power BI Control Tower on Fabric is the governed report, but Power BI cannot do motion: native visuals barely
animate, the HTML Content visual blocks JavaScript, and real animation needs a custom-coded visual. The owner wanted
an enterprise showcase with motion and storytelling that a reviewer can understand in a minute, without weakening
any correctness rule.

## Decision

- Add `command_center/`: one self-contained page (Three.js scales, GSAP timelines, D3 charts, story mode, command
  palette, CFO / Tax / CDO role views). It is a **presentation layer only**: it reads a snapshot, writes nothing and
  holds no secrets. Power BI stays the official report.
- Every figure comes from `scripts/build_command_center.py`, which exports from the Gold DuckDB tables, the Delta
  lakehouse, a re-run of the ZATCA engine, the stream replay, the dbt manifest (lineage) and the Phase 11 proof
  runs. Nothing is typed in by hand.
- Money stays exact end to end: `Decimal` in Python, decimal text in JSON, integer halalas in the browser. Count-up
  animations interpolate integer halalas and finish on the exact value.
- PII stays masked: IDs and phones are shown as `213....831`; `tests/test_command_center.py` fails on any unmasked
  10-digit ID, Arabic-Indic ID or phone number.
- Scripts load only pinned versions from cdnjs/jsDelivr. The page is published as a private claude.ai page, so the
  repository can stay private.

## Consequences

The page is a snapshot of one run; it does not refresh itself, and rebuilding is one command. It is outside the
original tool list (Fabric, Airflow, dbt, OpenLineage, pytest, Docker, GitHub Actions), so it is recorded here and in
HONESTY.md. Tests guard the money identities, determinism, masking and script pinning in CI.

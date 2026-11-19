# ADR-014: Open mirroring is demonstrated, not load-bearing

**Status:** Accepted (2026-11-19, owner-approved)
**Context:** spec Section 5.1 freezes the stack; this adds a Fabric component that was not in it.

## Context

Every other table in MIZAN arrives because we run something: a notebook lands Bronze, dbt builds Gold.
Fabric's **open mirroring** is the opposite contract -- a source system drops change files into a OneLake
landing zone and Fabric maintains the Delta table itself, with no pipeline and no Capacity Units spent on
the copy. It is the Fabric-native answer to "get this SAP or Oracle table in without a migration project",
which is a question Saudi enterprises actually ask.

The owner asked for it on 2026-11-19 after reviewing a competing blueprint that listed it.

## Decision

Implement open mirroring for real, on one table, and **do not wire it into the pipeline**.

`MR_MIZAN` is a mirrored database holding `erp.merchant_master`, fed from
`dbt/seeds/merchant_store_reference.csv` by `scripts/fabric_open_mirror.py`. Gold continues to read the
seed.

## Why not wire it in

`gld.merchant_store_reference` is the obvious candidate -- it is reference data that genuinely originates
outside the pipeline. Pointing Gold at the mirror instead would make the dbt project depend on a
Fabric-only feature, and the models would stop building on DuckDB locally and in CI.

"The same models run locally and on Fabric" is a property worth more than having one fewer source of the
same rows. Tests that only run against a cloud tenant are tests that stop being run.

So the mirror is a working parallel implementation. It proves the pattern and the mechanics; it does not
carry the reconciliation.

## What was proven, not asserted

Run against the live workspace on 2026-11-19:

- initial load of 121 rows ingested with no `__rowMarker__` (Fabric treats the file as all-INSERT)
- an incremental batch of one UPDATE, one DELETE and one INSERT applied in order
- `scripts/fabric_open_mirror.py verify` reads the table back over its SQL endpoint: 121 rows,
  `MID100044` register count 4 -> 6, `MID100120` gone, `MID100121` present in Abha
- Fabric applied the delete with a Delta **deletion vector**, visible in `Tables/erp/merchant_master`

## Consequences

**A constraint was found by hitting it.** DuckDB marks a Parquet column `REQUIRED` when the data it is
handed contains no nulls. The initial load therefore produced a non-nullable schema, and a delete row
padded with nulls -- which the format explicitly permits, since only key columns are required -- arrived
as nullable. Fabric rejected the batch with `SchemaMergeFailure` and **stopped replicating that table**,
with nothing in the pipeline to surface it. The fix is that every CDC row carries every column.
`tests/test_open_mirroring.py` pins this so it is not rediscovered.

**Failures are silent.** A wrong file name is skipped; a misplaced `__rowMarker__` misapplies rows; a
schema mismatch halts one table. None of it raises anywhere we would see. The format rules are therefore
tested, and `status` reports the per-table error.

**`keyColumns` cannot be changed** once `_metadata.json` is written, so `merchant_id` was checked for
uniqueness in the source first (a test asserts it).

**Recovery is by folder.** `reset` deletes the table folder, which is the documented way to restart one
table; the mirrored table is dropped and rebuilt from the next initial load.

**It is on a trial capacity** in a college tenant with the same expiry as everything else. Deleting
`MR_MIZAN` removes it entirely; nothing else depends on it.

## Alternatives rejected

- **Wire Gold to the mirror.** Rejected above: it breaks local and CI builds.
- **Mirror a fact table.** Rejected: facts are computed by MIZAN, so a mirror of them would be fiction.
  Reference data is the only honest candidate.
- **Skip it as "a feature for a list".** Rejected once it was clear the mechanics could be implemented and
  verified end to end rather than described. A demonstration that runs is not the same as a bullet point.

# ADR-015 — Three Gold facts are built incrementally, keyed on a Bronze arrival watermark

* **Status:** Accepted
* **Date:** 2026-11-20
* **Decided by:** the project owner, explicitly, after being shown that the spec freezes Gold as tables
* **Supersedes:** nothing. **Amends:** the materialisation half of spec Section 5 rule 3

## The question that was actually asked

An outside review of this project listed "no incremental models — every Gold table is rebuilt in full on
every run" as the one remaining engineering gap that code could close. It is a fair point. A full rebuild
of a reconciliation is fine at 25,000 invoices and is not fine at 25 million.

The reason it had not been done is that `CLAUDE.md` freezes it:

> **Gold models materialized as tables.**

So this was not a refactor to slip in. It needed the owner to say yes, and on 2026-11-20 they did.

## What the frozen rule was protecting, and why this does not break it

The rule exists for one reason, written next to it in `dbt_project.yml`: Power BI's **Direct Lake** mode
reads Delta tables directly, and falls back to the much slower DirectQuery if the thing it points at is not
a table. The rule is there to stop anyone making Gold out of views.

**An incremental dbt model is a physical table.** dbt creates it once with `CREATE TABLE` and from then on
issues `DELETE` and `INSERT` against that same table. Nothing becomes a view. Direct Lake cannot tell the
difference, because there is no difference to tell: the only thing that changed is how the rows get there.

So the letter of the rule is amended — the three facts below say `materialized = 'incremental'` — and the
intent of the rule is untouched. That is the whole reason this was a decision the owner could say yes to
without weakening anything.

## Decision

### 1. Three models become incremental. Four do not.

| Model | Materialisation | Why |
|---|---|---|
| `fact_merchant_settlement_recon` | **incremental**, `delete+insert`, key `(merchant_id, business_date_ksa)` | A day's reconciliation only depends on that day's three legs |
| `fact_payment_method_daily` | **incremental**, `delete+insert`, key `(merchant_id, business_date_ksa)` | Same, one level finer — see the note on the key below |
| `fact_zatca_clearance_ledger` | **incremental**, `delete+insert`, key `invoice_uuid` | One row per document; a document is independent of every other |
| `dim_date_saudi` | table | A moon-sighting announcement moves a month *boundary* and re-numbers days on both sides of it. There is no changed key, only a changed edge |
| `dim_party_golden` | table | Shows only *current* profiles, so a retired profile's correct new state is **absent**. An incremental build updates rows it is handed and cannot delete rows it is not, so retired profiles would accumulate, looking current, forever |
| `fact_merchant_dispute_monitor` | table | The window is `MIN`/`MAX` over all payments: one new event changes `window_days` on all 121 merchants |
| `mart_ndmo_scorecard` | table | Every figure is a ratio over an entire table; a new row moves the denominator with no key changing |

The four that stay are not leftovers. Each one's SQL file now opens with the paragraph explaining why, so
that a later reader "finishing the job" has to argue with the reason rather than discover it.

### 2. The watermark is Bronze's arrival time, carried into Silver

Silver gains one column, `source_ingested_at`, which is Bronze's `_ingested_at` passed through unchanged.

This is the load-bearing choice. Silver is rebuilt in full on every pipeline run, so a timestamp generated
*during* a Silver build would move for every row every time, and a watermark over it would select the whole
table on every run — an incremental model that is a full rebuild wearing a costume. Bronze is append-only,
so a row's arrival time is a fact about the data rather than about the last time the pipeline ran.

The ZATCA ledger is the exception and takes its watermark from `ctl.invoice_outbox.updated_at`, because a
document's **state** is decided by what ZATCA answers, long after the request landed in Bronze. Using
Bronze's time there would mean a document moving from `SUBMITTING` to `CLEARED` carried an unchanged
timestamp, stayed below the cut-off, and never appeared in the ledger — the model would be missing exactly
the documents that had just succeeded. **Invariant this relies on: any write that changes a document's
state must set `updated_at`.**

### 3. A key is rebuilt whole, from all of Silver — never appended to

The incremental run finds which keys were *touched* by late-arriving data, then deletes those keys and
re-derives them from the complete Silver history. It does not add the new rows to what was there.

This is the difference between "incremental" and "append", and in this domain it is the difference between
a reconciliation and a number. If a bank file for Tuesday arrives on Friday and we appended its line to
Tuesday's row, Tuesday would hold two partial rows whose variances mean nothing. Rebuilding Tuesday in full
produces exactly what a full refresh would. `tests/test_gold_incremental.py` asserts that by building both
ways and diffing the tables.

### 4. The cut-off is `>=`, not `>`

Bronze stamps every row in a landing batch with the same `current_timestamp()`. An exclusive cut-off would
skip forever any row sharing its timestamp with the recorded maximum. With `>=`, the last batch is simply
processed again, and because a rebuild re-derives whole keys, doing it twice changes nothing.

The cost of `>=` is a little repeated work. The cost of `>` is silent data loss. That is not a close call.

### 5. `fact_payment_method_daily`'s incremental key is coarser than its grain

Its grain is `(merchant, day, scheme)`; its `unique_key` is only `(merchant, day)`. This is deliberate.

A bank line whose payment event has not arrived is reported under the synthetic scheme
`UNMATCHED_BANK_LINE`. When the payment lands, that row should be *replaced* by a real `MADA` or `VISA` row
and the `UNMATCHED_BANK_LINE` row should cease to exist. Keyed at the grain, the rebuild has no row to
overwrite it with, so the stale row survives and the day's fees are counted twice — which the existing
reconciliation test against `fact_merchant_settlement_recon` would then fail, loudly, but only after the
wrong number had been published. Keyed at the day, the delete clears every scheme for that day before the
insert. Deleting more than you insert is the safe direction.

### 6. The watermark is excluded from the DR drill's fingerprint, by name

`scripts/dr_drill.py` hashes Gold's contents to prove a rebuild came back identical.
`last_source_arrival_at` is a wall clock reading that legitimately differs between two builds of identical
data, so it is excluded — exactly one column, named in `EXCLUDED_COLUMNS`, pinned by a test. Column counts
and every business value are still compared. A check that fails for a reason unrelated to correctness is a
check people learn to ignore.

## The case this nearly got wrong, recorded because it is the interesting one

The obvious set of "what changed" legs is payments, settlements and GL — anything whose own
`source_ingested_at` moved. That set is **incomplete**, and the gap is silent.

A bank line that arrives before its payment event is an orphan: it is `QUARANTINED`. When the payment
finally lands, the *same* bank line becomes `PAID_BANK`. Money moves between `quarantined_sar` and
`bank_paid_sar` — but the line's own arrival time never moves, because it is the bank file's, and that file
is old. The day would keep the quarantined figure permanently, and nothing would ever flag it.

So both reconciliation models carry a fourth leg: *any settlement day whose matching payment event arrived
since the cut-off is also changed*. This is the class of bug incremental models are notorious for, and it is
not found by running the pipeline normally — it needs a test that lands data out of order on purpose, which
is what `test_late_payment_rescues_an_orphaned_bank_line` does.

## What this does not solve

* **Reference data.** If the acquirer fee schedule, the GL account role map, or the dispute thresholds in
  `dbt_project.yml` change, nothing arrives in Bronze, no watermark moves, and Gold keeps the old figures.
  The fix is `dbt build --full-refresh`, and `docs/RUNBOOKS.md` lists when to run it. This is a *decision an
  operator makes*, not something the schedule does by accident.
* **Model edits.** dbt does not know the SQL changed. Same fix, same runbook.
* **Concurrent Bronze landing.** The watermark assumes arrival times never go backwards, which holds because
  the Airflow DAG lands Bronze in a single task on a linear chain. If Bronze ever becomes concurrent, this
  must become a stored watermark in `ctl.ingestion_watermarks` rather than a `MAX()` over Gold.
* **The actual scale claim.** This has been proven correct on ~25,000 invoices. It has *not* been run at a
  volume where the saving matters, so no performance number is claimed anywhere. See `HONESTY.md`.

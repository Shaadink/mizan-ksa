# ADR-016 — A price corrected after signing is fixed by cancelling in full and reissuing

* **Status:** Accepted
* **Date:** 2026-11-21
* **Closes:** HONESTY row 29, open since 2026-11-19
* **Depends on:** ADR-004 (clearance vs reporting), the ZATCA rules frozen in `CLAUDE.md`

## The defect, stated plainly

Correcting an item price upstream moved Silver, Gold and the bank reconciliation, and left the signed tax
chain showing the old amount. On the project's own data the gap was **SAR 396.18** — 30,920,225.04 against
30,919,828.86.

That is the exact condition this entire project exists to detect — a tax ledger disagreeing with the
books — occurring inside the project itself. It was found by CI, comparing live Fabric DAX results against
exported Gold, not by anybody reading the code.

## Why the existing behaviour was not a bug, which is what made it dangerous

`run_zatca` skips every `request_id` already in `ctl.invoice_outbox`. That is **correct and must not
change**: re-pricing a document ZATCA already holds would mean re-signing a cleared tax document, which is
the one thing a ZATCA chain must never do.

So both halves of the old behaviour were defensible. The engine was right to refuse, and the result was
still wrong. The missing piece was never a patch to the engine — it was **a pair of documents nobody was
issuing**.

This is worth recording because it is the shape of the most expensive defects: no component is behaving
badly, and the system is wrong anyway.

## Decision

### 1. Cancel in full, then reissue — one valid treatment, not the universal one

Two shapes are defensible when an invoice's price changes after it has been sent:

| | Difference note | **Cancel in full + replacement invoice** |
|---|---|---|
| Documents | 1 | 2 |
| Chain arithmetic | `100 − 4 = 96` | `100 − 100 + 96 = 96` |
| ZATCA type | 381 credit (overcharge) / **383 debit (undercharge)** | 381 credit + a new invoice |

Both reach the same total. This ADR implements the second, and ZATCA does illustrate that shape — a credit
note followed by a new invoice — for a replacement.

> **Correction, 2026-11-21, same day this ADR was written.** The original version of this section argued
> that the difference note was *wrong* because "a difference note has no honest line items — minus four
> riyals of nothing is not a description of an item." **That was false, and checkable.** ZATCA's own
> guidance uses a **debit note (type 383) for an undercharge**: its business-promotions guideline works
> through a hotel that charged less than the agreed price and corrects it with a debit note for the
> additional amount due, leaving the original invoice in place. A difference note's lines describe the
> correction, which is an honest thing to describe.
>
> An external reviewer caught it, and the claim was verified against ZATCA's guidance before this was
> rewritten — the same check that confirmed the HTTP 303 fix. The argument was an engineering preference
> presented as a compliance fact, which is the exact failure mode `HONESTY.md` exists to prevent. It is
> left visible rather than quietly edited out.

**What stands:** the pair this emits is arithmetically correct in every case, never touches the signed
document, and is a legitimate treatment for a cancellation or replacement.

**What does not:** that it is the right treatment for *every* price correction. Choosing between an
undercharge (383), an overcharge (381), a correction of erroneous invoice information, and a genuine
cancellation-and-replacement is a **Saudi VAT classification decision**. No specialist has reviewed this.
Emitting 383 for undercharges is the named fix and it needs that review first — guessing a tax document
type is precisely the confident wrongness this project exists to avoid. `HONESTY.md` row 38.

### 2. Both documents are new. The original never moves.

New request id, new UUID, its own ICV, signed in its own right, chained normally. The original stays in the
chain exactly as it was sent. The chain **arrives at** the corrected total by adding documents, which is
the only way a tax chain is allowed to change its mind.

Request ids are the original's plus a suffix — `-PC1CN` for the cancellation and `-PC1RI` for the
replacement — so a reader of `gld.fact_zatca_clearance_ledger` can see at a glance why a document exists
and which one it corrects, without joining anything. Both carry `billing_reference_uuid` pointing at the
original, which is what ZATCA itself reads.

### 3. Detection comes from Bronze holding both versions

The engine cannot detect this, because it deliberately never looks at a request it has already signed.
Bronze can: it is append-only, so a corrected re-send leaves **both** the version that was signed and the
version that is now true.

The signed version is identified by matching the total stored in `ctl.invoice_outbox`, **never** by "the
oldest row". That distinction is the difference between reversing the amount ZATCA actually received and
reversing a guess.

### 4. Two deliberate fail-closed paths

* **A changed `CREDIT_NOTE` raises.** Reversing a credit note requires a debit note (ZATCA type 383), which
  this project does not model. Half-handling a tax correction is worse than refusing one.
* **If no Bronze version matches the signed total, it raises.** Issuing a credit note against an amount the
  authority never received is its own tax problem, and a worse one than the gap it was meant to fix.

### 5. Three ledger postings, netting to the correction

The original posting stands, the cancellation reverses it, the replacement posts the corrected amount. Each
has its own `invoice_uuid`, so the frozen rule — `accounting_postings == 1` per `invoice_uuid` — holds
unchanged, and the ledger shows the correction rather than hiding it inside an edited figure. That is how a
ledger is supposed to handle a credit note.

## Consequences

* The ZATCA chain gains two ICVs per corrected invoice. Correct, and the reason the detector must be
  idempotent: a detector that re-fired would add two ICVs per invoice per night, for ever. Pinned by a test
  that runs the landing twice and asserts the second run issues nothing.
* `issue_ts_utc` on the pair defaults to the corrected request's, which keeps reruns byte-identical
  (`CLAUDE.md` determinism). **In production it must be the date the correction is actually issued.** The
  parameter exists; the default is a test-determinism choice, and this sentence is the reason it is not
  mistaken for a modelling claim.
* Nothing routes a *quantity* or *line count* change into this yet — only a change in the document total is
  detected. A corrected invoice with the same total and different lines would pass unnoticed.

### Repeat corrections, and the invariant that makes them work

The detector does not ask "has this invoice ever been corrected" — that question is only answerable the
first time, and an implementation built on it fired a second pair on the very next run. The question is:

> **What does the chain currently state this invoice is worth?**

That is the amount on the most recent replacement if there is one, and the original otherwise. If it
already equals the live Bronze payload, nothing is issued. If it does not, the pair cancels **the document
that states the current amount** — the previous replacement, not the original. Cancelling the original
twice would subtract it twice and the chain would net to the wrong figure.

The invariant, stated once so it can be checked: **the chain's net for a request equals the current Bronze
total**, after any number of corrections. A test corrects the same invoice twice and asserts exactly that,
plus that the second cancellation reverses the first replacement.

## What was rejected

**Blocking the upstream price change instead.** Refusing to let Silver move until the tax chain agrees
would make the lakehouse hostage to the tax authority's availability, and would not help: the sale really
did happen at the corrected price. The books are not wrong; the tax chain was incomplete.

**Re-signing with the same UUID.** Never. It is the failure this project's ZATCA module exists to make
impossible, and it would invalidate every downstream hash in the chain.

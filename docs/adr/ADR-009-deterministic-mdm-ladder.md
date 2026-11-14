# ADR-009: Deterministic MDM ladder anchored on typed identifiers, with a reversible ledger

- **Status:** Accepted (Phase 5)
- **Date:** 2026-11-14

## Context

One customer appears in five spellings (CP1256 Arabic, repaired mojibake, tashkeel + ligature with Arabic-Indic
ID digits, full and abbreviated English). Two brothers share a father's name, family name and home landline, and a
third record without an ID matches both. A fuzzy score would merge the brothers or guess for the third record.
Bronze holds identifiers and names only as ciphertext or keyed HMACs.

## Decision

- **Anchor first.** A checksum-valid National ID / Iqama (persons) or a format-valid VAT / 700 number
  (organisations) is the only thing that merges records automatically. Two different valid IDs never merge.
- **ID-less records** join a golden profile only when a name in the same script is compatible (initials allowed)
  AND they share a phone with **exactly one** candidate. Two or more candidates go to
  `quarantine.mdm_match_conflicts`; none means a new golden profile. No transliteration, no score.
- **Ledger is the truth.** `slv.entity_merge_ledger` is append-only; current membership is the fold of its events.
  Steward decisions (actor other than SYSTEM) pin a record, so re-runs never undo them; UNMERGE reverses any merge.
  `slv.golden_party_scd2` versions every membership or attribute change.
- **No cleartext in Silver.** MDM decrypts in driver memory only; it persists HMACs and the source ciphertext of the
  surviving legal name (clean source first, plain spelling over tashkeel/ligature forms, then oldest record).

## Consequences

Precision is guaranteed by construction (I-09, I-10), and every decision is explainable from the ledger. Recall is
lower where two records of one person share no comparable name script and no ID (54 records in the generated
data stay separate); those are candidates for a steward review list rather than an automatic guess.

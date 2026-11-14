# ADR-010: Erasure = shred every linked key + delete the token link + tombstone; Restore Guard before serving

- **Status:** Accepted (Phase 6)
- **Date:** 2026-11-14

## Context

PDPL erasure must make a person unrecoverable everywhere analytical, while ZATCA/SAMA retention forbids touching
the signed tax journal. Delta time travel and backups can bring old keys back. One person may have several subject
tokens (one per source record), linked only through MDM.

## Decision

- `security.subject_token_map` (written at the Bronze landing) holds token -> source identity, encrypted under the
  KEK with a purpose binding. Erasure **deletes** these rows.
- A DSR resolves the person through the ID HMAC and golden membership to **every** linked token, then for each:
  vault `wrapped_dek = NULL`, `SHREDDED`; `VACUUM RETAIN 0 HOURS` on the vault and the token map (zero
  deleted-file retention); a row in `ctl.deletion_tombstones`; MDM re-resolved; evidence in
  `audit.pdpl_dsr_evidence` including tax totals before and after.
- `audit.zatca_chain_journal` is never modified: the reference decision reports `LEGAL_HOLD_RETAINED` for TAX/SAMA
  and fails closed on an unknown class before anything changes.
- **Restore Guard** (`restore_guard`) re-applies every tombstone after any restore of data or vault tables, before
  serving; Bronze key minting also refuses tombstoned tokens, even if a restored vault still holds their key.

## Consequences

Bronze, Silver and Gold rows for the person stay in place (statutory totals unchanged) but are ciphertext without a
key. The residual window is OneLake's platform soft-delete, stated in HONESTY.md. Restores must call the guard;
the Airflow DAG runs it as the first serving step.

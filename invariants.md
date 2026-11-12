# MIZAN-KSA — the 14 automated invariants

Source: spec v1.1 Section 9 (proof artifacts) and the docstrings in Section 8. Every invariant is backed by an
executable test in `tests/`. The "Test" column is filled in as each phase lands.

The spec groups the invariants per artifact (e.g. "I-01 to I-04"); the one-per-ID split below follows the
order the spec lists them in and the IDs its reference code cites (I-02 = hash, I-03 = definitive statuses).

| ID | Module | Invariant (pass criterion) | Artifact | Test |
|----|--------|----------------------------|----------|------|
| I-01 | M2 ZATCA | Per EGS, ICVs are strictly sequential with **zero gaps**, and ICV 1 chains from the genesis PIH `base64(hex(sha256("0")))`. | 01 | Phase 2 |
| I-02 | M2 ZATCA | `PIH[n] == invoice_hash[n-1]`, where `invoice_hash` = base64(SHA-256(C14N XML minus UBLExtensions, cac:Signature and QR reference)), computed once at signing. | 01 | Phase 2 |
| I-03 | M2 ZATCA | Only HTTP 200/202/400/401/403 are definitive; every other outcome is `UNKNOWN_OUTCOME` and retries the identical UUID and bytes. `accounting_postings == 1` per `invoice_uuid`. | 01 | Phase 2 |
| I-04 | M2 ZATCA | QR TLV length byte == UTF-8 byte length of the value (tags 1-7 text, tags 8-9 raw bytes), property-tested over random Arabic strings. | 01 | Phase 2 |
| I-05 | M3 Recon | Per MID x business day: Expected Net (captures - refunds/disputes - bank fees) == Bank Paid + In-Transit + Quarantined, and `unclassified_events == 0`. | 02 | Phase 4 |
| I-06 | M3 Recon | Net Sales == GL card clearing (GL variance 0.00); **zero FLOAT/DOUBLE** columns in financial schemas. | 02 | Phase 4 |
| I-07 | M5 PDPL | A shredded identity is unrecoverable in Bronze, Silver, Gold and AI chunks — **including via vault time travel**. | 03 | Phase 6 |
| I-08 | M5 PDPL | A simulated restore (data snapshot AND old vault version) re-applies tombstones before serving; zero cleartext PII in Bronze, Silver or Gold. | 03 | Phase 6 |
| I-09 | M4 MDM | Zero false merges on conflicting National IDs (Hard-Negative Brother Test); an ambiguous ID-less match never auto-merges (steward queue). | 04 | Phase 5 |
| I-10 | M4 MDM | Every merge is reversible in `slv.entity_merge_ledger`; Umm al-Qura dates verified against the versioned calendar. | 04 | Phase 5 |
| I-11 | M7 Skew | Salted join output row count and SAR checksum match the unsalted baseline 100%. | 05 | Phase 7 |
| I-12 | M7 Skew | Replay of a duplicate batch is idempotent (`ctl.applied_event_ledger`). | 05 | Phase 3/7 |
| I-13 | M6 Lineage | 100% of Gold columns traced in lineage with `run_id` + `git_sha` (`audit.run_manifests`). | 06 | Phase 8 |
| I-14 | M6 NDMO | CI policy gate fails the build if a Secret/Top Secret column targets an open (unapproved) schema/sink. | 06 | Phase 6/8 |

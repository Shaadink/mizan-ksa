# HONESTY.md — what MIZAN-KSA is, and what it is not

This file states the boundaries of every claim. It is updated as each phase lands and finalized in Phase 11.

## Scope boundaries (from spec v1.1 Section 11)

- **Synthetic data.** All records come from a deterministic, fixed-seed generator (~100K rows). No real
  customer, merchant or tax data is used. The 20M-row figure is a local Docker Spark stress benchmark, not a
  Fabric production workload.
- **Not a certified tax product.** MIZAN-KSA implements ZATCA Phase-2 hashing and state rules as a
  standards-informed reference architecture. It is not ZATCA-certified and does not talk to the real Fatoora
  portal; a mock Fatoora server is used.
- **Signing.** ECDSA secp256k1 with a self-generated **test key**. Full XAdES signed-properties structure and
  ZATCA SDK certification are **out of scope** (ADR-006).
- **ERP.** GL lines are ACDOCA-*shaped*. No SAP system or binary cluster (RFBLG/BSEG) extraction is involved.
- **Privacy residual window.** Erasure is immediate for every analytical copy. The only residual window is
  OneLake's platform soft-delete, which MIZAN cannot shorten.
- **Regulatory interpretation.** PDPL/NDMO controls are configurable technical controls, not legal advice.
  Velocity rules are named as velocity rules; no SAMA clause is claimed.

## Open items (filled in during the build)

| Phase | Item | Status |
|-------|------|--------|
| 0 | Invariant one-per-ID numbering is derived from the spec's grouped ranges (see `invariants.md`). | Stated |
| 1 | Fee rates (MADA 0.80% capped 200, VISA/MC 1.95%, BNPL 4%, SADAD 0.5% capped 10, chargeback fee 50) are synthetic, not any acquirer's tariff. | Stated |
| 1 | Ramadan start 2026-02-18 is used only to shape traffic; calendar truth comes from the versioned Umm al-Qura table (Phase 5). | Stated |
| 1 | ACDOCA-shaped GL keeps `HSL` positive with `DRCRK` (S/H) carrying direction, to honour the project's positive-amount rule; real ACDOCA stores signed HSL. GL covers the daily sales journal only (no settlement clearing postings). | Stated |
| 1 | The spec names 6 of the 12 planted defects; D03/D04/D06/D07/D09/D11 are taken from the Section 9 artifact descriptions. "ICV gap" is modelled as a post-signing journal deletion (tamper), since MIZAN mints ICVs itself (ADR-001). | Stated |
| 1 | Byte-identical reruns are guaranteed for the same Python minor version (stdlib `random` stream). | Stated |
| 2 | C14N hash validated against a ZATCA SDK sample invoice, or a self-consistent hash if no sample is available (spec Day-3 kill switch). | Pending |

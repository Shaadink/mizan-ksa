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
| 2 | **Hash not yet matched against a ZATCA SDK sample invoice** (no SDK sample in this offline build). Per the spec's Day-3 kill switch, a self-consistent hash ships: C14N 1.0 inclusive via lxml over the invoice minus UBLExtensions, cac:Signature and the QR reference; tests prove it is stable under re-serialisation and invariant under signing. | Stated |
| 2 | XML is a simplified UBL 2.1 shape (no XAdES SignedProperties, no full ZATCA business-rule set). The signature is ECDSA secp256k1 over the invoice digest with a deterministic **test** key; tags 8/9 come from a self-signed test certificate. | Stated |
| 2 | Fatoora is a local mock. It really verifies the QR hash, the ECDSA signature and header-vs-line VAT, but the 400/401/403/5xx/timeout responses are scripted from the fault plan. | Stated |
| 2 | ctl/audit tables are held in an in-memory store whose contract is "survives a worker crash"; durable Delta persistence arrives in Phase 3. GL posting is an idempotent stand-in for the ERP API (keyed on the sale's invoice_uuid). | Stated |
| 3 | Local Spark on Windows uses a portable Temurin JDK 17.0.21 (sha256 verified against Adoptium) and a **community-built** Hadoop `winutils.exe`/`hadoop.dll` for Hadoop 3.3.x (github.com/cdarlint/winutils; sha256 496a591e... / d7ab36a6...). Apache does not publish these binaries. Local tooling only; Fabric needs neither. | Stated |
| 3 | `brz.crm_party_raw` and `brz.spl_address_raw` are **added** Bronze tables. The spec lists CRM/SPL as sources but names no Bronze table for them. All spec-named tables are unchanged. | Stated |
| 3 | Fee estimates on IN_TRANSIT rows use the same synthetic schedule the bank applies, so the estimate equals the eventual bank line. In reality the estimate would carry a tolerance until the file arrives. | Stated |
| 3 | `subject_token_id` is keyed on the source customer reference (one token per source record). Linking several tokens to one person is MDM's job (Phase 5); erasure must then shred every linked token. | Stated |
| 4 | Gold is proven on the **local DuckDB target** (reading the Silver Delta tables with `delta_scan`). The same dbt models target WH_MIZAN through dbt-fabric, but that run needs the tenant (Phase 10) and the Microsoft ODBC Driver 18 on the machine running dbt. | Stated |
| 4 | The Gold recon SQL is the spec reference except the GL leg, which signs `amount_sar` by `debit_credit` (ADR-007). | Stated |
| 4 | The "demo flag" is a separate overlay of two source files (orphan bank line, 0.01 float-drift GL line). The main build never loads them, so it stays green; loading them makes the circuit breaker fail on exactly those two MID-days (tested). | Stated |
| 5 | MDM matching is a deterministic ladder (valid ID anchor, then name-compatible + shared phone with exactly one candidate), not a probabilistic score. Name compatibility compares within one script only (Arabic with Arabic, English with English) and allows initials; there is no Arabic-English transliteration. | Stated |
| 5 | Resolution runs on the Spark driver over decrypted records held in memory only (about 4K records here). That is fine up to roughly a million parties; beyond that, blocking and candidate generation would move into Spark. | Stated |
| 5 | Silver keeps no name search key in clear: identifiers, phones and SPL short addresses are stored as keyed HMACs, and the surviving legal name is the untouched Bronze ciphertext of the source record (a crypto-shred of that subject also blinds the golden name). | Stated |
| 5 | The 700 Unified Number is validated by format only (no public checksum is claimed). Organisations anchor on VAT first, then 700. | Stated |
| 5 | Umm al-Qura dates come from Microsoft's .NET `UmAlQuraCalendar` (Windows), exported once by `scripts/build_hijri_seed.py` into a committed dbt seed (version `UAQ_DOTNET_V1`). The announcement-override seed is shipped **empty**: no real moon-sighting announcement is claimed; the override mechanism is proven with a test-only row. | Stated |
| 5 | SPL short addresses are checked for the 4-letters + 4-digits format only; they are not verified against the SPL address service. | Stated |
| 6 | Erasure is crypto-shredding: Bronze/Silver rows for an erased person stay as ciphertext without a key; they are not physically deleted, so statutory totals stay identical. The only residual window is OneLake's platform soft-delete of vacuumed files (on Fabric; verify the current retention default), and locally nothing is retained after `VACUUM RETAIN 0 HOURS`. | Stated |
| 6 | The "restore" in tests is simulated two ways: copying a pre-erasure backup of the vault table over the live one, and `RESTORE TABLE ... TO VERSION AS OF` on Silver. A OneLake/Fabric platform-level workspace restore was not exercised. | Stated |
| 6 | NDMO tiers come from ordered, versioned column rules (`NDMO_RULES_V1`), not from a regulator-issued catalog. The 6 quality dimensions use thresholds chosen for this dataset. The residency gate checks declared zones and regions; the Fabric trial capacity's actual region is whatever the tenant's home region is and is not claimed to be in KSA. | Stated |
| 6 | The legal-hold class of a DSR defaults to TAX when the person has invoices, else CONSENT; real retention periods (years) are not modelled, only the decision. | Stated |
| 9 | The governed AI is a **deterministic local stand-in**, not a language model: lexical TF-IDF retrieval over policy chunks and fixed SQL templates over Gold. It proves the guardrails (tier/ACL inheritance, entitlement filtering before ranking, tombstone suppression, money only from read-only Gold SQL, audited refusals). The Fabric Data Agent is configured over the same Gold marts in Phase 10. | Stated |
| 9 | Policy documents in `docs/policies/` are short synthetic examples written for this project, not real company policies. | Stated |
| 9b | Streaming events are a replay of the generated data. Invoice outcome latencies are synthetic seconds; the 26-hour late report for IR-0000102 is a scenario placed to exercise the SLA rule. The velocity/mule-ring alerts come only from an explicitly injected, labelled burst (`REPLAY_INJECTED`). KQL rules are named velocity rules, not SAMA controls. | Stated |

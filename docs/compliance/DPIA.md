# Data Protection Impact Assessment — MIZAN-KSA

**Status: self-assessed, not legally reviewed.** No Saudi data protection lawyer has read this, and no
external audit has been performed. For a regulated system a self-assessment is a starting point, not
evidence. It is written anyway, because "we have not thought about it" and "we thought about it and here is
the reasoning" are different positions, and the second one can be checked.

| | |
|---|---|
| **Assessment date** | 2026-11-20 |
| **System** | MIZAN-KSA, a commerce-to-ledger reconciliation and e-invoicing reference platform |
| **Assessor** | the project owner (sole engineer) |
| **Reviewed by** | nobody — see *Residual risks* |
| **Applicable law** | Saudi PDPL and its Implementing Regulations; ZATCA e-invoicing (Phase 2); NDMO data classification |
| **Data in this deployment** | **synthetic throughout.** No real person's data has ever been processed. |

The last row matters for reading everything below: the controls described are implemented and tested, but
they have been exercised only against invented people. A DPIA for a live deployment would need redoing
against the real data flows, the real retention obligations and the real processors.

---

## 1. What the system does, and why it needs personal data

MIZAN follows a retail sale through four systems — point of sale, ZATCA e-invoice, bank settlement, and the
general ledger — and proves the money agrees to the halala.

Personal data is needed for exactly two purposes:

| Purpose | Why personal data is unavoidable |
|---|---|
| **Issuing a compliant tax invoice** | ZATCA requires buyer identification on standard (B2B) invoices. A legal obligation, not a choice. |
| **Resolving one customer across systems** | The same person appears in the POS, the e-commerce site and the CRM under different spellings. Without resolution, a reconciliation cannot attribute a refund to the sale it reverses. |

**It is not used for:** marketing, profiling, credit decisions, automated decisions with legal effect, or
sharing with third parties. There is no advertising identifier and no behavioural tracking anywhere in the
platform.

---

## 2. What is held

| Category | Examples here | NDMO class | Where |
|---|---|---|---|
| Identity | name (Arabic and English), national ID / Iqama | TOP SECRET | `brz`, `slv` (encrypted at rest from the Bronze write) |
| Contact | phone, email, address | SECRET | `brz`, `slv` (encrypted) |
| Transaction | order, amount, payment method, merchant, timestamp | CONFIDENTIAL | `brz`, `slv`, `gld` |
| Tax document | signed invoice XML, invoice hash, ICV chain | CONFIDENTIAL | `audit.zatca_chain_journal` (binary, legal hold) |
| Derived | golden party record, match decisions | SECRET | `slv.golden_party_scd2` |

**Not collected at all:** payment card numbers (PAN), CVV, biometric data, health data, religious or
political data, precise geolocation. A card payment is represented by its scheme, its amount and a masked
reference; the PAN never enters the platform, so there is no PCI scope.

---

## 3. Lawful basis

| Processing | Basis under PDPL |
|---|---|
| Issuing and reporting tax invoices | Compliance with a legal obligation (ZATCA e-invoicing) |
| Retaining invoices for the statutory period | Compliance with a legal obligation (tax law) |
| Reconciling payments to the ledger | Legitimate interests of the controller — detecting misposted or missing funds |
| Resolving customer identity across systems | Legitimate interests, narrowly: only to attribute transactions correctly |

**Consent is not relied on** for any of the above, which is deliberate: consent that can be withdrawn is the
wrong basis for a record you are legally required to keep, and offering a choice you cannot honour is worse
than not offering it.

---

## 4. Data minimisation, and where it is enforced in code

Minimisation claims are cheap. These are the ones with a test behind them:

- **PII is encrypted at the Bronze write**, not in a later cleanup step. A per-subject AES-256-GCM key, with
  an HMAC-SHA256 token as the only link. There is no window in which cleartext sits at rest.
- **Gold holds no cleartext PII.** Enforced by `test_mdm_tables_hold_no_cleartext_pii` and
  `test_zatca_invoice_documents_hold_no_cleartext_buyer_pii`, which fail the build rather than warn.
- **The AI index holds no personal data it is not entitled to**, and loses entitlement on erasure
  (`test_ai_case_notes_entitled_then_suppressed_after_erasure`).
- **The Ask MIZAN agent never receives personal data.** It sees Gold aggregates only — no Fabric token, no
  Gold row, no identity attribute leaves the tenant.
- **Classification is computed, not declared.** 350 columns across 27 tables are classified from versioned
  rules in code, and a residency gate fails the build if a SECRET column reaches a zone that may not hold it.

---

## 5. Retention and erasure — the conflict, and how it is resolved

**The conflict.** PDPL gives a data subject the right to erasure. Saudi tax law requires invoices to be kept
for years. Both apply to the same row.

**The resolution: crypto-shredding.**

1. Each subject's PII is encrypted under a key that belongs to that subject alone.
2. An erasure request **destroys the key**. The ciphertext remains and is permanently unreadable.
3. The **tax documents survive**, satisfying the retention obligation, with the token-to-identity link
   removed so they can no longer be attributed to a person.
4. A **tombstone** in `ctl.deletion_tombstones` records that the erasure happened, and when — proof of
   compliance that is not itself personal data.
5. **`VACUUM` with zero-hour retention** on the vault. Without this the deleted key is recoverable from Delta
   time travel and the erasure is theatre.
6. A **Restore Guard** attempts to resurrect the key from a backup and **must fail**. Tested against both the
   data tables and the vault.

**Measured:** one erasure removed 5 linked records and 5 keys, retained 25,001 tax documents, and the guard
confirmed the key could not be brought back.

**What is not implemented:** automated retention expiry. Nothing deletes a tax document when its statutory
period ends; that is a manual decision today. Stated rather than implied.

---

## 6. Cross-border transfer — an unresolved finding

**PDPL restricts transferring personal data outside the Kingdom.**

`config/residency_policy.yml` declares `region: KSA` for every zone. **The capacity actually runs in UAE
North**, because that is the nearest region offered on the available Fabric capacity. The residency gate
checks a column's classification against its zone; **it does not check the physical region**, so it does not
catch this.

For this deployment the exposure is nil — the data is synthetic. **For a real deployment this is blocking**,
and the remedies are, in order of preference:

1. Deploy on a Fabric capacity in a Saudi region.
2. Extend the gate to compare the declared region against the capacity's actual region and fail on mismatch.
3. If neither is possible, an adequacy or safeguards assessment under the Implementing Regulations before any
   real personal data is processed.

This is `HONESTY.md` row 23 and it is not softened here.

A second transfer exists and is narrower: the Ask MIZAN agent calls Azure OpenAI, whose Global Standard
deployment may process a request outside the UAE. **Only Gold aggregates are sent** — no identity attribute,
no row-level personal data — so no personal data crosses a border by this path.

---

## 7. Security measures

| Risk | Control | Verified by |
|---|---|---|
| PII readable at rest | AES-256-GCM per subject, encrypted at the Bronze write | `test_encoding_crypto.py` |
| Key compromise reveals everything | One key per subject; compromise is bounded to one person | by design |
| Erasure reversible by restore | `VACUUM RETAIN 0 HOURS` plus Restore Guard | `test_panel2_vault_time_travel_cannot_return_the_key` |
| Over-exposure of classified data | Residency and classification gate fails the build | `test_residency_gate_passes_on_real_lake_and_gold` |
| Secrets in source control | `.env` is git-ignored; CI secret scanning; no credential in any synced file | `test_fabric_airflow_dag.py` |
| API keys stolen | Azure OpenAI keys disabled; managed identity only | deployment configuration |
| Unauthenticated API access | **Entra token verification implemented** (`entra_auth.py`, 16 attack tests) but **shipped off** — see below | `test_entra_auth.py` |
| Tampered tax chain | ICV hash chain plus `verify_chain`, violations quarantined | `test_zatca_chaos.py` |

**The open one.** The Ask MIZAN Function ships with token verification disabled, because the app cannot yet
obtain a token it would accept (ADR-013: different directories, Entra error 530035). Today an `Origin` header
is the only check and an `Origin` header is forgeable. The blast radius is bounded by design — no Fabric
token, no Gold row and no personal data passes through, rate limits of 20/minute and 600/day apply, and a USD
5 budget alert caps the cost — so the exposure is Azure credit, not data. **It must be switched on before any
real tenant**, and the code to do so exists and is tested.

---

## 8. Data subject rights

| Right | Status |
|---|---|
| Access | Partial — data is retrievable by subject token, but there is no self-service portal |
| Rectification | Supported — a correction lands as a new Bronze version; Silver takes the latest |
| **Erasure** | **Implemented and tested**, including the restore case |
| Restriction | Not implemented |
| Portability | Not implemented |
| Object to processing | Not implemented — processing is legal obligation and legitimate interest, but an objection route should still exist |

Four of six are absent. For a reference architecture that is a reasonable scope; for a live system it is not,
and nothing here should be read as claiming otherwise.

---

## 9. Residual risks

Ranked by what would actually hurt first in a real deployment.

| # | Risk | Severity | Status |
|---|---|---|---|
| 1 | Data residency declared KSA, capacity runs UAE North | **High** | Open — `HONESTY.md` row 23 |
| 2 | Agent API has no caller authentication in the shipped configuration | **High** | Code exists and is tested; disabled pending a token the app can obtain |
| 3 | No legal review, no DPIA sign-off, no external audit | **High** | Open — needs a Saudi data protection practitioner |
| 4 | Four of six subject rights unimplemented | Medium | Open |
| 5 | No automated retention expiry | Medium | Open |
| 6 | Classification rules are the author's, not a regulator-issued catalogue | Medium | Stated — `HONESTY.md` |
| 7 | One engineer; nobody else has reviewed the privacy design | Medium | Open — bus factor of one |
| 8 | No breach notification procedure or timeline | Medium | Open — not drafted |
| 9 | Only synthetic data has ever been processed | Low here, High on go-live | By design |

---

## 10. Conclusion

**Proceed for a synthetic-data reference deployment.** The privacy engineering — encryption at the Bronze
write, crypto-shredding, the restore guard, computed classification — is implemented and tested, and in
several respects is ahead of what a typical production system does, particularly the erasure-survives-restore
property.

**Do not proceed with real personal data** until risks 1, 2 and 3 are closed: a Saudi region or a documented
transfer safeguard, caller authentication switched on, and a review by somebody qualified who is not the
author.

**Review when:** real data is introduced, the region changes, the agent gains access to anything below Gold
aggregate level, or a new category of personal data is collected. Otherwise annually.

---

### Record of processing (summary)

| | |
|---|---|
| Controller | the deploying organisation (this deployment: none — synthetic data) |
| Processors | Microsoft (Fabric, Azure OpenAI) |
| Categories of subject | retail customers, merchant staff |
| Categories of data | identity, contact, transaction, tax document, derived golden record |
| Recipients | ZATCA (tax authority), the acquiring bank, the organisation's finance function |
| Transfers | UAE North (see section 6); Azure OpenAI Global Standard for Gold aggregates only |
| Retention | tax documents per statutory period; all other PII until erasure |
| Security | per-subject AES-256-GCM, managed identity, classification gate, build-failing tests |

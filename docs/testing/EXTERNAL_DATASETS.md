# Testing MIZAN against data it did not author

The strongest criticism of this project is that the generator invents the defects and the pipeline detects
them, so passing proves only that the two agree. Every edge case handled is one that was already imagined.

This document lists public datasets that break that circle, one per module, with what each one **can** and
**cannot** prove. The second half matters more than the first.

**Nothing here is Saudi retail data.** No such public dataset exists, and that is not a gap this file can
close — see "What none of this fixes" at the end.

---

## 1. Reconciliation — BenchRec (obtained, analysed)

**[BenchRec: A Real-World Cash Reconciliation Dataset](https://www.kaggle.com/datasets/benchmarkteam/benchrec-real-world-cash-reconciliation-dataset)**
· ICAIF 2023 Benchmark Competition · Tier 1 bank · **CC BY 4.0** · 149,854 rows

Real bank statement lines paired with internal ledger lines across 56,074 reconciliation matches. One USD
account, 2022-2023, counterparty names anonymised, amounts and dates real.

**Measured on 2026-11-22, against assumptions this project had written down:**

| | |
|---|---|
| Matches that are one-to-one | **47,024 of 56,074 — 83.9%** |
| Matches that are **not** one-to-one | **16.1%** (2:2, 2:1, 3:1, 6:6, 9+:9+, and 3,102 groups of 2:0) |
| Matched by a rule | 83.1% |
| **Matched by a human** | **9,330 groups — 16.6%** |

**What it proves.** `assert_every_settled_line_matches_its_payment` assumes one bank line per payment event.
HONESTY row 19 already called that this project's contract rather than every acquirer's -- it was a
hypothesis, and it is now a measurement: the assumption holds about **84%** of the time in real bank data.

And a second thing nobody had written down: **roughly one in six real reconciliation matches is made by a
person, not a rule.** This pipeline has two states for the bank leg -- it balances, or the circuit breaker
trips. Real systems have a third: *a rule could not do this, queue it for review*. That queue exists here
for Arabic name matching (the MDM steward queue) and not for settlement.

**What it does not prove.** BenchRec is *fuzzy record linkage with no shared key* -- its own data card says a
match is correct "even if the internal transaction IDs differ". MIZAN reconciles on an **exact** key,
`payment_event_id`, because acquirer settlement files carry the transaction reference by contract. These are
different problems. BenchRec cannot be run through MIZAN's reconciler, and claiming otherwise would be
false. It is evidence about an assumption, not a test of the engine.

---

## 2. ZATCA / e-invoicing — Peppol UBL corpora

- **[StanzaAPI/peppol-test-data](https://github.com/StanzaAPI/peppol-test-data)** — well-formed UBL invoices,
  Peppol BIS Billing 3.0, synthetic parties, **CC0-1.0**.
- **[OpenPEPPOL/peppol-bis-invoice-3](https://github.com/OpenPEPPOL/peppol-bis-invoice-3)** — the
  authoritative BIS 3 structure and rules.
- **[BaseInvoice](https://www.baseinvoice.eu/en/samples)** and
  **[efacturatieontcijferd](https://www.efacturatieontcijferd.be/en/test-invoices/)** — sample sets that
  include **deliberately invalid** files, built to break validators.

**Why this is the most interesting one.** The deliberately invalid files were broken by people who have
never seen this project. Running them through the UBL reader and the hardened parser tests whether it
rejects what it should and accepts what it should -- against somebody else's idea of malformed.

**The honest limit.** Peppol BIS 3 is **EN 16931**, the European standard. ZATCA Phase 2 *extends* EN 16931
with Saudi rules (BR-KSA-*), the invoice hash chain, the PIH, the QR TLV and the ICV. So these files share
the UBL 2.1 skeleton and the EN 16931 core, and have **none** of the Saudi-specific machinery. They test the
parser and the base rules. They cannot test the chain, the QR, or anything BR-KSA.

---

## 3. Arabic identity matching — real transliteration pairs

- **[Sayedyousef/arabic-name-pairs](https://huggingface.co/datasets/Sayedyousef/arabic-name-pairs)** —
  22,798 English-to-Arabic name pairs, **CC BY 4.0**.
- **[ANETAC](https://arxiv.org/pdf/1907.03110)** — 79,924 English-Arabic named-entity pairs from parallel
  corpora, with a test split.

**Why it matters here.** The MDM ladder scores precision 1.0000 / recall 0.9625 against *this project's own*
answer key, built by the same author as the matcher. These pairs were written by other people, from real
text, with the spelling variation that real transliteration produces.

**The honest limit.** They are *transliteration* pairs (English name ↔ Arabic name), not *duplicate-record*
pairs. They do not come with the national IDs, phones and addresses the ladder actually keys on. The honest
use is narrow and still worth doing: feed the Arabic side through `arabic_norm` and check that genuine
variants of one name normalise together — a direct test of the normaliser, not of the whole ladder. No
public Arabic **record-linkage** benchmark was found; the search suggests one may not exist.

---

## 4. General ledger — a real public ledger

**Oklahoma State Government Open Data Platform** publishes its general ledger as quarterly CSV under
**CC BY**. A real ledger, from a real organisation, with real posting behaviour.

Academic SAP extracts exist (e.g. [arXiv 1709.05254](https://arxiv.org/pdf/1709.05254), 307,457 and 172,990
line items from real SAP ERP systems) but the data is **not published** — those would need an email to the
authors.

**What it can prove.** The GL contract reader (`ERP_GL`, ACDOCA-shaped) assumes a particular column set and
that `HSL` is positive with the sign carried by `DRCRK`. A real government ledger will not look like that,
which is the point: it shows how much of the reader is SAP-specific rather than ledger-generic.

**The honest limit.** Government fund accounting is not retail card clearing. It cannot exercise the
three-way spine.

---

## 5. PDPL / PII classification — labelled sensitive data

- **[Nemotron-PII](https://huggingface.co/blog/nvidia/nemotron-pii)** (NVIDIA) — 100K synthetic records with
  span-level annotations, **CC BY 4.0**.
- **[Protegrity PII-SCOPE](https://huggingface.co/datasets/Protegrity/pii-scope)** — 8,030 documents,
  114,887 labelled PII spans, 69 entity types, CSV.
- **[REDACT-PII-Benchmark](https://huggingface.co/datasets/guneeshv/REDACT-PII-Benchmark)** — 13,427 records,
  51 entity types, 25 languages (licence listed as "other" — check before use).

**The honest limit, and it is a large one.** These are all **span-level detection in free text** — finding a
name inside a sentence. `governance/catalog.py` does **column-level classification by rule**: it decides
that a column called `national_id` is SECRET because a rule says so. Those are different tasks. No
column-labelled public benchmark for tabular sensitive-data discovery was found; a 2025 paper describes one
but does not appear to have released it.

The usable test is narrow: take the entity types these datasets label, and check whether the rule set in
`COLUMN_RULES` would classify a column holding each type correctly. That tests **coverage of the rule set**
against someone else's taxonomy, which is worth knowing and is not what the project claims today.

---

## What none of this fixes

**No public dataset exists for acquirer settlement files or Saudi e-invoices.** Settlement files contain
merchant IDs, MDR rates and fee structures — commercially sensitive, so no bank publishes them. ZATCA
documents are tax records. This is not an oversight in the search; it is a property of the domain.

So the **three-way spine** — payments × settlement × GL, reconciled to the halala — has no public equivalent
anywhere. That is simultaneously why the project is interesting and why it cannot be validated on real data
without a real merchant.

**The strongest honest claim available is therefore:**

> *Individual assumptions have been tested against real third-party data and quantified. The end-to-end
> reconciliation has not, because the data for it does not exist publicly, and I know the difference.*

A blind-adversary generation round (`EXTERNAL_DATA_CONTRACT.md`) gets the remaining property — defects
chosen by someone else — without pretending to be real data.

---

## Order of work, by value

| | Dataset | Tests | Effort |
|---|---|---|---|
| 1 | **BenchRec** | the one-to-one assumption | **done** |
| 2 | **Peppol invalid invoices** | the UBL reader against someone else's malformed files | low |
| 3 | **Arabic name pairs** | the normaliser against real transliteration variation | low |
| 4 | **Oklahoma GL** | how SAP-specific the GL reader is | medium |
| 5 | **Nemotron-PII** | coverage of the classification rule set | medium |

Licences: BenchRec CC BY 4.0, Peppol test data CC0, Arabic name pairs CC BY 4.0, Oklahoma GL CC BY,
Nemotron-PII CC BY 4.0. All attributable and usable. **None of it is committed to this repository** —
`data/external/` is git-ignored, because the licence is somebody else's to grant and the entire point of
these files is that this project did not author them.

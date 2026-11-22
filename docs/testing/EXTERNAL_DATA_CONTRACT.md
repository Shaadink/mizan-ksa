# Generate a month of Saudi retail data — brief for an outside author

**Give this file to someone who has not seen the receiving system's code.** Another AI, or a person. That is
the entire point: the irregularities in the data must be chosen by somebody who does not know what the
receiving system checks for.

This document deliberately does **not** describe what is validated downstream, what the reconciliation rules
are, or which conditions raise an error. Do not tell the author. If they ask, do not answer.

---

## Why this exists

The strongest criticism of a data platform tested on its own generated data is that the author invented both
the defects and the detector, so passing proves only that the two agree. Every edge case handled is one that
was already imagined.

Real production data has one property that cannot be manufactured by the same hand: **someone else decided
what goes wrong.** This brief buys that property by moving the decision to a different author.

Whatever the receiving system fails to handle is a genuine finding. That is the deliverable.

---

## The scenario

A retail chain in Saudi Arabia. Around 20 stores across Riyadh, Jeddah and Dammam, plus an e-commerce
channel. Customers pay by card — **mada** (the Saudi domestic debit scheme, the majority of transactions),
Visa, Mastercard, and buy-now-pay-later (Tamara, Tabby). **Twenty consecutive trading days.**

Five separate systems record pieces of the same month, and each sees it differently:

1. **Orders** — the commerce platform.
2. **Payments** — the card transaction at the till.
3. **The acquiring bank** — pays the merchant a day or two later, minus fees.
4. **The ERP** — posts journal entries to the general ledger.
5. **CRM and the national address service** — who the customer is, and where they live.
6. **The tax system** — one e-invoice request per sale, for the Saudi tax authority.

Produce all of it. Seven files.

---

## Saudi context the data should reflect

- **Currency** SAR. The minor unit is the **halala**: 1 SAR = 100 halalas. Two decimal places.
- **VAT is 15%.**
- **The weekend is Friday and Saturday.** Bank behaviour differs around it.
- **Timezone Asia/Riyadh (UTC+3).** Decide for yourself whether each file uses local or UTC, and whether the
  files agree with each other about that.
- **mada** usually carries lower merchant fees than international schemes.
- Evenings are busier than mornings. The week around the **27th** (government payday) is busier.
- **Saudi national IDs** are 10 digits beginning with 1 (citizen) or 2 (resident/iqama).
- **VAT numbers** are 15 digits beginning and ending with 3.
- **National Short Address** is 4 letters + 4 digits, e.g. `RRRD2929`.
- Arabic names are written many ways: with and without `al-`, with or without the honorific `Abu`, different
  spacing, different forms of the same letter, and sometimes with Arabic-Indic digits (`٠١٢٣`).

---

## File 1 — `orders/commerce_events.csv` (UTF-8)

One row per order or return.

```
event_id, event_type, order_id, return_id, channel, store_id, register_id,
merchant_id, customer_ref, buyer_name, buyer_mobile, delivery_short_address,
payment_means, amount_sar, event_ts_utc
```

`event_type` is `ORDER_PLACED` or `RETURN_REQUESTED`. `channel` is store or e-commerce.

## File 2 — `payments/payment_events.csv` (UTF-8)

One row per card transaction.

```
payment_event_id, event_type, order_id, invoice_uuid, credit_note_uuid,
merchant_id, store_id, register_id, payment_scheme, amount_sar, currency, event_ts_utc
```

`event_type` is `CAPTURE`, `REFUND` or `CHARGEBACK`. `payment_scheme` is `MADA`, `VISA`, `MASTERCARD`,
`BNPL` or `SADAD`. Amounts positive; the direction lives in `event_type`.

## File 3 — `settlement/NAJDACQ_SETTLEMENT_<YYYYMMDD>.csv` (UTF-8, one file per payout date)

What the acquiring bank actually paid.

```
settlement_batch_id, payout_date, merchant_id, payment_event_id, txn_type,
card_scheme, txn_ts_ksa, settlement_for_date, gross_amount, mdr_fee,
vat_on_fee, net_amount, dr_cr
```

`txn_type` is `PURCHASE`, `REFUND` or `CHARGEBACK`. `dr_cr` is `CR` (money to the merchant) or `DR` (taken
back). `mdr_fee` is the bank's fee; `vat_on_fee` is VAT on that fee. `settlement_for_date` is the trading
day the line pays for, which is not the same as `payout_date`.

## File 4 — `erp/erp_gl_acdoca.csv` (UTF-8)

SAP ACDOCA-style journal lines.

```
RLDNR, RBUKRS, GJAHR, BELNR, DOCLN, BUDAT, BLDAT, RACCT, DRCRK, HSL,
RHCUR, PRCTR, ZZ_STORE_ID, ZZ_MERCHANT_ID
```

`DRCRK` is `S` (debit) or `H` (credit). `HSL` is the amount, positive, with the sign carried by `DRCRK`.
`BUDAT` is the posting date, format `YYYYMMDD`. Typical accounts: cash on hand, **card clearing** (money
owed by the acquirer), revenue, VAT output, chargeback losses.

## File 5 — `crm/crm_pos_cp1256.csv` (**encoded in Windows CP1256, not UTF-8**)

Customer records from the in-store system — an older application that still writes CP1256.

```
source_customer_id, party_type, full_name_ar, full_name_en, national_id,
mobile, landline, vat_number, unified_700, spl_short_address, city, created_date
```

## File 6 — `crm/crm_ecom_utf8.csv` (UTF-8)

Customer records from the e-commerce platform. A different system, so different conventions.

```
source_customer_id, party_type, full_name_ar, full_name_en, national_id,
mobile, landline, email, spl_short_address, city, created_date
```

**Some customers appear in both files.** They are the same people. Nothing marks them as the same.

## File 7 — `crm/spl_address_observations.csv` (UTF-8)

Address sightings from the national address service.

```
observation_id, source_system, source_customer_id, short_address,
building_number, secondary_number, district, city, postal_code, observed_date
```

## File 8 — `zatca/invoice_requests.jsonl` (UTF-8, one JSON object per line)

One **unsigned** e-invoice request per sale. The receiving system signs and chains these; you only produce
the request.

```json
{
  "request_id": "...", "invoice_uuid": "...", "egs_id": "EGS-01",
  "document_type": "INVOICE" | "CREDIT_NOTE",
  "invoice_flow": "REPORTING" | "CLEARANCE",
  "billing_reference_uuid": null,
  "order_id": "...", "merchant_id": "...", "store_id": "...", "register_id": "...",
  "customer_ref": "...", "buyer": null,
  "issue_ts_utc": "2026-02-13T09:14:22Z",
  "payment_means": "MADA",
  "seller": {
    "name": "...", "name_ar": "...", "vat_number": "3...3", "cr_number": "...",
    "address": { "street_ar": "...", "building_number": "1234", "additional_number": "5678",
                 "district_ar": "...", "city_ar": "...", "postal_zone": "12345",
                 "region_ar": "...", "country_code": "SA" }
  },
  "lines": [
    { "line_id": 1, "item_en": "...", "item_ar": "...", "qty": 1,
      "unit_price_sar": "120.00", "line_net_sar": "120.00",
      "vat_rate": "15.00", "line_vat_sar": "18.00" }
  ],
  "total_excl_vat_sar": "120.00", "vat_total_sar": "18.00", "total_incl_vat_sar": "138.00"
}
```

Notes for this file:
- `egs_id` identifies which till/device issued it. Use several; each is a separate stream.
- `invoice_flow` — consumer sales are `REPORTING` (simplified), business sales are `CLEARANCE` (standard).
- A `CREDIT_NOTE` references the invoice it corrects via `billing_reference_uuid`.
- Amounts are strings with two decimals.

---

## The important instruction

**Make it behave like real data, not like clean data.**

You are not being asked to plant a list of bugs from a checklist. You are being asked to produce what these
systems would genuinely look like after a month in a real business — including everything that makes a
finance team's life difficult.

Think about what actually happens in organisations:

- Systems disagree, because different vendors built them in different decades.
- Files arrive late, early, twice, or half-written.
- People mistype things at tills and in back offices.
- Banks batch, net, split and delay things for their own reasons.
- Dates mean subtly different things in different systems.
- Months end in the middle of processes that take days to finish.
- The same person is recorded differently by two systems that never spoke to each other.
- Old systems write old encodings, and something mangles the characters on the way.

**Use your own judgement about what realistic trouble looks like.** Do not ask what the receiving system
checks for. Do not aim to break it, and do not aim to please it. Aim to be realistic.

A dataset in which all seven files agree perfectly is neither realistic nor useful here.

---

## What to hand back

1. **The seven files**, in the folder layout shown above.
2. **A sealed note — kept back until after the first run** — listing every irregularity you deliberately
   introduced, and anything you suspect you introduced by accident.

Point 2 is the measurement. Once the receiving system has processed the files and reported what it found,
the two lists are compared:

| | |
|---|---|
| In your note, and found | detection worked |
| **In your note, not found** | **a real gap. The most valuable outcome here** |
| Found, not in your note | your accident, or a false positive. Both worth knowing |

Please do not reveal the note early. Its value depends entirely on arriving second.

---

## Scale

Enough to be realistic, small enough to inspect by hand when something looks odd:

| | |
|---|---|
| Card transactions | 10,000–20,000 |
| Orders | similar, plus returns |
| Customers | 2,000–4,000, with some appearing in both CRM files |
| Settlement files | one per payout date across the month |
| GL lines | enough to cover every store, day and account |
| Invoice requests | one per sale |

---

## One thing to get right

The seven files describe **the same month of the same business**. A payment should correspond to an order,
a settlement line to a payment, a journal entry to a day's trading, an invoice request to a sale.

Where they do **not** correspond, that should be because something realistic happened — not because the
files were generated independently and never reconciled. Generating seven unrelated files is the one way to
make this exercise worthless.

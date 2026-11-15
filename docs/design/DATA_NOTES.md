# Data notes (Stage 1 "Fix first")

Every figure below is computed by `scripts/build_command_center.py` (section `truth`) from the dbt Gold tables, with
Silver used only for the card-payment link. Each bug has a test in `tests/test_stage1_truth.py`.

## 1. ZATCA ledger: 25,001 documents, not 25,000

`gld.fact_zatca_clearance_ledger` kept only accepted states, so the HTTP 400 `CONFIRMED_REJECTION` (ICV 103,
IR-0000103, SAR 1,987.10) disappeared from Gold although it stays in the legal chain. The model now keeps every
document with a definitive outcome: REPORTED 23,913 + CLEARED 1,087 + CONFIRMED_REJECTION 1 = **25,001**, the same
count as the ZATCA engine run and the signed journal. "Accepted" figures filter the rejection out explicitly
(Power BI `Accepted Documents`, `Rejected Documents`, `Documents in Chain`). No column was added.

## 2. Tax SAR 30.92M vs gross captures 22.39M

They measure different things, and they reconcile exactly:

| Part (accepted documents, SAR incl. VAT) | SAR |
|---|---|
| Invoices paid by card (a CAPTURE in `slv.payment_lifecycle`) | 22,390,730.16 |
| Invoices paid in cash (no card capture) | 7,545,182.44 |
| Credit notes (stored as positive amounts; `document_type` carries the sign) | 981,929.16 |
| **Total of accepted documents (old "Documents Total SAR")** | **30,917,841.76** |
| Net invoiced = card + cash - credit notes | 28,953,983.44 |

Card-paid invoices equal gross captures (22,390,730.16) to the halala. One subtlety: the rejected invoice's card
capture keeps the **original** invoice UUID, so its correction (ICV 104, SAR 1,987.09) is linked to the payment
through `corrects_invoice_uuid`. The old card total "Documents Total SAR" added credit notes as if they were sales;
the report now shows `Invoices SAR`, `Credit Notes SAR` and `Net Invoiced SAR`.

## 3. EGS-05 = MID900001

From Silver (invoice UUID joined to the payment's merchant): EGS-01..04 each serve 30 POS merchants
(MID100001..MID100120); **EGS-05 serves only MID900001**, the e-commerce merchant (Riyadh). No other device issues
documents for MID900001.

## 4. "Not assessed" MID-days

A MID-day is **not assessed** when its bank file has not arrived: `in_transit_sar <> 0` (not `> 0`: six 3 March
MID-days have negative in-transit because refunds exceeded captures). Result: **112 MID-days, all on 2026-03-03**, no
bank payment on any of them; 2,121 MID-days are assessed. Bank and GL variance are 0.00 on the assessed MID-days;
the 112 are shown as "Awaiting bank file", never as balanced. Power BI: `Bank Paid SAR (Assessed)` is blank (not
0.00) on that day, plus `MID Days Assessed` / `MID Days Not Assessed`. Exposed as measures and in the export, not as
a new Gold column (adding `assessment_status` to `gld.fact_merchant_settlement_recon` would need your approval).

## 5. 73.8% vs 65%

- MID900001 holds **73.8% of gross captured SAR** in the reconciliation (16.5M of 22.39M).
- The Spark skew benchmark is a separate synthetic test that puts **65% of 20 million rows** on one key
  (`src/mizan/spark/skew.py`, `mega_share=0.65`). Both are now labelled with what they measure.

## 6. NDMO: 27 / 27 / 27 and 6 vs 7 and 99.07%

- The classification donut used `CALCULATE(..., NOT ISBLANK(table_classification))`. A plain filter inside
  CALCULATE **replaces** the donut's own filter on that column, so every slice counted all 27 tables. Real split:
  CONFIDENTIAL 17, PUBLIC 1, SECRET 6, TOP_SECRET 3. Every measure filter is now wrapped in `KEEPFILTERS`.
- "6 passing" was data-quality only; "7 PASS" also counted the one classification table that passes
  (`ctl.ingestion_watermarks`). One shared `Checks Passing` measure now feeds `Data Quality Checks Passing` (6/6)
  and `Classification Checks Passing` (1/27).
- 99.07% is the average of the six data-quality scores only; the classification score is separate.

## 7. Published vs candidate run

- **Published run**: the last main dbt build (`dbt/target/run_results.json`: run id, time, 65 nodes, PASS) and the
  Fabric run (65/65 PASS, 2026-11-14).
- **Candidate run**: the demo-flag build with the two planted defects; the circuit breaker failed it (2 unexplained
  MID-days), so it was never published (`docs/artifacts/html/02_halala_recon_board.html`).
- Both, plus the git SHA, are in the export (`runs`) and the Command Center footer.

## 8. Store city for the map: proposal (waiting for your decision)

Store city **exists only in the generator's reference file** `data/generated/reference/merchants.csv`
(merchant_id, store_id, channel, egs_id, city, register_count): 120 POS stores across Riyadh, Jeddah, Dammam, Makkah
and Madinah, plus MID900001 (ECOM, Riyadh). It is not landed in the lakehouse or Gold (the `city` in
`dim_party_golden` is the customer's address, not the store's).

Smallest change: add `merchants.csv` as one **dbt seed** `merchant_store_reference` (5 columns, 121 rows, no PII),
with tests (unique `merchant_id`, accepted `channel`, accepted `city`), read by the map only. No existing table or
column changes. The map's money routes (store, acquirer, bank) can then be drawn from the existing recon facts.
**This adds a seed table, so it needs your yes.**

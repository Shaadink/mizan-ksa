# Portal steps (only what the Fabric REST API could not do)

Everything else in Phase 10 was created and run by script: workspace, LH_MIZAN (schemas), WH_MIZAN, EH_MIZAN,
ES_MIZAN, the service principal, all notebook jobs, `dbt build` on WH_MIZAN, the KQL objects, the Eventstream
topology, the Direct Lake semantic model and the 3-page report. Sign in at https://app.fabric.microsoft.com with the
account that owns the workspace `mizan-ksa-dev`.

## 1. Eventstream -> Eventhouse delivery (about 3 minutes)

Status when written: ES_MIZAN accepted all 91,513 replayed events (custom endpoint), the topology reports source,
stream and Eventhouse destination as Running, and `EH_MIZAN.MizanEvents` exists with its JSON mapping, but no rows had
arrived after several probes. The portal shows destination errors and a data preview that the API does not expose.

1. Workspaces -> `mizan-ksa-dev` -> open **ES_MIZAN**.
2. Click the stream node **ES_MIZAN-stream** -> **Data preview**. You should see the replay events (JSON). If the
   preview is empty, re-send: `.\.venv\Scripts\python.exe scripts\fabric_streaming.py replay`.
3. Click the destination **eh-mizan**. If it shows a warning/error, open it and read the message. The usual fixes:
   - **Edit** -> keep workspace `mizan-ksa-dev`, Eventhouse `EH_MIZAN`, KQL database `EH_MIZAN`, table
     **MizanEvents**, input format **JSON** -> **Save**, then **Publish** (top right).
   - If it asks to approve a connection to the KQL database, approve it.
4. After publishing, the custom endpoint keys may change: run
   `.\.venv\Scripts\python.exe scripts\fabric_streaming.py conn` then `... replay`.
5. Check: `.\.venv\Scripts\python.exe scripts\fabric_streaming.py check`. Expected: CHECKOUT 23,511, INVOICE 50,002,
   PAYMENT 18,000; `VelocityAlerts()` 1, `MuleRingAlerts()` 1, `InvoiceReportingSlaBreaches()` 2.

## 2. Fabric Data Agent (needs a paid capacity, about 3 minutes)

The API refused to create it on the trial: `UnsupportedCapacitySKU: FTL64 SKU Not Supported`. Microsoft allows data
agents only on paid capacities (F2 and above), with the tenant setting "Users can access Microsoft Copilot in Power BI
and Microsoft Fabric" on. On such a capacity:

1. Workspace `mizan-ksa-dev` -> **+ New item** -> **Data agent** -> name `MIZAN Data Agent`.
2. **Add data source** -> **WH_MIZAN** -> tick only the Gold tables `gld.fact_merchant_settlement_recon`,
   `gld.fact_zatca_clearance_ledger`, `gld.mart_ndmo_scorecard`, `gld.dim_date_saudi`. Do **not** add `dim_party_golden`
   or any Lakehouse schema (read-only over Gold, same allow-list as `mizan.ai.governed.GOLD_ACL`).
3. **Agent instructions** (paste): "Answer only from the selected Gold tables. Money values come only from SQL over
   these tables, never from text. Amounts are SAR with two decimals. If a question needs data outside these tables,
   say you cannot answer it."
4. **Example queries**: "What is the total unexplained bank variance?" -> `SELECT SUM(unexplained_bank_variance_sar)
   FROM gld.fact_merchant_settlement_recon`; "How many invoices were reported?" -> `SELECT COUNT(*) FROM
   gld.fact_zatca_clearance_ledger WHERE state = 'REPORTED'`.
5. **Publish**. Share it only with the finance/tax groups; users without access to WH_MIZAN are refused by Fabric.

Locally, the same guardrails (entitlement filter before retrieval, Gold-only money answers, audited refusals) are
proven by `tests/test_governed_ai.py` and `tests/test_pdpl_ndmo.py`.

## 3. Optional: review the Control Tower report (1 minute)

Workspace `mizan-ksa-dev` -> **MIZAN Control Tower** (report). The three pages (CFO Settlement, Tax ZATCA Health,
CDO Data Trust) were generated as PBIR. Layout is deliberately simple (cards + one table per page); resize or restyle
in **Edit** if you like. The semantic model **MIZAN Control Tower Model** is Direct Lake over WH_MIZAN.

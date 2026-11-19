# Portal steps (only what the Fabric REST API could not do)

Everything else in Phase 10 was created and run by script: workspace, LH_MIZAN (schemas), WH_MIZAN, EH_MIZAN,
ES_MIZAN, the service principal, all notebook jobs, `dbt build` on WH_MIZAN, the KQL objects, the Eventstream
topology, the Direct Lake semantic model and the 3-page report. Sign in at https://app.fabric.microsoft.com with the
account that owns the workspace `mizan-ksa-dev`.

## 1. Eventstream -> Eventhouse delivery (resolved 2026-11-15)

Rows did not arrive at first. The destination's **Runtime logs** (ES_MIZAN -> destination **eh-mizan** -> Runtime logs)
showed `Kusto output data error: Column amount_sar has invalid KQL Database column type decimal`: the Eventstream writer
cannot write KQL `decimal`. `amount_sar` now lands as exact text and `MizanEventsTyped()` converts it with `todecimal()`
(never float). After `fabric_streaming.py setup` + `conn` + `replay`, `check` returns CHECKOUT 23,511, INVOICE 50,002,
PAYMENT 18,000 and rule counts 1 / 1 / 2. If delivery ever stops again, read those runtime logs first.

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

## 4. The workspace task flow (5 minutes, portal only)

A **task flow** is the diagram across the top of a workspace. It is a label layer: it creates nothing, moves nothing
and runs nothing. It is worth five minutes because a workspace that opens with a labelled flow reads as a designed
platform rather than as a pile of eleven items.

There is no REST API for it. Probed on 2026-11-19 with the service principal:
`GET /v1/workspaces/{ws}/taskFlow`, `/taskflow` and `/taskFlows` all return 404 `EntityNotFound`, while
`/items` and `/folders` return 200. The portal uses an internal endpoint. So this is the one part of MIZAN that
cannot be scripted.

**One rule drives the whole design:** an item can be assigned to exactly one task
([Microsoft Learn](https://learn.microsoft.com/en-us/fabric/get-started/task-flow-work-with)). So the boxes cannot
be pipeline *stages* (the one notebook runs seven steps and would have to appear in four of them). They have to be
*groups of items*. Six boxes cover all eleven items with none repeated.

### 4.1 Clear the generic template

Fabric's **Apply predesigned task flow** drops in ten empty boxes (Get data, Mirror, Store, Prepare, Analyze and
train, Develop, Govern data, Visualize, Track, Distribute). MIZAN has no mirroring, no model training and no
distribution step, so most of them would stay empty and invite a question the project cannot answer.

Select a blank area of the canvas -> task flow details pane -> **trash icon** to delete the whole thing and start
clean. (Deleting a task flow never deletes items.)

### 4.2 Build six tasks

**Add** dropdown -> pick the task type -> select the task -> **Edit** -> set name and description -> **Save**.

| # | Name | Task type to pick | Description to paste |
|---|---|---|---|
| 1 | Ingest and build | Prepare | One notebook, seven steps: bronze_land, silver_build, mdm_resolve, zatca_chain, ai_index, ndmo_catalog, restore_guard. PII is encrypted at the Bronze write. |
| 2 | Store | Store | Lakehouse schemas brz, ctl, slv, quarantine, security, audit, meta, ai; Warehouse schema gld. |
| 3 | Stream | Get data | Eventstream to Eventhouse: velocity, mule-ring and reporting-SLA rules evaluated in KQL. |
| 4 | Model | Develop | Direct Lake semantic model over WH_MIZAN. No import, no refresh. |
| 5 | Report | Visualize | Three pages: CFO Settlement, Tax ZATCA Health, CDO Data Trust. |
| 6 | Command Center | Distribute | Fabric App front end and the data function behind it. |

Connectors (drag from the edge of one task to the next): 1 -> 2, 3 -> 2, 2 -> 4, 4 -> 5, 4 -> 6.

Then select the canvas -> **Edit** -> name the flow **MIZAN platform**, description
*"Payments reconciliation and ZATCA e-invoicing for Saudi Arabia. Every Gold figure traces to source."*

### 4.3 Assign the items

Click the **clip icon** on a task -> tick the items -> **Select**. All eleven workspace items, each used once:

| Task | Items |
|---|---|
| Ingest and build | `nb_mizan_step` (Notebook) |
| Store | `LH_MIZAN` (Lakehouse), `LH_MIZAN` (SQL endpoint), `WH_MIZAN` (Warehouse) |
| Stream | `ES_MIZAN` (Eventstream), `EH_MIZAN` (Eventhouse), `EH_MIZAN` (KQL database) |
| Model | `MIZAN Control Tower Model` (Semantic model) |
| Report | `MIZAN Control Tower` (Report) |
| Command Center | `command-center` (App backend), `command_center_connector` (User data function) |

The SQL endpoint and the KQL database are created automatically by the Lakehouse and the Eventhouse; if the portal
will not let you assign them separately, leave them out and the flow still covers everything.

### 4.4 Faster: import the flow as a file (done 2026-11-19)

`docs/fabric/mizan_task_flow.json` is the six-task flow above. Task flow details pane -> **Import and export task
flow** -> **Import** -> **Replace**. Imported successfully on 2026-11-19.

The schema was taken from a real export of Fabric's own predesigned flow, not invented:

```json
{"tasks":[{"type":"store data","id":"<uuid>","name":"Store"}],
 "edges":[{"source":"<uuid>","target":"<uuid>"}],
 "name":"...","description":"..."}
```

The ten `type` values Fabric emits are: `get data`, `store data`, `prepare data`, `analyze and train data`,
`develop`, `govern data`, `visualize`, `track data`, `distribute data`, `mirror data`.

**What import does and does not carry, established by doing it:**

| Carried | Not carried |
|---|---|
| Task names, types, positions | **Per-task descriptions** -- each box keeps its default type subtitle |
| The connectors between tasks | Item assignments (the format has no field for them) |
| The task flow's own name and description | |

The first file shipped with a `description` on each task. Fabric accepted the file and silently ignored that field,
so it has been removed rather than left in to imply something it cannot do. The six descriptions are in
`docs/fabric/task_descriptions.md` to paste by hand (select task -> **Edit** -> **Save**); this is optional.

Item assignments in 4.3 are still by hand, and always will be: the export format has nowhere to put them.

This whole section is cosmetic. Nothing in the pipeline, the tests or the evidence depends on it.

# Task descriptions to paste by hand

Fabric's task flow import **ignores** a `description` field on individual tasks (proven 2026-11-19: the file
carried them, the import accepted the file, and every box kept its default type subtitle). The task flow's own
name and description DO import. So these six have to be typed in: select the task -> **Edit** -> paste ->
**Save**. Optional; the flow reads fine without them.

## Ingest and build

One notebook, seven steps: bronze_land, silver_build, mdm_resolve, zatca_chain, ai_index, ndmo_catalog, restore_guard. PII is encrypted at the Bronze write.

## Store

Lakehouse LH_MIZAN (brz, ctl, slv, quarantine, security, audit, meta, ai) and Warehouse WH_MIZAN (gld). Money is DECIMAL(18,2); never float.

## Stream

Eventstream to Eventhouse. Velocity, mule-ring and reporting-SLA rules evaluated in KQL.

## Model

Direct Lake semantic model over WH_MIZAN. No import, no scheduled refresh.

## Report

Three pages: CFO Settlement, Tax ZATCA Health, CDO Data Trust.

## Command Center

Fabric App front end and the user data function behind it.


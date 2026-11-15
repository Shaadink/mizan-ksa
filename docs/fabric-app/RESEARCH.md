# Fabric App (preview) research for the MIZAN Command Center

Sources (read 2026-11-15): learn.microsoft.com/en-us/fabric/apps/overview, /apps/cli-reference, /apps/connectors,
/apps/create-app-with-cli, /admin/region-availability; plus the scaffolded template itself (`apps/command-center/`).

## What a Fabric App is

A managed app item in a Fabric workspace, built with the **Rayfin SDK** (TypeScript). `npx rayfin up` creates a
**Fabric app** item with child services from `rayfin/rayfin.yml`: Authentication (Fabric SSO / Entra ID only after
deploy), Static Content (our built frontend, served from `https://<app>-app.rayfin.windows.net/`), and, only if data
is enabled, a SQL database in Fabric. Our app does not enable data (no new database): it only reads the semantic model.

## Confirmed facts

| Question | Answer |
|---|---|
| Scaffold command | `npm create @microsoft/rayfin@latest`, or non-interactive `npx -y @microsoft/create-rayfin@latest --project-name command-center --template dataapp` (used; template list from `npx @microsoft/rayfin-cli init --list-templates`: `blankapp`, `dataapp` "Data App", `gettingstartedauth`, `todoapp`) |
| CLI version | `@microsoft/rayfin-cli` 1.36.2 (local to `apps/command-center/`, invoked as `npx rayfin`) |
| Node | Docs require "Node.js and npm installed"; no minimum stated. Local: Node 24.22.1, npm 11.19.1. Nothing installed globally. |
| Data App template | React 19 + Vite + Tailwind, Microsoft `fabric-visuals` / `fabric-datagrid`, connector client in `src/lib/rayfin-client.ts` + `src/lib/connectors.ts` (generated part below `@generated`). Hook: `useSemanticModelQuery({ connection, query })`, shaped with `toDataTable`. |
| How it queries the semantic model | Connector type **`fabric-semanticmodel`**, operation **`executeQuery`** (DAX). `client.connectors.<name>.executeQuery({ query: "EVALUATE ..." })` returns `{ status, table: { columns, rows } }`. Added with `npx rayfin connector add --type fabric-semanticmodel --name <name> --workspace-id <ws> --item-id <model>` (needs `npx rayfin login`). |
| Auth for the model | **Delegated only**: every viewer queries with their own identity and needs Read + **Build** on "MIZAN Control Tower Model". No service principal sign-in (`rayfin login --service-principal` is listed but not supported). |
| Region | UAE North (our capacity's region) supports Fabric App (not on the "not available" list). |
| Tenant setting | Fabric admin portal, Tenant settings, **"Fabric Apps (preview)"**: Enabled (whole org or a security group). |
| Local run | `npx rayfin dev` starts Vite locally **and deploys a backend item to Fabric** (first run, chosen workspace). So "run locally" already creates a Fabric app item in `mizan-ksa-dev`. |
| Deploy preview | `npx rayfin up --dry-run --verbose` validates and resolves the workspace without deploying. `npx rayfin up --workspace-id <id>` deploys. |
| Sharing | Users need **Run and interact** on the app item and Build on the semantic model. |

## Money and numbers

DAX results arrive as JSON numbers (double). To keep money exact, every DAX query returns **integer halalas**:
`CONVERT(ROUND([Measure] * 100, 0), INTEGER)`. Model money columns are DAX fixed decimal, so `* 100` is exact and
the integer is far below 2^53. The app formats halalas with the same integer routine as the standalone page.

## Data the app reads (plan for Stage 2)

- **Live DAX, one query per scene**: pulse, money flow, daily ledger (+ Hijri calendar), reconciliation heatmap, ZATCA
  outcomes/EGS/flows, NDMO scorecard and catalogue counts, store map (needs `merchant_store_reference` added to the
  semantic model; it is a table in WH_MIZAN `gld`, no Gold change).
- **Static proof-run JSON, labelled "proof run" with the source file named**: ZATCA chain tape and incident
  (engine re-run), PDPL erasure and Restore Guard, Arabic MDM board, stream replay and alerts, lineage, Spark skew
  benchmark, Fabric job timings, published/candidate run status, tax SAR card/cash split (needs a Silver join that the
  semantic model does not hold). Copied from `command_center/data.json` by `scripts/build_command_center.py`.
- **Offline fallback**: without a connector (unit tests, a local preview before sign-in) the app reads the same
  shapes from the export, so tests compare live-shaped results with the export.

## Risks and blockers

1. **Tenant setting**: if "Fabric Apps (preview)" is off in the college tenant, nothing can be created; only a tenant
   admin can turn it on.
2. **Trial capacity**: the docs require "Fabric capacity assigned" and do not say whether trial capacities (our
   FTL64) are supported. The Data Agent was refused on FTL64, so this is a real risk. We only find out at the first
   `rayfin dev` / `rayfin up`.
3. **Delegated access**: whoever opens the app needs Build on the semantic model; fine for the owner, must be granted
   for anyone else.
4. **Preview**: commands and flags can change between CLI versions; pin the versions in `package-lock.json`.

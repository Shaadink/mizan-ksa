# AF_MIZAN — running the daily pipeline from Fabric's own Airflow

## What this is, in plain words

**Apache Airflow** is a scheduler. You give it a Python file that says "run these jobs, in this order, every
night", and it runs them and shows you a picture of what passed and what failed. The picture is called a
**DAG** — a directed acyclic graph, which is a long way of saying "boxes with arrows, and no loops".

Until now, MIZAN's Airflow ran in **Docker on the owner's laptop**. That works, but the schedule only exists
while the laptop is on. Microsoft Fabric can host Airflow itself, as an item type the portal calls an
**Apache Airflow job** (it used to be called **Data workflows**, and some menus still say that). Moving the
schedule there means the pipeline runs whether or not anyone is at the machine.

This document is the setup. It takes about twenty minutes, and most of it is clicking.

## What it will and will not do

`dags/mizan_fabric_daily.py` runs the **six Fabric notebook jobs**, in order:

```
bronze_land ──▶ silver_build ──▶ mdm_resolve ──▶ zatca_chain ──┬──▶ ai_index
                                                               └──▶ ndmo_catalog
```

It does **not** run the freshness gate, the residency gate, the dbt build, or OpenLineage → Marquez. Those
stay in the Docker DAG (`airflow/dags/mizan_daily.py`), and the reason is a real limitation rather than a
preference: Microsoft states that "private networks and virtual networks aren't supported with Apache Airflow
jobs", so a Marquez server running on a laptop cannot be reached from inside Fabric. The repository's `mizan`
Python package is not installed there either.

So the honest description is: **Fabric's Airflow owns the nightly schedule for the lakehouse jobs; the Docker
Airflow remains the full pipeline including the gates and lineage.** Both are in the repository, and the
difference is written at the top of each file.

## What is already done

`AF_MIZAN` exists, and the DAG is in it. Both were done over the Fabric REST API by
`scripts/fabric_airflow.py`, so they can be rebuilt from one command on any tenant rather than clicked:

```powershell
.\.venv\Scripts\python.exe scripts\fabric_airflow.py status     # what exists right now
.\.venv\Scripts\python.exe scripts\fabric_airflow.py all        # create, push the DAG, settings, start
```

As of 2026-11-20 on the FTL64 capacity in UAE North:

| | |
|---|---|
| Item | `AF_MIZAN`, created through `POST /v1/workspaces/{ws}/apacheAirflowJobs` |
| DAG file | `dags/mizan_fabric_daily.py`, uploaded, 9,630 bytes |
| Environment | `Started` |
| Environment variables | **refused** — see below |

Git sync is deliberately not used. Microsoft documents no REST surface for configuring it, and uploading
the file from the repository keeps the whole deployment in one command without handing Fabric a GitHub
credential. The file management API this relies on is still in beta, so every such call carries
`?beta=true` and the shape may change.

## The one thing the API would not do

Fabric documents an environment-settings API for setting variables. On this capacity it does not work: the
same service principal that had just created the item and uploaded a DAG through the sibling beta API gets

```
401 Unauthorized -- "User is not authorized to perform this operation because user does not have
Write permissions for the workspace"
```

and the matching `GET` answers `500 InternalServerError`. Both are reproducible, and `isRetriable` is
false. It is documented as supported for service principals, so this is a gap between the documentation and
the capacity rather than a missing permission on our side.

That is not a loss. The DAG asks Airflow for a **Variable** first and only falls back to an environment
variable, and Variables are the better home anyway: Airflow masks any variable whose name contains
`secret`, while the settings API stores values in plain text and hands them back in full on a `GET`. The
client secret was never going to be sent through that API for exactly that reason.

## Step 1 — add seven Airflow Variables

1. Open `AF_MIZAN` in the workspace, then the **Airflow UI** button at the top.
2. Go to **Admin → Variables**.
3. Add these six, names exactly as written:

| Variable | Value |
|---|---|
| `mizan_tenant_id` | `FABRIC_TENANT_ID` from `.env` |
| `mizan_client_id` | `FABRIC_CLIENT_ID` from `.env` |
| `mizan_client_secret` | `FABRIC_CLIENT_SECRET` from `.env` |
| `mizan_workspace_id` | `FABRIC_WORKSPACE_ID` from `.env` |
| `mizan_lakehouse_id` | `LH_MIZAN_ID` from `.env` |
| `mizan_notebook_id` | the `nb_mizan_step` item id — `fabric_airflow.py status` prints it |
| `mizan_sql_endpoint` | `FABRIC_SQL_ENDPOINT` from `.env` — only the dbt task needs this one |

Open `.env` in the editor to copy from. **Do not paste it into a chat, a commit, or a screenshot.**

## Step 1b — add dbt to the worker (only for the `dbt_build_gold` task)

The six notebook tasks need nothing installed. The seventh, `dbt_build_gold`, builds Gold on WH_MIZAN and
needs dbt in the worker. The REST route for requirements is refused for our service principal (HONESTY row
31), so this one is a portal click:

1. In `AF_MIZAN`, press **Apache Airflow requirements** in the top toolbar.
2. Add `dbt-fabric==1.9.10`.
3. Save, and **restart the job** so the install takes effect.

`scripts/fabric_airflow.py push-dbt` has already uploaded the dbt project itself to `dags/dbt/`, so the task
has something to build.

**This may not work, and the DAG is built to survive that.** dbt-fabric needs `ODBC Driver 18 for SQL Server`
in the worker image, which Microsoft does not promise for Apache Airflow jobs. The task shells out to `dbt`
rather than importing it, so a missing driver or a failed install turns one task red with a readable reason
instead of making the whole DAG vanish from the list — and the six Fabric steps before it keep their result.
If it cannot be made to work, dbt keeps running from the developer machine against the same warehouse, as it
did before, and this stays an honest open item rather than a claim.

## Step 2 — run it once by hand

1. In the Airflow UI, find `mizan_fabric_daily` and switch it from paused to active.
2. Press **Trigger DAG**.
3. Open the **Graph** view: six boxes, turning green in order.

`bronze_land` takes around twelve minutes on its own; the whole run took **19 minutes 23 seconds** on
2026-11-19. If a box turns red, click it → **Logs**: the DAG raises with the step name, the Fabric run id
and the failure message Fabric reported, so the log says what broke rather than that something did.

After that the schedule takes over: **03:00 Asia/Riyadh, every day**, with no back-filling of missed nights.

## The starter pool pauses, so the nightly schedule is not yet real

Fabric puts a banner above the editor: *"You're using a starter pool, which pauses when idle. For
uninterrupted DAG runs on schedule, switch to an always-on custom pool."* That is the default, and it means
**Run DAG by hand works, but a 03:00 run may not fire** -- the pool has to be awake for the scheduler to act.

An always-on custom pool fixes it and bills capacity units continuously, which on this capacity is not
something to switch on and forget. So the honest statement today is: the schedule is written into the DAG and
the DAG is deployed, and until the pool is always-on, the nightly trigger is not something to rely on. Run it
by hand, or switch the pool when the pipeline is worth keeping warm.

## Common failures, and what they actually mean

| What you see | What it means |
|---|---|
| `missing Airflow Variable 'mizan_workspace_id'` | Step 3 was skipped or the name is misspelled. The DAG names the one it wanted. |
| `Entra token request failed (401): AADSTS7000215` | The client secret is wrong or has expired. App registrations expire — regenerate it in Entra and update the variable. |
| `Fabric refused the job submission (403)` | The service principal is not a member of the workspace, or lost its role. Add it back as a Contributor. |
| `bronze_land: Fabric reported Failed` | The notebook itself failed. The message is Fabric's own; the notebook log in `LH_MIZAN/Files/_logs/` has the detail. |
| DAG does not appear at all | Git sync has not completed, or the file is not under a top-level `dags/` folder. |

## How this is tested

The DAG cannot be run from this machine — it needs Fabric's scheduler, Fabric's workers and a live capacity.
`tests/test_fabric_airflow_dag.py` therefore tests everything that does not need those: that the module
imports with nothing but the standard library, that the job order is the one the lakehouse requires, that the
REST contract matches what Fabric answers (202 plus a `Location` header, then polling), that a failed step
raises instead of letting the next one read half-written tables, that a bad token never echoes the secret
into a log, and that no credential is written into a file Fabric syncs.

What is **not** tested here is whether Fabric's Airflow accepts the file at all. That is only knowable by
running Step 4, and until that has been done once, this document describes an intention rather than a result.

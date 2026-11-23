# MIZAN-KSA launch video - the plan

**2:30, engineering-first, shot inside Microsoft Fabric.** Supersedes `VIDEO_SHOT_LIST.md`.

The audience is people hiring for Fabric work. So the rule for every shot is: *if it can be shown in the
tenant, it is shown in the tenant.* A screen recording of a local repository proves the engineering but
puts it in the wrong building.

---

## Part 0. The four decisions, argued

### 1. Everything that can be in Fabric, is in Fabric.

Six architecture diagrams and eight sections of narrative now live in **`nb_mizan_walkthrough`**, a
notebook in workspace `mizan-ksa-dev`. Each section shows its diagram from OneLake and then queries
`LH_MIZAN` and `WH_MIZAN` live underneath it. That notebook is the spine of the video.

Here is the honest split, because a viewer who knows Fabric will work it out anyway:

| Shown in Fabric | Cannot be in Fabric |
|---|---|
| Workspace items: `LH_MIZAN`, `WH_MIZAN`, `EH_MIZAN`, `ES_MIZAN`, semantic model, report, app | **Docker** - `docker-compose.airflow.yml`, `.skew.yml` |
| **`AF_MIZAN`** - Apache Airflow, running *as a Fabric item* | **Marquez** - the OpenLineage viewer, a container |
| Monitoring hub: six PySpark notebook runs | **GitHub Actions** - CI runs on GitHub's runners |
| **`nb_mizan_walkthrough`** - diagrams + live queries | |
| Lakehouse explorer: the eight schemas, browsable | |
| **`WH_MIZAN` SQL query editor** - Gold, in T-SQL | |
| **Spark UI**, opened from a notebook run | |
| Direct Lake semantic model and the Power BI report | |
| **Command Center** - a Fabric App, live DAX | |

The three on the right get **eight seconds total**, in one honest beat near the end. They are real, they
matter, and pretending they run in Fabric would be the one lie in the video.

### 1b. The diagrams in the video are Fabric's own, not pictures of Fabric.

`docs/diagrams/` holds six SVGs this project draws. They are good for the README and for a thumbnail, and
they are **not** what the video should lead with, because a picture of an architecture proves nothing
about whether that architecture exists.

Fabric draws five diagrams itself, from the real items. Those are the ones to film. Each is a live view
of the tenant: if an item were missing or disconnected, the diagram would show it.

| Fabric's own diagram | Where | What it proves that a drawing cannot |
|---|---|---|
| **Task flow** | across the top of the workspace | the whole platform as seven labelled tasks with real items clipped to each. Seven tasks, five connectors, named *MIZAN platform*. Imported from `docs/fabric/mizan_task_flow.json` |
| **Lineage view** | workspace -> **Lineage** (top right) | Fabric traced it, not me: lakehouse -> SQL endpoint -> warehouse -> semantic model -> report -> app. Impact analysis from any node |
| **Model view** | `MIZAN Control Tower Model` -> **Model** | the star schema, drawn from the real relationships: two dimensions, four facts, six relationships |
| **Eventstream canvas** | `ES_MIZAN` | source -> transform -> destination, as a live flow with throughput on it |
| **Airflow DAG graph** | `AF_MIZAN` -> Monitor DAG -> Graph | six tasks with real durations and a real fan-out |

A sixth, if you want it: the **Spark UI DAG** for a notebook run, which draws the actual query plan - the
salted skew join is visible in it as the stage that fans out to 16.

**The honest note about the task flow.** It is a label layer: it creates nothing, moves nothing and runs
nothing. There is also no REST API for it - probed on 2026-11-19, `GET /v1/workspaces/{ws}/taskFlow` and
its variants all return 404 while `/items` returns 200 - so it is the one part of MIZAN that was
assembled by hand in the portal. Worth saying in an interview rather than implying it was scripted.

**Where my six SVGs still belong.** In the README, where there is no tenant to open; as the thumbnail;
and inside `nb_mizan_walkthrough`, where each one sits above the query that proves it. In the video they
are a cutaway, not the main evidence.

### 2. Open on the failure, not on the platform.

Seconds 0-3 are the only ones you are guaranteed. An item list is a screenshot of a filing cabinet.

Open on the planted **0.01 SAR** error and the build refusing to publish. It states the problem, shows the
stakes, proves the system is adversarial rather than decorative, and sets up a callback. And it happens
inside the Command Center, which is a Fabric App - so even the hook is a Fabric shot.

The Airflow DAG is the strongest argument you have and the second-weakest hook you have. It is beat two.

### 3. Captions, no voice-over.

Sound-off is the majority case, so the captions carry it regardless. A voice-over then adds retakes and
pacing risk and reaches nobody the captions do not. Quiet music bed, nothing with a drop.

### 4. One extra export, free.

Record once in 16:9. Export the **2:30 master** for the README and the portfolio, and a **1:10 square**
cut for the feed itself - the first six seconds, Airflow, the warehouse query, the Arabic flip and the end
card. The short earns the click; the long survives the interview panel.

---

## Part 1. The 2:30, shot by shot

Eight acts. Each has one job. If a shot does not serve its act's job, cut it - that rule is what keeps a
2:30 from becoming a 5:00.

### Act 0 - The hook (0:00 - 0:08) - Fabric App

| Time | On screen | Caption |
|---|---|---|
| 0:00 - 0:03 | Command Center (Fabric App), hero, gold scale **level**, then press `B`: it tilts, the stamp reddens | I hid a 0.01 SAR error in 22 million rows. |
| 0:03 - 0:08 | The breaker line filling frame: `dbt circuit breaker - FAIL - 2 unexplained MID-days - build halted` and `Candidate run x FAIL - not published` | It found it, and refused to publish the day. |

### Act 1 - It orchestrates itself, in Fabric (0:08 - 0:40) - Airflow + monitoring hub

The act a data engineer is actually judging. Four shots, eight seconds each, mouse still.

| Time | On screen | Caption |
|---|---|---|
| 0:08 - 0:16 | **`AF_MIZAN` -> Monitor DAG -> Graph**: `mizan_fabric_daily`, six green tasks, the fan-out from `zatca_chain`. Hover `bronze_land` for the duration | Apache Airflow, running as a Fabric item. |
| 0:16 - 0:24 | Fabric **Monitoring hub** filtered to today: the same six notebook runs, all **Succeeded**, timestamps seconds after the DAG tasks | It starts six PySpark notebooks over the REST API. |
| 0:24 - 0:32 | Click into `silver_build` -> **Spark UI** -> Stages. Show the skew: 20M rows, 62:1, the salted join | 20M rows at 62:1 skew, salted to 16. Same checksum three ways. |
| 0:32 - 0:40 | Back to the workspace item list, slow scroll: lakehouse, warehouse, eventhouse, eventstream, semantic model, report, app, notebooks | One workspace. Nothing runs on my laptop. |

### Act 2 - The architecture, drawn by Fabric (0:40 - 1:00) - task flow, lineage, model view

Three of Fabric's own diagrams, back to back. None of them is a picture I drew; each is rendered from the
items that exist, which is why they are worth more than the SVGs.

| Time | On screen | Caption |
|---|---|---|
| 0:40 - 0:47 | The workspace **task flow** across the top: seven tasks, five connectors, items clipped to each. Click **Store** so the pane shows its items | Seven tasks. Every item in the workspace belongs to exactly one. |
| 0:47 - 0:54 | Workspace -> **Lineage**. Let the graph draw: lakehouse -> SQL endpoint -> warehouse -> semantic model -> report -> app. Hover one node for impact analysis | Fabric traced this, not me. |
| 0:54 - 1:00 | `MIZAN Control Tower Model` -> **Model** view: the star schema, six relationships | Two dimensions, four facts, six relationships. |

If you want the SVG architecture diagram in the video at all, it belongs here as a two-second cutaway
between the task flow and the lineage view - as a legend for what Fabric is about to show, not as the
evidence itself.

### Act 3 - One sale, five systems (1:00 - 1:20) - notebook + lakehouse explorer

| Time | On screen | Caption |
|---|---|---|
| 1:00 - 1:04 | `nb_mizan_walkthrough`, section 2, **run the cell**: 28 tables, 439,192 rows printed live | Eight schemas, read live through the same code the jobs run. |
| 1:04 - 1:08 | Section 3: the dataflow diagram | Five systems record the same sale. None of them agree. |
| 1:08 - 1:20 | Run the trace cell: one `payment_event_id` printed from `slv.payment_lifecycle` and `slv.settlement_lines` side by side | The MDR fee is read from the bank file. Never recomputed. |

### Act 4 - Reconciliation (1:20 - 1:45) - notebook + `WH_MIZAN` query editor

| Time | On screen | Caption |
|---|---|---|
| 1:20 - 1:28 | Section 4: the key-spine diagram | A LEFT JOIN answers what matched. Finance needs what is missing. |
| 1:28 - 1:37 | Run the Gold cell: both variances `0.00`, and the assessed / in-transit split | SAR 22.39M reconciled to exactly 0.00. |
| 1:37 - 1:45 | **`WH_MIZAN` -> New SQL query**, type and run: `SELECT SUM(unexplained_bank_variance_sar), SUM(unexplained_gl_variance_sar) FROM gld.fact_merchant_settlement_recon;` | And again in T-SQL, straight against the warehouse. |

Typing that query live is the most convincing eight seconds available. It cannot be faked, it is the
claim the whole project rests on, and it is a Fabric surface.

### Act 5 - The ZATCA chain (1:45 - 2:03) - notebook

| Time | On screen | Caption |
|---|---|---|
| 1:45 - 1:53 | Section 5: the state machine diagram. Rest on `SUBMITTING -> UNKNOWN_OUTCOME` | SUBMITTING is persisted before the HTTP call. |
| 1:53 - 2:03 | Run the chain cell: 25,001 documents, **0 ICV gaps, 0 PIH breaks** | A timeout and a worker crash. Retried with the identical signed bytes. |

### Act 6 - dbt, lineage, and the honest gap (2:03 - 2:18)

| Time | On screen | Caption |
|---|---|---|
| 2:03 - 2:10 | Section 6: the dbt lineage diagram, generated from the manifest | dbt build: 99 nodes. 7 models, 89 tests, 3 seeds. |
| 2:10 - 2:18 | Fast cut, three shots, ~2.5s each: **Marquez** column lineage 94/94, `docker compose up` in a terminal, **GitHub Actions** green | OpenLineage, Marquez and CI. The half that does not run in Fabric. |

Naming that gap out loud costs eight seconds and buys more credibility than any feature in the video.

### Act 7 - What it is not, and the end card (2:18 - 2:30)

| Time | On screen | Caption |
|---|---|---|
| 2:18 - 2:25 | Section 8 of the notebook, and `HONESTY.md` on GitHub scrolling | Synthetic data. Not ZATCA-certified. One engineer, no second reviewer. |
| 2:25 - 2:30 | Static card: **MIZAN-KSA**, your name, `github.com/Shaadink/mizan-ksa` | Built by Shadin K. Repo in the comments. |

One call to action. Not "follow, like, connect, DM and star".

---

## Part 2. Before you record

### Get the tenant into the right state

```
.\.venv\Scripts\python.exe scripts\build_diagrams.py          # SVG + PNG
.\.venv\Scripts\python.exe scripts\fabric_walkthrough.py      # upload + publish + RUN it
```

The second one publishes `nb_mizan_walkthrough`, uploads the six diagrams to
`LH_MIZAN/Files/diagrams/`, and executes the notebook end to end. It writes
`Files/_logs/walkthrough_receipt.json`, so you can confirm it really ran before you point a camera at it.
If a cell fails, the traceback is in `Files/_logs/walkthrough.txt` and nothing else is affected - cells
are wrapped so one failure cannot cancel the Spark session.

Then, in order:

1. **Warm the Spark pool.** Run any notebook once. A cold starter pool sits on "Queued" for minutes and
   there is no way to edit that out that does not look like an edit.
2. **Run `AF_MIZAN`** so the DAG graph is already six green boxes when you film it.
3. **Check the Command Center says `Live` in green**, not amber `Snapshot`. Amber means your Fabric
   session expired; sign in again.
4. **Give the SQL endpoint a few minutes** after any write. It lags the lakehouse, and a freshly written
   table can read empty.

### Settings

- **Capture:** OBS Studio (free), display capture, 1920x1080, 30 fps, CQP 18.
- **Browser:** zoom 100%, dark mode, full screen (`F11`), bookmarks bar hidden, one window.
- **Notifications off.** Focus Assist on, Teams and Outlook closed. One toast ruins a take.
- **Enlarge the mouse cursor** in Windows settings. At 1080p scaled into a phone feed the default pointer
  disappears, and half these shots are "watch where I click".
- **Edit:** DaVinci Resolve or CapCut. Both crop square and burn in captions.
- **Export:** MP4 / H.264. 1080p for the master, 1080x1080 for the cut. **Burn the captions in** - do not
  trust LinkedIn's auto-captions with "halala", "ZATCA" or "mada".

### Caption rules

Seven words a line, two lines maximum, on screen at least 1.2 seconds. Bottom third, white, 55-65% black
scrim so it survives a bright heatmap. One idea per caption; if it needs an "and", it is two captions.

**Never caption a replay as live.** The stream, PDPL, MDM and Spark scenes are proof runs and their
provenance line says so on screen. Do not contradict your own page.

### Recording order

Four sittings, three takes each, keep the best. Retaking an hour later means re-signing in and
re-matching the window size.

| Block | What | Watch for |
|---|---|---|
| A. Fabric orchestration | workspace, `AF_MIZAN`, monitoring hub, Spark UI | run the DAG first |
| B. The notebook | all six sections, cells run live | clear old output first, so the run is visible |
| C. Warehouse + app | `WH_MIZAN` query editor, Command Center, Arabic | check the green `Live` label |
| D. Outside Fabric | Marquez, `docker compose up`, GitHub Actions | pick one theme and keep it |

### If a live capture fails

`docs/artifacts/demo/` holds eight screenshots at 2400x1500 and `docs/diagrams/png/` holds the six
diagrams. Both are legitimate fallbacks, and the screenshots double as a stills carousel. The demo shots
come from the **standalone** page, which labels itself *exported Gold snapshot* rather than *Live* - so if
you use one, do not caption it "live DAX".

---

## Part 3. The numbers you are allowed to say

Re-check these against `docs/PROOF_MANIFEST.md` on the day. This project's whole argument is that its
figures are derived rather than typed, so a stale caption costs more than it saves.

| | |
|---|---|
| Reconciled | SAR 22,391,236.23 across 2,233 merchant-days |
| Variance | 0.00, on the 2,121 merchant-days whose bank file has arrived |
| Held back | 112 merchant-days, in transit, never counted as balanced |
| ZATCA | 25,001 documents, 0 ICV gaps, 0 PIH breaks |
| Lineage | 94 of 94 Gold columns |
| Scale | 20M rows at 62:1 skew, same checksum three ways |
| dbt | a 99-node build, green on WH_MIZAN and on the local target. 99 = 7 models + 89 tests + 3 seeds |
| Tests | 444 Python, 184 Fabric App (183 pass, 1 skipped) |
| Lakehouse | 28 tables, 439,192 rows (from the walkthrough receipt) |

Say **"99-node dbt build"**, not "99 dbt tests". There are 89 tests. The front pages said otherwise until
2026-11-22 and it was wrong.

And the four that must not be left out: **synthetic data**, **not certified by ZATCA or any regulator**,
**one engineer with no second reviewer**, **a reference architecture, not a product**.

# MIZAN-KSA demo video: shot list (2:30)

Record at 1920x1080, 30 fps, browser zoom 100%, dark mode. Close other tabs and notifications. Sign in to Fabric and
to the app before recording so no login screen appears. Captions go on screen (bottom third, short, white on dark);
no voice-over is needed. Every number on screen comes from the real (synthetic-data) run.

**Before you start:** open these tabs in order
1. Fabric workspace `mizan-ksa-dev` (item list)
2. **AF_MIZAN -> Monitor DAG -> Graph**, showing `mizan_fabric_daily` with all six tasks green
3. Monitoring hub (Fabric) filtered to today's notebook runs
4. GitHub Actions page of the repo (latest green run)
5. The Fabric App: `mizan-ksa-dev` -> command-center -> Open (check the bottom-left label is green "Live")

## Part 1. The platform is real (0:00 - 0:30)

Open on the orchestrator, not the data. "It runs itself in the cloud" is the claim most portfolio projects cannot make, so make it in the first fifteen seconds.

| Time | Show / click | Caption |
|---|---|---|
| 0:00 - 0:06 | Fabric workspace `mizan-ksa-dev`, slow scroll over LH_MIZAN, WH_MIZAN, EH_MIZAN, ES_MIZAN, the semantic model, the report and the **command-center** app | One Saudi commerce transaction, followed end to end on Microsoft Fabric. |
| 0:06 - 0:15 | **AF_MIZAN -> Monitor DAG -> Graph**: `mizan_fabric_daily`, six green boxes, the arrows fanning from `zatca_chain` to `ai_index` and `ndmo_catalog`. Hover `bronze_land` so the duration shows | Apache Airflow, running inside Fabric, starts six PySpark jobs over the REST API. Nothing runs on my laptop. |
| 0:15 - 0:21 | Monitoring hub: the same six notebook runs, all **Succeeded**, started seconds after the DAG tasks | Each box is a real Fabric notebook run: land, encrypt, resolve, sign, index, catalogue. |
| 0:21 - 0:26 | Terminal: `dbt build` ending **PASS=99 ERROR=0** | dbt builds and tests the Gold layer: 99 models and tests green. | 
| | **Either build is now true.** Fabric was re-run on 2026-11-21 and also reads 99/99, so `--target fabric` is the stronger shot: it says the warehouse in the cloud, not the laptop. |  |
| 0:26 - 0:30 | GitHub Actions: the latest run with three green jobs (lint + unit, full PySpark suite, Fabric App) | Every push runs the full test suite. |

## Part 2. The app tour (0:30 - 1:50)

| Time | Show / click | Caption |
|---|---|---|
| 0:30 - 0:38 | Open the app from the workspace. Hold on the hero: the gold scale settles level | The scales only settle when bank and ledger agree to the last halala. |
| 0:38 - 0:46 | Point the mouse at the green **Live** label (bottom-left), then the chip "112 MID-days not assessed" | Live DAX on the semantic model. Days without a bank file are never shown as balanced. |
| 0:46 - 0:58 | Filter bar: choose **City = Jeddah**. Scroll to Reconciliation, the heatmap redraws | Every filter re-queries the model; the page recomputes. |
| 0:58 - 1:08 | Click one bright heatmap cell. The drill panel opens with every leg | One merchant-day: captures, fees, bank paid, GL and both variances. |
| 1:08 - 1:14 | Click **Clear**. Press **B** (break a halala) | One planted halala break... |
| 1:14 - 1:20 | Scroll up: the 3D scale tilts, the stamp turns red, the candidate run is flagged | ...and the circuit breaker stops it from being published. |
| 1:20 - 1:23 | Press **B** again to restore | |
| 1:23 - 1:35 | Menu: **ZATCA**. Hover the EGS cards, then the outcome bar and the 24 h ring | ZATCA Phase-2: 25,001 documents, zero chain breaks, a rejection kept in the chain. |
| 1:35 - 1:42 | Type `102` in the search box, press Enter: the chain jumps to ICV 102 | A timeout and a worker crash, retried with the identical signed bytes. |
| 1:42 - 1:50 | Menu: **Map**, click **Riyadh**; then press **L** for Arabic, hold 2 s, press **L** again | Stores by city, money routed to the bank. English and Arabic, right to left. |

## Part 3. Story mode (1:50 - 2:25)

| Time | Show / click | Caption |
|---|---|---|
| 1:50 - 1:52 | Click **Clear**, press **P** (presenter mode hides the chrome) | |
| 1:52 - 2:25 | Click **Play the story** (or press P, then the top button before hiding). Let it run through Pulse, Money flow, Ledger, PDPL erasure, MDM and the risk stream; press **T** once on Money flow to trace one riyal | Story mode: one riyal, one invoice, one customer's erasure, one fraud burst. |

## End card (2:25 - 2:30)

| Time | Show | Caption |
|---|---|---|
| 2:25 - 2:30 | Hero (press **P** to bring the header back) with your name and LinkedIn button visible | MIZAN-KSA - built by Shadin K. Synthetic data; engineering reference, not a certified product. |

## Tips

- Keep the mouse still while a caption is on screen; move it only to the next click.
- If the app shows the amber "Snapshot" label, sign in again before recording (live DAX uses your Fabric identity).
- The stream, PDPL, MDM and Spark scenes are proof runs or replays; their provenance line says so. Do not caption them as live.
- Export as MP4 (H.264). LinkedIn accepts up to 10 minutes; 2:30 keeps people watching.

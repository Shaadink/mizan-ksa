# MIZAN-KSA launch video - the recording plan

**2:30. Problem -> how I solve it -> proof -> impact. Recorded clip by clip, then joined.**

1920x1080, 60 fps. Browser at 110%, taskbar and bookmarks hidden, one window, notifications off.
Record each clip on its own, 3 takes, keep the best. Hold still 2 s at the start and end of every clip.
**Pause 1 s before every click** so the auto-zoom has something to lock onto.

No voice-over. Captions are burned in during the edit.

Read Part 1, do Part 2, then record Part 3 clip by clip. Everything after that can wait until you have
the footage. Supersedes `VIDEO_SHOT_LIST.md`.

---

## Part 1. The ten things you must show

Nothing else earns a place. If a shot does not make one of these points, cut it.

| # | The point | What proves it |
|---|---|---|
| 1 | **The problem is real** | A raw bank CSV and a raw ZATCA XML that do not line up |
| 2 | **It is a real Fabric platform, not scripts** | The workspace, the lakehouse, the lineage view |
| 3 | **It orchestrates itself in the cloud** | Airflow DAG, six green tasks |
| 4 | **It is real code over real data** | `nb_mizan_walkthrough` cells run live on camera |
| 5 | **dbt builds and tests the Gold layer** | `PASS=99 ERROR=0`, then the dbt docs lineage graph |
| 6 | **ZATCA agrees with my hash** | ZATCA's own SDK vs MIZAN, 44/44 characters identical |
| 7 | **The tax chain survives a crash** | 25,001 invoices, 0 ICV gaps, 0 PIH breaks |
| 8 | **It catches mistakes and refuses to ship them** | Press `B`; the scale tilts, the build halts |
| 9 | **Lineage is tracked to the column** | Marquez: a Gold column traced back to Bronze |
| 10 | **It works in Arabic** | Press `L`; the page mirrors, numerals stay left to right |

Then one closing beat: **what it is not**, and your name.

**The single most important rule: click things.** A video of a static screen is a screenshot with a
runtime. The value here is that the system *responds*.

---

## Part 2. Before you record

### Done already - nothing to do

| | |
|---|---|
| Semantic model deployed | 6/6 relationships verified live in the tenant |
| `nb_mizan_walkthrough` | Ran 31/31 cells, 0 errors, 6 diagrams uploaded |
| Marquez | 94/94 Gold columns, 9 datasets, serving on `localhost:3000` |
| dbt docs | Serving on `localhost:8081` with the lineage graph |
| ZATCA hash showdown | Serving on `127.0.0.1:8765`, verified returning MATCH |
| `nb_probe_tmp` | Deleted. Workspace is 15 clean items |

### Still yours

| | Do | Why |
|---|---|---|
| 1 | **Fabric portal -> MIZAN -> `AF_MIZAN` -> Start** | Clip `03b` is impossible until it runs. ~10 min. The REST API refuses service principals on the whole `/environment/` surface, so this one is a portal click |
| 2 | Run `AF_MIZAN` once | So the DAG graph already shows six green boxes when you film it |
| 3 | **Clear all outputs** in `nb_mizan_walkthrough` | So Clip `03c` shows them appearing, not results from my run |
| 4 | Open the workspace, check the **task flow** band is across the top | No API can verify it. If missing, import `docs/fabric/mizan_task_flow.json` (`docs/PORTAL_STEPS.md` 4.4) |
| 5 | Open any notebook, run one cell | Warms the Spark pool. A cold pool sits on "Queued" for minutes and you cannot edit that out invisibly |
| 6 | Set the mouse pointer to **size 3** | Settings -> Accessibility -> Mouse pointer. Half this video is "watch where I click" and the default pointer vanishes at phone size |
| 7 | **Re-run the test suite and read the number off the screen** | It has moved three times this week. Caption what it prints, not what this file says |

If a server is not answering, restart it:

```
docker compose -f docker/docker-compose.airflow.yml up -d
cd dbt; ..\.venv\Scripts\dbt.exe docs serve --profiles-dir . --target duckdb --port 8081 --no-browser
.\.venv\Scripts\python.exe D:\zatca-demo\showdown_server.py
```

---

## Part 3. The clips

Lengths are the *edited* length. Record a few still seconds either side so you have room to cut.

### Act 1 - Hook (0:00 - 0:08)

| Clip | Record | Len | Added in the edit |
|---|---|---|---|
| - | Nothing | 5 s | Animated title: *"Saudi finance teams lose days matching payments to ZATCA invoices."* |
| `01-facecam` (optional) | One line to camera: *"I built a platform that reconciles every halala."* | 3 s | Rounded frame, name lower-third |

### Act 2 - The problem (0:08 - 0:18)

Cut from 16 s to 10 s. This is the most compressible part of the video: a viewer grasps "these two files
disagree" in about three seconds, and nothing is gained by holding it longer.

| Clip | Record | Len | Added |
|---|---|---|---|
| `02a-raw-bank-csv` | Open a raw settlement CSV from `data/generated/`, scroll slowly | 5 s | Red mismatch highlights |
| `02b-raw-invoice-xml` | Open a raw ZATCA invoice XML beside it | 5 s | Split screen, "doesn't match" tags |

**No real VAT numbers or customer names.** The generated data is safe; nothing else is.

### Act 3 - How I solve it (0:18 - 0:50)

| Clip | Record | Len | Added |
|---|---|---|---|
| `03a-lakehouse` | In the Fabric workspace open LH_MIZAN, click into `brz`, then `slv`, then WH_MIZAN `gld` | 6 s | Animated Bronze -> Silver -> Gold flow |
| `03b-fabric-airflow` | Open `AF_MIZAN` -> Monitor in Apache Airflow -> `mizan_fabric_daily` -> Graph. Six green boxes. Hover `bronze_land` for the duration tooltip | 8 s | Speed-up, zoom travelling along the chain |
| `03c-walkthrough` | Open `nb_mizan_walkthrough`. Scroll to a diagram, then **run the cell beneath it** and let the real numbers print | 10 s | Caption: *"The diagram, and the query that proves it, in the same notebook."* |
| `03d-marquez` | `localhost:3000`. Start on a Gold table, click a node to expand its columns, pan slowly back to Bronze | 8 s | Glowing path along the lineage edges |

**`03c` is the clip that answers "does he actually work in Fabric".** Everything else in this act could
be a screenshot. A cell that prints a number which was not there a second ago cannot be.

### Act 4 - Engine and proof (0:50 - 1:32)

| Clip | Record | Len | Added |
|---|---|---|---|
| `04a-dbt` | `cd dbt; ..\.venv\Scripts\dbt.exe build --profiles-dir . --target fabric` landing on `PASS=99 ERROR=0` | 5 s | Speed 8x. A time-lapse of a real build is honest; a cut to the finished screen is not |
| `04b-dbt-docs` | `localhost:8081`. Click the lineage icon, bottom right. Then click `fact_merchant_settlement_recon` to show its tests | 4 s | Caption: *"7 models, 89 tests, 3 seeds."* |
| `04c-spark-skew` | The AQE-off stage page, hover the Max row. Then the salted stage | 8 s | Side-by-side. Caption: *"One merchant is 65% of the data. Worst task: 15.3 s -> 3.2 s."* |
| `04d-tests` | The suite running, ending on whatever it prints | 5 s | Counter animation on the real number |
| `04e-zatca-hash` | `127.0.0.1:8765`, F11. Click **Run live**, wait for MATCH 44/44. Then **Change one digit & run again** | 12 s | Glow on the matching hashes. Caption: *"ZATCA's official SDK vs my pipeline. Same invoice, same hash."* |
| `04f-zatca-chain` | Command Center: `P` then `5`. Let the chain animate through the amber RETRIED pulse, then drag the crash slider 0 -> 2 until "byte-identical proven" | 8 s | Caption: *"25,001 invoices, 0 chain breaks."* |

**`04e` is the strongest single clip in the video.** Every other shot asks the viewer to trust your
system. That one shows an external authority's own tool agreeing with yours, computed on screen - and the
tamper button proves it was not pre-rendered.

### Act 5 - The Command Center (1:32 - 2:08)

Open the **Fabric App** (workspace -> `command-center` -> Open), not the local HTML file. The Fabric App
says **Live**; the local copy labels itself *exported Gold snapshot*. Check the label is green before you
start - amber means your session expired.

| Clip | Record | Len | Added |
|---|---|---|---|
| `05a-home` | Let the page load so the scales and KPIs animate in. Hands off the mouse | 7 s | Slow push-in |
| `05b-break-it` | Press `B`. The scale tilts, the stamp turns red. Scroll slowly to the red breaker line | 8 s | Auto-zoom on the alert |
| `05c-drilldown` | Click a heatmap cell, then open the MID-day drill panel showing all four legs | 5 s | Cursor highlight, click ripples |
| `05d-arabic` | Press `L`. The layout mirrors, numerals stay left to right | 5 s | Caption: *"Full RTL. The numbers do not flip."* |
| `05e-ask-mizan` | Ask MIZAN: type *"Which merchants have unsettled payments?"*, show the evidence panel | 7 s | Typing emphasis |
| `05f-governance` | A glimpse of PDPL erasure, then the NDMO scorecard | 4 s | Tag: "Compliance built in" |

### Act 6 - Impact and close (2:08 - 2:24)

| Clip | Record | Len | Added |
|---|---|---|---|
| `06-wide` | One final wide, still shot of the dashboard | 11 s | Animated stats, then what it is not, then your name and LinkedIn |
| `01-facecam` outro (optional) | Reuse, or record one closing line | 5 s | |

### The budget, so it can be checked

| Act | Clips | Length |
|---|---|---|
| 1 Hook | title + facecam | 8 s |
| 2 Problem | `02a` `02b` | 10 s |
| 3 How I solve it | `03a` `03b` `03c` `03d` | 32 s |
| 4 Engine and proof | `04a` - `04f` | 42 s |
| 5 Command Center | `05a` - `05f` | 36 s |
| 6 Impact and close | `06` + outro | 16 s |
| | **Total** | **2:24** |

Six seconds under 2:30 on purpose. Every edit overruns, and the headroom is cheaper than deciding at
midnight which proof to delete.

---

## Part 4. Three things this plan deliberately does NOT claim

Checked against `HONESTY.md` on 2026-11-24. Each of these was in an earlier draft and each is wrong.

**1. No data-residency claim, in any form.** HONESTY row 23 is open: `config/residency_policy.yml` declares
`region: KSA` for every zone, the capacity is in **UAE North**, and the residency gate cannot see the
mismatch. Not showing the region in a 2:30 video is fine. Telling a KSA-residency story is not - and in a
project whose entire differentiator is HONESTY.md, a reviewer who finds the contradiction costs more than
the clip was worth. Film the gate running; claim nothing about where the data physically sits.

**2. Not "5x faster" on the skew clip.** The measured run:

| Mode | Total job | Worst task |
|---|---|---|
| AQE off | 23.12 s | 15.3 s |
| AQE skew-join | **15.52 s** | 10.1 s |
| Salted x16 | 17.62 s | **3.2 s** |

The 5x is the *worst task*, not the job - and on total time Spark's built-in AQE **beat** the hand-written
salt. PROGRESS already states that outright, and warns these ratios should not be quoted as a result at
all, because they were measured on stages with 64 tasks versus 5. Caption the worst task, which is the
number visible on the two pages being filmed.

If asked in an interview: *"AQE beat my salt on wall clock. I would still write the salt, because AQE
cannot split every partition - stream-to-static joins and skewed pre-shuffle aggregations are left over.
Implementing it is how I learned why the built-in wins."*

**3. No fixed test count in a caption.** The number has moved three times in one week. Run the suite on the
day, read the screen, caption that. There is a test that fails the build when the documents disagree with
the suite, which is the only reason the figure in Part 8 is current at all.

### Also do not show

- The **dbt step inside the Fabric DAG**. It is deployed and has never run there (HONESTY row 32). dbt
  itself reaching 99/99 on WH_MIZAN is fine, and is Clip `04a`.
- **`-validate` output from the ZATCA SDK.** It still fails the KSA and QR stages, which are documented
  validator defects. Film `--hash`, which is a clean claim. The defects stay written down in HONESTY where
  a reviewer can find them; they do not belong in a 12-second clip that cannot explain them.
- Any claim that a **QR code passed ZATCA validation**.
- Real VAT numbers or customer names.

---

## Part 5. How to click so it reads well on camera

The part most technical demos get wrong.

- **Pause before and after every click.** One second before, so the viewer sees where you are going; two
  to three after, so they see what changed. It will feel painfully slow to you. It is not.
- **Move the mouse in a straight line, slowly.** No circling, no hunting, no wiggling to point at things.
- **Never move the mouse while a caption is on screen.** Movement and reading compete.
- **Scroll two or three notches, then stop.** Fast scrolling is unwatchable on a phone.
- **Let things finish.** If a query takes four seconds, keep all four. The wait *is* the proof that it ran.
- **Dry-run each clip without recording.** Know exactly where everything is before the red light.
- **Auto-zoom fires on clicks.** `05a` and `05b` are keyboard and scroll driven, so turn auto-zoom **off**
  for those two - the hook only reads if the whole scale stays in frame.

---

## Part 6. Editing and export

1. Join in order: `01`, `02a`, `02b`, `03a`-`03d`, `04a`-`04f`, `05a`-`05f`, `06`.
2. Trim dead air. Aim for **2:30**. If you are over, take it from Act 2 and `05c`, never from `04e` or `06`.
3. **Burn the captions in.** LinkedIn's auto-captions mangle "halala", "ZATCA" and "mada". Seven words a
   line, two lines maximum, 1.2 s minimum on screen, bottom third, white on a dark band.
4. **No voice-over.** Most people watch sound-off, so the captions carry it anyway; a voice-over adds
   retakes and reaches nobody the captions do not. Quiet music bed, nothing with a drop.
5. Export **MP4 / H.264, 1080p**. That is the master, for the README and your portfolio.
6. **Then a square cut:** `01`, `03b`, `04e`, `05b`, `06` only, 1:1, about 70 seconds. That is what you
   post. The feed version earns the click; the long one survives the interview.

Motion graphics live in `d:\mizan-video` (`npm run render`). Keep them to roughly 20 seconds of the 2:30 -
animation on top of live Fabric footage reads senior, animation instead of it reads like a showreel.

Tools: DaVinci Resolve or CapCut, both free. The CapCut finishing pass worth copying is chromatic
aberration masked to the frame edges, plus Radial Blur 2 in the corners - five minutes, and it takes the
sterile edge off anything code-rendered.

---

## Part 7. What will go wrong

| What you see | Do this |
|---|---|
| A cell sits on "Queued" for minutes | Cold Spark pool. Part 2, item 5, before recording |
| `AF_MIZAN` has no UI to open | Environment stopped. Part 2, item 1. Takes ~10 min |
| Amber **Snapshot** instead of green **Live** | Fabric session expired; sign in again |
| An UNBALANCED scale under a caption claiming balance | Filmed mid-swing. Wait for it to settle |
| A freshly written table reads empty | SQL endpoint lag. Wait a few minutes after a pipeline run |
| `localhost:8765` does not answer | Restart the showdown server, Part 2 |
| The dbt build takes an hour instead of minutes | Something heavy is running. **Nothing else on the machine while you record** |

**If a live capture fails entirely:** `docs/artifacts/demo/` has eight screenshots at 2400x1500 and
`docs/diagrams/png/` has the six diagrams. Both are legitimate fallbacks and double as a stills carousel.
The demo screenshots come from the **standalone** page, which labels itself *exported Gold snapshot* rather
than *Live* - so if you use one, do not caption it "live DAX".

---

## Part 8. The numbers you are allowed to say

Re-check against `docs/PROOF_MANIFEST.md` on the day. This project's whole argument is that its figures are
derived rather than typed, so a stale caption costs more than it saves.

| | |
|---|---|
| Reconciled | SAR 22,391,236.23 across 2,233 merchant-days |
| Variance | 0.00, on the 2,121 merchant-days whose bank file has arrived |
| Held back | 112 merchant-days, in transit, never counted as balanced |
| ZATCA | 25,001 documents, 0 ICV gaps, 0 PIH breaks |
| ZATCA hash | ZATCA SDK 3.0.8 and MIZAN agree, 3/3 invoices, 44/44 characters |
| Lineage | 94 of 94 Gold columns |
| Scale | 20M rows at 62:1 skew, same checksum three ways. Worst task 15.3 s -> 3.2 s |
| dbt | a 99-node build, green on WH_MIZAN and locally. 99 = 7 models + 89 tests + 3 seeds |
| Tests | **read it off the screen on the day** |
| Lakehouse | 28 tables, 439,192 rows |

Say **"99-node dbt build"**, not "99 dbt tests". There are 89 tests.

Never leave out: **synthetic data**, **not certified by ZATCA or any regulator**, **one engineer with no
second reviewer**, **a reference architecture, not a product**.

---

## Part 9. Why it is built this way (read after you have the footage)

**Why the problem comes before the platform.** An earlier draft opened on the planted error. That is a
strong shot, but it assumes the viewer already knows why matching payments to invoices is hard. Ten seconds
of two files that disagree buys the other 140.

**Why `nb_mizan_walkthrough` is in and my own diagrams are not.** The six SVGs in `docs/diagrams/` are good
for the README, but a picture of an architecture proves nothing about whether that architecture exists. The
notebook displays the diagram and then runs a cell that queries the real lakehouse underneath it. A notebook
nobody has executed is indistinguishable from a screenshot.

**Why the hash showdown earns twelve seconds.** Every other clip asks the viewer to trust the system. That
one shows an external authority's own tool agreeing with yours, on screen, with a tamper button proving it
was computed rather than printed.

**What cannot be shown in Fabric.** Docker, Marquez and GitHub Actions do not run there. Clip `03d` shows
Marquez anyway, and the caption should say so. Naming the gap costs a few seconds and buys more credibility
than hiding it, because anyone who knows Fabric will work it out.

**Why two exports.** 2:30 is the right length to own and the wrong length to post. The feed is people
scrolling on a phone between meetings with the sound off, and a video most people abandon at twenty seconds
gets read as weak and stops being shown. The square 70-second cut earns the click; the people who care
click through to the long one.

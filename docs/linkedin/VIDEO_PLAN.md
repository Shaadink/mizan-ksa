# MIZAN-KSA launch video - the recording plan

**2:30. One receipt -> the five things it sets in motion -> the platform that makes all five agree -> proof.
Recorded clip by clip, then joined.**

1920x1080, 60 fps. Browser at 110%, taskbar and bookmarks hidden, one window, notifications off.
Record each clip on its own, 3 takes, keep the best. Hold still 2 s at the start and end of every clip.
**Pause 1 s before every click** so the auto-zoom has something to lock onto.

No voice-over. Captions are burned in during the edit.

Read Part 1, do Part 2, then record Part 3 clip by clip. Everything after that can wait until you have
the footage. Part 10 is the build sheet for the receipt animation in `D:\mizan-video`, for later.
Supersedes `VIDEO_SHOT_LIST.md`.

---

## Part 1. The ten things you must show

Nothing else earns a place. If a shot does not make one of these points, cut it.

| # | The point | What proves it |
|---|---|---|
| 1 | **The problem is real** | One synthetic receipt splitting into five journeys that must all agree (animation, Act 1) |
| 2 | **It is a real Fabric platform, not scripts** | The workspace, the lakehouse, the lineage view |
| 3 | **It orchestrates itself in the cloud** | Airflow DAG, six green tasks |
| 4 | **It is real code over real data** | `nb_mizan_walkthrough` cells run live on camera |
| 5 | **dbt builds and tests the Gold layer** | `PASS=99 ERROR=0`, then the dbt docs lineage graph |
| 6 | **ZATCA agrees with my hash** | ZATCA's own SDK vs MIZAN, 44/44 characters identical |
| 7 | **The tax chain survives a crash** | 25,001 invoices, 0 ICV gaps, 0 PIH breaks |
| 8 | **It catches mistakes and refuses to ship them** | Press `B`; the scale tilts, the build halts |
| 9 | **Lineage is tracked to the column** | Marquez: a Gold column traced back to Bronze |
| 10 | **It works in Arabic** | Press `L`; the page mirrors, numerals stay left to right |

Then one closing beat: all five journeys return to the balanced scale, **what it is not**, and your name.

**The single most important rule: click things.** A video of a static screen is a screenshot with a
runtime. The value here is that the system *responds*.

### The story spine: one receipt, five journeys

A customer buys something at a till. That one purchase starts five separate journeys, and each is a
problem a Saudi finance team owns:

| Journey | What happens to the receipt | The problem | Marker label |
|---|---|---|---|
| **J1** | The e-invoice goes to ZATCA | It must carry the right hash and chain to the invoice before it | `1/5 · ZATCA e-invoice` |
| **J2** | The mada card payment settles T+1 | Tomorrow's settlement must match today's sale to the halala | `2/5 · mada T+1` |
| **J3** | The bank deposit arrives net of fees | The deposit is not the sale amount, and still has to reconcile | `3/5 · Bank deposit` |
| **J4** | The ERP general ledger records it | The ledger must agree with the bank: GL variance 0.00 | `4/5 · ERP ledger` |
| **J5** | The customer's data is stored | It is personal data, governed under PDPL and NDMO | `5/5 · Customer data` |

The animation introduces the five. Every live clip after it carries a small **receipt journey marker**
(top-left: a receipt glyph with five dots, the active one lit, plus the label above), so the viewer always
knows which of the five problems the footage is solving. Clips that serve all five (the platform itself)
light all five dots and read `Where all five land`.

**The receipt is a synthetic recreation, never a real one.** Made-up store, made-up items, ZATCA's test
VAT number. Exact contents in Part 10.

---

## Part 2. Before you record

### Done already - nothing to do

| | |
|---|---|
| Semantic model deployed | 6/6 relationships verified live in the tenant |
| `nb_mizan_walkthrough` | Ran 31/31 cells, 0 errors, 6 diagrams uploaded |
| Marquez | 94/94 Gold columns, 9 datasets, serving on `localhost:3000` |
| dbt docs | Serving on `localhost:8081` with the lineage graph |
| ZATCA hash showdown | Serving on `127.0.0.1:8765`, verified returning MATCH (5/5 invoices on 2026-11-24) |
| `nb_probe_tmp` | Deleted. Workspace is 15 clean items |

### Still yours

| | Do | Why |
|---|---|---|
| 1 | **Fabric portal -> MIZAN -> `AF_MIZAN` -> Start** | Clip `P2` is impossible until it runs. ~10 min. The REST API refuses service principals on the whole `/environment/` surface, so this one is a portal click |
| 2 | Run `AF_MIZAN` once | So the DAG graph already shows six green boxes when you film it |
| 3 | **Clear all outputs** in `nb_mizan_walkthrough` | So Clip `P3` shows them appearing, not results from my run |
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

The clips keep their old content; they are **renamed and reordered** so the footage follows the receipt
through its five journeys. The old name is in brackets so nothing recorded under the earlier plan is lost.

### Act 1 - The receipt (0:00 - 0:20) - animation, nothing to record

| Clip | Record | Len | Added in the edit |
|---|---|---|---|
| `A1-receipt-opener` | Nothing. Rendered in `D:\mizan-video` (Part 10) | 20 s | A receipt prints (laid out like a real Saudi simplified tax invoice, all details invented); the one purchase splits into the five journeys, each with its problem in one line; ends on *"MIZAN-KSA makes all five agree."* |

This replaces the old title card, facecam and the raw CSV / XML clips (`01`, `02a`, `02b`). Those said
"two files disagree"; the receipt says *why* they disagree and how many parties are involved, in the same
time. The raw files stay on disk as a fallback.

### Act 2 - Where all five land (0:20 - 0:44) - marker: all five dots

| Clip | Record | Len | Added |
|---|---|---|---|
| `P1-lakehouse` [`03a`] | In the Fabric workspace open LH_MIZAN, click into `brz`, then `slv`, then WH_MIZAN `gld` | 6 s | Animated Bronze -> Silver -> Gold flow. Caption: *"All five land in one Fabric lakehouse."* |
| `P2-fabric-airflow` [`03b`] | Open `AF_MIZAN` -> Monitor in Apache Airflow -> `mizan_fabric_daily` -> Graph. Six green boxes. Hover `bronze_land` for the duration tooltip | 8 s | Speed-up, zoom travelling along the chain |
| `P3-walkthrough` [`03c`] | Open `nb_mizan_walkthrough`. Scroll to a diagram, then **run the cell beneath it** and let the real numbers print | 10 s | Caption: *"The diagram, and the query that proves it, in the same notebook."* |

**`P3` is the clip that answers "does he actually work in Fabric".** Everything else in this act could
be a screenshot. A cell that prints a number which was not there a second ago cannot be.

### Act 3 - J1: the e-invoice goes to ZATCA (0:44 - 1:04) - marker `1/5 · ZATCA e-invoice`

| Clip | Record | Len | Added |
|---|---|---|---|
| `J1a-zatca-hash` [`04e`] | `127.0.0.1:8765`, F11. Click **Run live**, wait for MATCH 44/44. Then **Change one digit & run again** | 12 s | Glow on the matching hashes. Caption: *"ZATCA's official SDK vs my pipeline. Same invoice, same hash."* |
| `J1b-zatca-chain` [`04f`] | Command Center: `P` then `5`. Let the chain animate through the amber RETRIED pulse, then drag the crash slider 0 -> 2 until "byte-identical proven" | 8 s | Caption: *"25,001 invoices, 0 chain breaks."* |

**`J1a` is the strongest single clip in the video.** Every other shot asks the viewer to trust your
system. That one shows an external authority's own tool agreeing with yours, computed on screen - and the
tamper button proves it was not pre-rendered. It comes first among the journeys because it is the
receipt's own legal twin, and because the strongest proof should land before the viewer's attention dips.

### Act 4 - J2: the mada payment settles T+1 (1:04 - 1:24) - marker `2/5 · mada T+1`

| Clip | Record | Len | Added |
|---|---|---|---|
| `J2a-drilldown` [`05c`] | Command Center. Click a heatmap cell, then open the MID-day drill panel showing all four legs | 5 s | Cursor highlight, click ripples. Caption: *"Yesterday's sale, today's settlement, to the halala."* |
| `J2b-spark-skew` [`04c`] | The AQE-off stage page, hover the Max row. Then the salted stage | 8 s | Side-by-side. Caption: *"One merchant is 65% of the data. Worst task: 15.3 s -> 3.2 s."* |
| `J2c-ask-mizan` [`05e`] | Ask MIZAN: type *"Which merchants have unsettled payments?"*, show the evidence panel | 7 s | Typing emphasis |

### Act 5 - J3: the bank deposit arrives net of fees (1:24 - 1:40) - marker `3/5 · Bank deposit`

| Clip | Record | Len | Added |
|---|---|---|---|
| `J3a-dbt` [`04a`] | `cd dbt; ..\.venv\Scripts\dbt.exe build --profiles-dir . --target fabric` landing on `PASS=99 ERROR=0` | 5 s | Speed 8x. A time-lapse of a real build is honest; a cut to the finished screen is not |
| `J3b-dbt-docs` [`04b`] | `localhost:8081`. Click the lineage icon, bottom right. Then click `fact_merchant_settlement_recon` to show its tests | 4 s | Caption: *"A 99-node build: 7 models, 89 tests, 3 seeds."* |
| `J3c-home` [`05a`] | Open the Command Center Fabric App. Let the page load so the scales and KPIs animate in. Hands off the mouse | 7 s | Slow push-in. Caption: *"Bank variance 0.00. 112 merchant-days still in transit, never counted as balanced."* |

### Act 6 - J4: the ledger must agree with the bank (1:40 - 1:53) - marker `4/5 · ERP ledger`

| Clip | Record | Len | Added |
|---|---|---|---|
| `J4a-break-it` [`05b`] | Press `B`. The scale tilts, the stamp turns red. Scroll slowly to the red breaker line | 8 s | Auto-zoom on the alert. Caption: *"GL variance must be 0.00. When it isn't, nothing ships."* |
| `J4b-tests` [`04d`] | The suite running, ending on whatever it prints | 5 s | Counter animation on the real number |

### Act 7 - J5: the customer's data (1:53 - 2:10) - marker `5/5 · Customer data`

| Clip | Record | Len | Added |
|---|---|---|---|
| `J5a-governance` [`05f`] | A glimpse of PDPL erasure, then the NDMO scorecard | 4 s | Caption: *"One erasure shreds 5 keys. 25,001 signed tax rows stay under legal hold."* |
| `J5b-marquez` [`03d`] | `localhost:3000`. Start on a Gold table, click a node to expand its columns, pan slowly back to Bronze | 8 s | Glowing path along the lineage edges. Caption: *"94 of 94 Gold columns traced. Marquez runs locally, not in Fabric."* |
| `J5c-arabic` [`05d`] | Press `L`. The layout mirrors, numerals stay left to right | 5 s | Caption: *"Full RTL. The numbers do not flip."* |

Act 3 to Act 7 all use the **Fabric App** (workspace -> `command-center` -> Open) for Command Center
shots, not the local HTML file. The Fabric App says **Live**; the local copy labels itself *exported Gold
snapshot*. Check the label is green before you start - amber means your session expired.

### Act 8 - All five return to the scale (2:10 - 2:24)

| Clip | Record | Len | Added |
|---|---|---|---|
| `A2-scale-close` | Nothing. Rendered in `D:\mizan-video` (Part 10) | 5 s | The five journey lines fly back in from the edges and land as weights on the scale, which settles level on 0.00 |
| `06-wide` | One final wide, still shot of the dashboard | 9 s | Cross-dissolve from `A2`. Animated stats, then what it is not, then your name and LinkedIn |
| `01-facecam` outro (optional) | One closing line to camera: *"I built a platform that reconciles every halala."* | +5 s | Rounded frame, name lower-third. Only if the cut has room |

### The budget, so it can be checked

| Act | Clips | Length |
|---|---|---|
| 1 The receipt | `A1` (animation) | 20 s |
| 2 Where all five land | `P1` `P2` `P3` | 24 s |
| 3 J1 ZATCA e-invoice | `J1a` `J1b` | 20 s |
| 4 J2 mada T+1 | `J2a` `J2b` `J2c` | 20 s |
| 5 J3 Bank deposit | `J3a` `J3b` `J3c` | 16 s |
| 6 J4 ERP ledger | `J4a` `J4b` | 13 s |
| 7 J5 Customer data | `J5a` `J5b` `J5c` | 17 s |
| 8 Close | `A2` (animation) + `06` | 14 s |
| | **Total** | **2:24** |
| | With the optional facecam outro | 2:29 |

Animation: `A1` 20 s + `A2` 5 s = **25 s of 2:24**. Everything else is live footage, and that is what
carries the credibility. Do not let the animation grow past this; if a scene in Part 10 runs long, cut it,
not a live clip.

Six seconds under 2:30 on purpose. Every edit overruns, and the headroom is cheaper than deciding at
midnight which proof to delete.

---

## Part 4. Three things this plan deliberately does NOT claim

Checked against `HONESTY.md` on 2026-11-24. Each of these was in an earlier draft and each is wrong.

**1. No data-residency claim, in any form.** HONESTY row 23 is open: `config/residency_policy.yml` declares
`region: KSA` for every zone, the capacity is in **UAE North**, and the residency gate cannot see the
mismatch. Not showing the region in a 2:30 video is fine. Telling a KSA-residency story is not - and in a
project whose entire differentiator is HONESTY.md, a reviewer who finds the contradiction costs more than
the clip was worth. Film the gate running; claim nothing about where the data physically sits. This
applies to J5 too: "governed under PDPL and NDMO" is fine, "kept in the Kingdom" is not.

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
  itself reaching 99/99 on WH_MIZAN is fine, and is Clip `J3a`.
- **`-validate` output from the ZATCA SDK.** It still fails the KSA and QR stages, which are documented
  validator defects. Film `--hash`, which is a clean claim. The defects stay written down in HONESTY where
  a reviewer can find them; they do not belong in a 12-second clip that cannot explain them.
- Any claim that a **QR code passed ZATCA validation**. The animated receipt has a QR-shaped block because
  a real one would; it is a stylised, non-scannable pattern, and no caption mentions it.
- **A real receipt, real store, real VAT number or real customer name.** The receipt in `A1` is a synthetic
  recreation (Part 10). The fee in J3 is illustrative, not a real mada rate, and is labelled as such.

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
- **Auto-zoom fires on clicks.** `J3c` and `J4a` are keyboard and scroll driven, so turn auto-zoom **off**
  for those two - the shot only reads if the whole scale stays in frame.
- **Leave the top-left corner clear.** The journey marker sits there (about 360x90 px at 1080p). Do not
  park the pointer or a tooltip in that corner.

---

## Part 6. Editing and export

1. Join in order: `A1`, `P1`-`P3`, `J1a`-`J1b`, `J2a`-`J2c`, `J3a`-`J3c`, `J4a`-`J4b`, `J5a`-`J5c`,
   `A2`, `06`.
2. Lay the **journey marker** over every clip from `P1` to `J5c` (Part 10, `JourneyMarker`). Fade it in
   over 10 frames at the start of each act, swap the lit dot on the act's first frame, and hide it under
   `A1`, `A2` and `06`.
3. Trim dead air. Aim for **2:30**. If you are over, take it from `P1` and `J2a`, never from `J1a`, `A1`
   or the close.
4. **Burn the captions in.** LinkedIn's auto-captions mangle "halala", "ZATCA" and "mada". Seven words a
   line, two lines maximum, 1.2 s minimum on screen, bottom third, white on a dark band.
5. **No voice-over.** Most people watch sound-off, so the captions carry it anyway; a voice-over adds
   retakes and reaches nobody the captions do not. Quiet music bed, nothing with a drop. One soft printer
   sound under the first two seconds of `A1` is the only sound effect.
6. Export **MP4 / H.264, 1080p**. That is the master, for the README and your portfolio.
7. **Then a square cut:** `A1` (trimmed to 12 s: print, split, title), `P2`, `J1a`, `J4a`, `A2`, `06`
   only, 1:1, about 70 seconds. That is what you post. The feed version earns the click; the long one
   survives the interview. Render the Remotion scenes a second time at 1080x1080 rather than cropping.

Motion graphics live in `D:\mizan-video` (`npm run render`). Keep them to the 25 seconds in the budget -
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
| The marker covers something that matters | Re-frame in the edit by nudging the clip down/right, or move the marker top-right for that act only |

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
| Variance | 0.00 bank and 0.00 GL, on the 2,121 merchant-days whose bank file has arrived |
| Held back | 112 merchant-days, in transit, never counted as balanced |
| ZATCA | 25,001 documents, 0 ICV gaps, 0 PIH breaks |
| ZATCA hash | ZATCA SDK 3.0.8 and MIZAN agree, 44/44 characters. Matched on 5/5 invoices on 2026-11-24 (earlier runs: 3/3). Caption whatever the showdown prints on the day |
| Lineage | 94 of 94 Gold columns |
| Scale | 20M rows at 62:1 skew, same checksum three ways. Worst task 15.3 s -> 3.2 s |
| dbt | a 99-node build, green on WH_MIZAN and locally. 99 = 7 models + 89 tests + 3 seeds |
| PDPL | One erasure shreds 5 keys; the Restore Guard re-shreds 5 on restore; 25,001 signed tax rows kept under legal hold |
| Tests | **read it off the screen on the day** |
| Lakehouse | 28 tables, 439,192 rows |

Say **"99-node dbt build"**, not "99 dbt tests". There are 89 tests.

The receipt's own amounts (Part 10) are made up for the animation and are **not** project figures. Never
put them next to a number from this table as if they were related.

The hash-showdown count is not in `PROOF_MANIFEST.md` (the manifest tracks Command Center figures), so it is
the one number here that rests on the showdown's own screen. Film it, and caption what it shows.

Never leave out: **synthetic data**, **not certified by ZATCA or any regulator**, **one engineer with no
second reviewer**, **a reference architecture, not a product**.

---

## Part 9. Why it is built this way (read after you have the footage)

**Why a receipt, and why first.** An earlier draft opened on the planted error, and the one after it on two
files that disagree. Both assume the viewer already knows why matching payments to invoices is hard. A
receipt is something every viewer has held. Watching one purchase split into five obligations - tax,
card, bank, ledger, privacy - explains the whole problem in twenty seconds, and gives every later clip a
place to hang: the marker tells the viewer which of the five they are looking at.

**Why only 25 seconds of animation.** The receipt sets up the question; only live footage can answer it.
A viewer who has seen a polished animation and then a real Fabric workspace believes the workspace. A
viewer who sees two minutes of animation believes nothing.

**Why the platform comes before the journeys.** All five journeys land in the same lakehouse and run on the
same DAG. Showing that once, up front, means each journey act can spend its seconds on proof rather than
re-establishing where the data lives.

**Why ZATCA is the first journey.** It is the receipt's legal twin, and `J1a` is the strongest clip.
Putting the best proof at 0:44 rather than at 1:30 catches the viewers who would have left by then.

**Why `nb_mizan_walkthrough` is in and my own diagrams are not.** The six SVGs in `docs/diagrams/` are good
for the README, but a picture of an architecture proves nothing about whether that architecture exists. The
notebook displays the diagram and then runs a cell that queries the real lakehouse underneath it. A notebook
nobody has executed is indistinguishable from a screenshot.

**Why the hash showdown earns twelve seconds.** Every other clip asks the viewer to trust the system. That
one shows an external authority's own tool agreeing with yours, on screen, with a tamper button proving it
was computed rather than printed.

**What cannot be shown in Fabric.** Docker, Marquez and GitHub Actions do not run there. Clip `J5b` shows
Marquez anyway, and the caption says so. Naming the gap costs a few seconds and buys more credibility
than hiding it, because anyone who knows Fabric will work it out.

**Why two exports.** 2:30 is the right length to own and the wrong length to post. The feed is people
scrolling on a phone between meetings with the sound off, and a video most people abandon at twenty seconds
gets read as weak and stops being shown. The square 70-second cut earns the click; the people who care
click through to the long one.

---

## Part 10. Remotion build sheet: the receipt sequence (build later in `D:\mizan-video`)

Not built yet. This is the spec so it can be built in one sitting.

### Compositions

| Composition | Size | fps | Frames | Length | Used as |
|---|---|---|---|---|---|
| `ReceiptOpener` | 1920x1080 | 60 | 1200 | 20 s | `A1` |
| `ScaleClose` | 1920x1080 | 60 | 300 | 5 s | `A2` |
| `JourneyMarker` | 360x90, transparent | 60 | 60 | 1 s, held | Overlay on `P1`-`J5c`. Prop `active: 0-5` (0 = all five lit). Render to ProRes 4444 or PNG sequence for alpha |
| `ReceiptOpenerSquare`, `ScaleCloseSquare` | 1080x1080 | 60 | 720 / 300 | 12 s / 5 s | Square cut, Part 6 step 7 |

Keep the receipt contents in one `receipt.ts` constant so the opener, the square cut and the marker glyph
can never disagree.

### The synthetic receipt (`receipt.ts`)

Everything on it is invented. Do not trace, photograph or copy a real receipt. The **layout** follows a
real Saudi quick-service-restaurant simplified tax invoice (photographed 2026-11-24, kept off disk and out
of the repo), because that is what a Saudi viewer recognises at a glance. No name, number, address, logo,
item or amount from that photo is used.

Top to bottom, every label bilingual (English line, Arabic line under it), thermal-printer monospace:

| # | Block | Value |
|---|---|---|
| 1 | Order number, large | *Your order number is* **0742** |
| 2 | Document type | **SIMPLIFIED TAX INVOICE** / الفاتورة الضريبية المبسطة |
| 3 | Seller | **Dar Al Mizan Trading Co.** / شركة دار الميزان للتجارة (fictional) |
| 4 | Address | `0000;Example St;Riyadh;SA;` in the semicolon style real POS printers use, deliberately not a real street |
| 5 | Branch | Branch #07 · Al Mizan / الميزان · Tel 800-000-0000 |
| 6 | VAT Reg. No. | **312345678900003** - the test organisation identifier in ZATCA's own SDK (`Data/Input/csr-config-example.properties`) |
| 7 | Invoice No. / Date | `INV-SIM-000123` · 2026-11-24 |
| 8 | Order line | `ORD #07-CSO # 03-Time - 19:42:10` |
| 9 | Columns | QTY · PRICE · ITEM · TOTAL / الكمية · السعر · المنتج · المجموع |
| 10 | Items (VAT-inclusive shelf prices) | 1 Dates 1 kg 26.00 · 1 Arabic coffee 250 g 21.00 · 1 Water 6x 12.00 |
| 11 | Total Taxable Amount (Excl VAT) | SAR **51.30** |
| 12 | Total VAT (15%) | SAR **7.70** |
| 13 | Total Amount Due (Incl VAT) | SAR **59.00** |
| 14 | Payment | In-Store Cashless (mada) 59.00 · Change 0.00 |
| 15 | `--E Invoice QR Code--` | Stylised, non-scannable block pattern. No caption |
| 16 | Footer | small grey line: "Synthetic receipt for illustration" |

The amounts are chosen so the receipt is internally consistent the way a real one is: prices are
VAT-inclusive, so the taxable amount is backed out (59.00 / 1.15 = 51.304 -> **51.30**) and 15% of that
rounds to **7.70**, adding back to exactly 59.00. Most round totals do not do this (57.00 gives
49.57 + 7.44 = 57.01). That one-halala trap is real and worth a beat in S2 if there is time; never put a
receipt on screen whose lines do not add up.

Illustrative downstream amounts, used only inside the animation: deposit **SAR 58.57** after a
**SAR 0.43** fee (label it *"illustrative fee"* on screen), GL entry **SAR 59.00**, GL variance **0.00**.

### `ReceiptOpener` scenes (60 fps)

| # | Frames | Time | Visual beat | On-screen text |
|---|---|---|---|---|
| S1 Print | 0-180 | 0:00-0:03 | Dark background. A thermal receipt feeds down from the top of frame, line by line (each line `spring` in, 6 frames apart), slight paper curl, soft printer sound | - |
| S2 The sale | 180-300 | 0:03-0:05 | Camera eases in on the total. A mada card taps the bottom edge; a green tick | *"One purchase. SAR 59.00."* |
| S3 The split | 300-420 | 0:05-0:07 | The receipt tears into five horizontal strips. Each strip flies to its own lane, fanning out left to right; a thin coloured line trails each one | *"It starts five journeys."* |
| S4.1 ZATCA | 420-528 | 0:07-0:08.8 | Lane 1 lights. Strip becomes an XML page; a hash string types out; a chain link snaps it to the previous invoice's hash | *"1 · The e-invoice goes to ZATCA - hashed and chained."* |
| S4.2 mada | 528-636 | 0:08.8-0:10.6 | Lane 2. A calendar flips from 24 to 25 (T+1); a settlement line slides under the sale line and the two halala digits lock | *"2 · The card settles tomorrow - to the halala."* |
| S4.3 Bank | 636-744 | 0:10.6-0:12.4 | Lane 3. A deposit arrives at 58.57; a small tag peels off reading *illustrative fee 0.43*; the two lines are bracketed together | *"3 · The bank pays net of fees - it still must reconcile."* |
| S4.4 Ledger | 744-852 | 0:12.4-0:14.2 | Lane 4. An ERP ledger row and the bank row face each other; a counter rolls down to **0.00** | *"4 · The ledger must agree with the bank. GL variance 0.00."* |
| S4.5 Customer | 852-960 | 0:14.2-0:16 | Lane 5. The customer's details blur behind a shield; two small badges: PDPL, NDMO | *"5 · The customer's data - governed under PDPL and NDMO."* |
| S5 Multiply | 960-1110 | 0:16-0:18.5 | Pull back: all five lanes visible, then the single receipt tiles into a dense wall of receipts as the lanes keep running | *"Five problems. Every receipt. Every day."* |
| S6 Title | 1110-1200 | 0:18.5-0:20 | The five lines converge to a point that becomes the MIZAN scale icon, level. Hard cut to `P1` on frame 1200 | *"MIZAN-KSA makes all five agree."* |

Each S4 beat is 1.8 s: enough for a seven-word caption at the 1.2 s minimum plus the motion. If anything
overruns, shorten S5, never S4.

### `ScaleClose` scenes (60 fps)

| # | Frames | Time | Visual beat | On-screen text |
|---|---|---|---|---|
| C1 Return | 0-120 | 0:00-0:02 | The five coloured lane lines from the opener sweep back in from the frame edges, each carrying its lane icon | - |
| C2 Weigh | 120-240 | 0:02-0:04 | They drop onto the two pans of a large scale, alternating sides. The beam wobbles, then settles level (`spring`, damping high so it does not overshoot twice) | *"Five journeys. One balance."* |
| C3 Hold | 240-300 | 0:04-0:05 | Beam level, **0.00** under the fulcrum. Cross-dissolve into `06-wide` | *"Variance 0.00."* |

Use the same scale drawing as the Command Center so the close visually matches the live dashboard.

### Style

Colours: one per lane, reused by the marker dots (pick five from the Command Center palette so the marker
does not clash with the footage). Type: the Command Center's fonts, with an Arabic face for the receipt
header. Motion: `spring()` for arrivals, `interpolate` with ease-in-out for camera moves, nothing faster
than 8 frames. No glitch effects, no particles - the CapCut finishing pass (Part 6) adds the texture.

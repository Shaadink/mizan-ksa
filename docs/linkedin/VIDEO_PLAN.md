# MIZAN-KSA launch video - the recording plan

**2:30. Shot inside Microsoft Fabric. Seven short clips, recorded separately, then joined.**

Read Part 1, do Part 2, then record Part 3 clip by clip. Everything after that is background and can wait
until you have the footage. Supersedes `VIDEO_SHOT_LIST.md`.

---

## Part 1. The seven things you must show

Nothing else earns a place. If a shot does not make one of these points, cut it.

| # | The point | What proves it |
|---|---|---|
| 1 | **It catches mistakes and refuses to ship them** | Plant a 0.01 SAR error; the build halts |
| 2 | **It is a real Fabric platform, not a folder of scripts** | The workspace task flow and lineage view |
| 3 | **It orchestrates itself in the cloud** | Airflow DAG, six green tasks |
| 4 | **It is real code over real data** | Notebook cells run live on camera |
| 5 | **The money actually reconciles** | A T-SQL query in the warehouse returning 0.00 |
| 6 | **The tax chain survives a crash** | 25,001 invoices, 0 ICV gaps, 0 PIH breaks |
| 7 | **It works in Arabic** | Press `L`; the page mirrors, numerals stay left to right |

Then one closing beat: **what it is not** (synthetic data, not certified, one engineer), and your name.

**The single most important rule: click things.** A video of a static screen is a screenshot with a
runtime. The value here is that the system *responds* - a filter redraws a heatmap, a cell prints a number
that was not there a second ago, a query returns 0.00 while the viewer watches. Every clip below is built
around something changing because you clicked.

---

## Part 2. Before you record (about 20 minutes)

Four of these need **you**, because they need your sign-in or they cost capacity.

| | Do | Why |
|---|---|---|
| 1 | `.\.venv\Scripts\python.exe scripts\fabric_airflow.py start` | **The Airflow environment is Stopped.** Clip 3 is impossible until it runs, and starting takes several minutes. It uses capacity while running, so stop it afterwards. |
| 2 | `.\.venv\Scripts\python.exe scripts\fabric_powerbi.py` | Deploys the fixed semantic model. Without it, Fabric's model view draws one table floating on its own. Needs your `az login` (MFA), which is why I could not run it. |
| 3 | Delete **`nb_probe_tmp`** from the workspace | My debugging leftover. It shows in the workspace list and in the lineage view. |
| 4 | Open the workspace; check the **task flow** band is across the top | There is no API to verify it. If it is missing, import `docs/fabric/mizan_task_flow.json` (`docs/PORTAL_STEPS.md` 4.4). |
| 5 | `.\.venv\Scripts\python.exe scripts\fabric_walkthrough.py` | Re-runs the walkthrough notebook so its figures are today's. Then **clear all outputs** in the notebook, so Clip 4 shows them appearing. |
| 6 | Run `AF_MIZAN` once | So the DAG graph already shows six green boxes when you film it. |
| 7 | Open any notebook and run one cell | Warms the Spark pool. A cold pool sits on "Queued" for minutes and you cannot edit that out invisibly. |
| 8 | Open the Command Center; check the label bottom-left says **Live** in green | Amber **Snapshot** means your Fabric session expired. Sign in again. |

**Machine setup**

- OBS Studio (free). Display capture, 1920x1080, 30 fps.
- Browser at **100% zoom**, dark mode, full screen (`F11`), bookmarks bar hidden, one window only.
- **Notifications off.** Focus Assist on; close Teams, Outlook, WhatsApp. One toast ruins a take.
- **Make the mouse cursor bigger** (Settings -> Accessibility -> Mouse pointer, size 2 or 3). At 1080p
  shrunk into a phone feed the default pointer is invisible, and half this video is "watch where I click".

---

## Part 3. The seven clips

Record each one **separately**. Three takes each, keep the best. Do not attempt one continuous take - you
will fail at minute four and start again, five times.

Lengths below are the *edited* length. Record a few still seconds at the start and end of each so you have
room to cut.

### Clip 1 - The hook (15 s) - Command Center

The planted error. First thing anyone sees, so re-record this until it is right.

1. Open the **Command Center** app. Wait for the gold scale to settle level. **Hold still 2 seconds.**
2. Press **`B`**.
3. The scale tilts, the stamp turns red. **Hold still 3 seconds.** Do not move the mouse.
4. Scroll down slowly until the red breaker line is in frame:
   `dbt circuit breaker - FAIL - 2 unexplained MID-days - build halted` and
   `Candidate run x FAIL - not published`. **Hold 3 seconds.**
5. Press **`B`** again; the scale settles. Stop recording.

Captions: *"I hid a 0.01 SAR error in 22 million rows."* then *"It found it, and refused to publish."*

### Clip 2 - It is a real platform (20 s) - workspace

1. Open the workspace **`mizan-ksa-dev`**. Let the **task flow** band at the top finish drawing.
2. **Click the `Store` task.** The right-hand pane opens showing its items. Hold 3 seconds.
3. Close the pane.
4. **Click `Lineage`** (top right). Let the graph draw.
5. **Hover the semantic model node** so its connections highlight. Hold 3 seconds.

Caption: *"Seven tasks. Fabric drew the lineage itself."*

### Clip 3 - It runs itself (25 s) - Airflow

Only possible once the environment is started (Part 2, step 1).

1. Workspace -> click **`AF_MIZAN`**.
2. Click **Monitor in Apache Airflow**. The Airflow UI opens in a new tab.
3. Click the DAG **`mizan_fabric_daily`**.
4. Click the **Graph** tab. Six boxes, all green, with the fan-out after `zatca_chain`.
5. **Hover `bronze_land`** so the duration tooltip appears. Hold 3 seconds.

Caption: *"Apache Airflow, running as a Fabric item. It starts six PySpark notebooks."*

### Clip 4 - Real code, real data (35 s) - the walkthrough notebook

The most important clip after the hook, because output appears **while the viewer watches**. A notebook
with its output already in it looks exactly like a screenshot.

1. Open **`nb_mizan_walkthrough`**.
2. Scroll to **section 1**, the architecture diagram. Hold 2 seconds.
3. Scroll to **section 2**. Click into the code cell, then click **Run** (or `Shift+Enter`).
4. **Touch nothing while it runs.** The table prints: 28 tables, 439,192 rows. Hold 3 seconds.
5. Scroll to **section 5**, the ZATCA state machine diagram. Hold 2 seconds.
6. Run that cell: 25,001 documents, **0 ICV gaps, 0 PIH breaks**. Hold 3 seconds.

Captions: *"Read live, through the same code the jobs run."* then *"25,001 e-invoices. Zero chain breaks."*

### Clip 5 - The money reconciles (25 s) - the warehouse

**Type the query. Do not paste it.** Watching someone type a query and get 0.00 is the most convincing
thing in this video, and pasting throws that away.

1. Workspace -> click **`WH_MIZAN`**.
2. Click **New SQL query**.
3. Type:
   ```sql
   SELECT SUM(unexplained_bank_variance_sar) AS bank_variance,
          SUM(unexplained_gl_variance_sar)   AS gl_variance
   FROM gld.fact_merchant_settlement_recon;
   ```
4. Click **Run**. Two zeros come back. Hold 4 seconds.

Caption: *"SAR 22.39M across 2,233 merchant-days. Both variances: zero."*

### Clip 6 - Interrogable, and bilingual (30 s) - Command Center

1. Back in the Command Center. In the filter bar, **choose City = Jeddah**.
2. Scroll to the Reconciliation scene; the **heatmap redraws**. Hold 3 seconds.
3. **Click one bright cell.** The drill panel opens with every leg of that merchant-day. Hold 4 seconds.
4. Click **Clear**.
5. Press **`L`**. The page flips to Arabic, right to left. Hold 4 seconds - long enough to see that the
   numerals still read left to right.
6. Press **`L`** again.

Captions: *"Filter a city, everything recomputes."* then *"Arabic, right to left. The numbers do not flip."*

### Clip 7 - What it is not, and your name (15 s)

1. Back in `nb_mizan_walkthrough`, scroll to **section 8**. Hold 5 seconds while the limits are readable.
2. Cut to a still card: **MIZAN-KSA**, your name, `github.com/Shaadink/mizan-ksa`.

Captions: *"Synthetic data. Not ZATCA-certified. One engineer, no second reviewer."* then *"Built by
Shadin K. Repo in the comments."*

Keep this clip. Most people would cut it. Everyone technical still watching at 2:15 is already thinking
*"but is any of this real?"*, and answering before they ask is worth more than another feature.

---

## Part 4. How to click so it reads well on camera

The part most technical demos get wrong.

- **Pause before and after every click.** One second before, so the viewer sees where you are going; two
  to three seconds after, so they see what changed. It will feel painfully slow to you. It is not.
- **Move the mouse in a straight line, slowly.** No circling, no hunting, no wiggling to point at things.
- **Never move the mouse while a caption is on screen.** Movement and reading compete.
- **Scroll in small amounts.** Two or three notches, then stop. Fast scrolling is unwatchable on a phone.
- **Let things finish.** If a query takes four seconds, keep all four. The wait *is* the proof that it ran.
- **Click accurately.** A mis-click and a correction costs three seconds and looks unrehearsed.
- **Dry-run each clip without recording.** Know exactly where everything is before the red light.

---

## Part 5. Editing and export

1. Join the seven clips in order.
2. Trim dead air at the start and end of each. Aim for **2:30**; if you are over, take it out of Clips 2
   and 6, never Clip 1 or Clip 7.
3. **Burn the captions in.** Do not rely on LinkedIn's auto-captions - they will mangle "halala", "ZATCA"
   and "mada". Seven words a line, two lines maximum, at least 1.2 seconds on screen, bottom third, white
   on a dark band.
4. **No voice-over.** Most people watch with sound off, so the captions carry it anyway; a voice-over adds
   retakes and reaches nobody the captions do not. Quiet music bed, nothing with a drop.
5. Export **MP4 / H.264, 1080p**. That is the master, for the README and your portfolio.
6. **Then export a second, square version:** Clips 1, 3, 5, 6, 7 only, cropped to 1:1, about 70 seconds.
   That is what you post. The feed version earns the click; the long one survives the interview.

Tools: DaVinci Resolve or CapCut. Both free, both do square crops and burned-in captions.

---

## Part 6. What will go wrong

| What you will see | Do this |
|---|---|
| A cell sits on "Queued" for minutes | Cold Spark pool. Part 2, step 7, before recording |
| `AF_MIZAN` has no UI to open | Airflow stopped. Part 2, step 1. Takes several minutes |
| Amber **Snapshot** instead of green **Live** | Your Fabric session expired; sign in again |
| An UNBALANCED scale under a caption claiming balance | Filmed mid-swing. Wait for it to settle before starting |
| A freshly written table reads empty | SQL endpoint lag. Wait a few minutes after a pipeline run |

**If a live capture fails entirely:** `docs/artifacts/demo/` has eight screenshots at 2400x1500 and
`docs/diagrams/png/` has the six diagrams. Both are legitimate fallbacks and double as a stills carousel.
The demo screenshots come from the **standalone** page, which labels itself *exported Gold snapshot*
rather than *Live* - so if you use one, do not caption it "live DAX".

---

## Part 7. The numbers you are allowed to say

Re-check against `docs/PROOF_MANIFEST.md` on the day. This project's whole argument is that its figures
are derived rather than typed, so a stale caption costs more than it saves.

| | |
|---|---|
| Reconciled | SAR 22,391,236.23 across 2,233 merchant-days |
| Variance | 0.00, on the 2,121 merchant-days whose bank file has arrived |
| Held back | 112 merchant-days, in transit, never counted as balanced |
| ZATCA | 25,001 documents, 0 ICV gaps, 0 PIH breaks |
| Lineage | 94 of 94 Gold columns |
| Scale | 20M rows at 62:1 skew, same checksum three ways |
| dbt | a 99-node build, green on WH_MIZAN and locally. 99 = 7 models + 89 tests + 3 seeds |
| Tests | 444 Python, 184 Fabric App (183 pass, 1 skipped) |
| Lakehouse | 28 tables, 439,192 rows |

Say **"99-node dbt build"**, not "99 dbt tests". There are 89 tests.

Never leave out: **synthetic data**, **not certified by ZATCA or any regulator**, **one engineer with no
second reviewer**, **a reference architecture, not a product**.

---

## Part 8. Why it is built this way (read after you have the footage)

**Why open on the failure.** Seconds 0-3 are the only ones you are guaranteed. A workspace item list is a
screenshot of a filing cabinet. A planted error the system catches states the problem, shows the stakes
and proves the thing is adversarial rather than decorative - in two seconds, with no explanation.

**Why Fabric's own diagrams and not mine.** The six SVGs in `docs/diagrams/` are good for the README, but
a picture of an architecture proves nothing about whether that architecture exists. The task flow, the
lineage view and the model view are rendered by Fabric from the real items: if something were missing or
disconnected, those diagrams would show it. That is why they are in the video and the drawings are not.

**What cannot be shown in Fabric.** Docker, Marquez and GitHub Actions do not run there. If you want them,
add one four-second cut between Clips 5 and 6 - Marquez column lineage and a green GitHub Actions run -
captioned *"OpenLineage and CI: the half that does not run in Fabric."* Naming the gap costs four seconds
and buys more credibility than any feature.

**Why two exports.** 2:30 is the right length to own and the wrong length to post. The feed is people
scrolling on a phone between meetings with the sound off, and a video most people abandon at twenty
seconds gets read as weak and stops being shown. The square 70-second cut earns the click; the people who
care click through to the long one.

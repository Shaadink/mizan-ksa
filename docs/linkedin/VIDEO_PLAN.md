# MIZAN-KSA launch video - the plan

This supersedes `VIDEO_SHOT_LIST.md`. One recording session, two exports.

---

## Part 0. The three decisions, argued

Everything below follows from these. If you disagree with one, the shot list changes.

### Decision 1 - two cuts, not one. Master 2:30, LinkedIn cut 1:10.

A 2:30 video is the right thing to **own** and the wrong thing to **post**.

The research baseline in `MASTER_BRIEF.md` puts organic LinkedIn video at 30-90 seconds with completion
above 60% in that band, and reads a retention cliff at 8-12 seconds as a body-content failure. A 2:30 cut
posted cold to a feed asks for 150 seconds of attention from someone scrolling between meetings with the
sound off. Most will leave at 20 seconds, and LinkedIn reads a 13% completion rate as a weak video and
stops showing it.

But a 2:30 **is** the right asset for the three places that matter after the post lands: the repo README,
the portfolio site, and the recruiter or hiring manager who clicked through because the short one worked.
Those people have already opted in. They want the long version.

So: record once, export twice.

| | **The LinkedIn cut** | **The master** |
|---|---|---|
| Length | **1:10** | **2:30** |
| Aspect | **1:1 square** (fills more of a phone feed) | **16:9** |
| Where | the LinkedIn post, native upload | README, portfolio, the link in the post's first comment |
| Job | earn the click | survive the scrutiny |

The master is a superset. Every shot in the short cut is a shot in the long one, so the short is an edit,
not a second shoot.

### Decision 2 - open on the failure, not on the platform.

The current shot list opens with six seconds of scrolling a Fabric workspace item list. That is the single
weakest opening available to this project. An item list is a screenshot of a filing cabinet. Nobody has
ever stopped scrolling for one, and seconds 0-3 are the only ones you are guaranteed to get.

Open instead on the one thing in this project that is impossible to fake and takes two seconds to
understand: **a 0.01 SAR error, planted on purpose, and a build that refuses to publish because of it.**

That hook does four jobs at once. It states the problem (money that does not add up), it shows the stakes
(it is one halala out of twenty-two million riyals), it proves the system is adversarial rather than
decorative, and it sets up a callback you can pay off at 1:30 when you press `B` live on camera.

The platform credibility shot - Airflow, six green tasks, nothing on my laptop - is the **second** beat,
not the first. It is the strongest argument you have and the second-weakest hook you have, because a viewer
has to already care before a DAG graph means anything.

### Decision 3 - captions only. No voice-over.

Most LinkedIn video is watched with the sound off, so the captions have to carry the whole thing anyway.
Once they do, a voice-over adds risk (retakes, pacing, a self-conscious read) and adds nothing a silent
viewer receives. It also doubles your edit time on the day you are least patient.

Add a quiet music bed at about -24 LUFS, something without a drop or a build. Its only job is to stop the
video feeling broken when someone does have sound on.

A voice-over version is a cheap later export if you want one for YouTube. It is not the launch asset.

---

## Part 1. The master, 2:30, shot by shot

Five acts. Each act has one job, written next to it. If a shot does not serve its act's job, it is cut -
that rule is what keeps a 2:30 from becoming a 4:00.

### Act 0 - The hook (0:00 - 0:08). Job: buy the next ten seconds.

No logo. No title. No "hi, I'm Shadin". Branding at the front costs retention; it goes at 2:15.

| Time | On screen | Caption |
|---|---|---|
| 0:00 - 0:03 | The Command Center hero, full frame, gold scale **level**. Then it tilts and the stamp flips red. Capture this by pressing `B` and starting the clip one second before the tilt. | I hid a 0.01 SAR error in 22 million rows. |
| 0:03 - 0:08 | Hard cut to the breaker line, filling the frame: `dbt circuit breaker - FAIL - 2 unexplained MID-days - build halted`, and `Candidate run x FAIL - not published`. Hold still. | It found it, and refused to publish the day. |

The second caption is the thesis of the entire project. Everything after it is evidence.

### Act 1 - What it is (0:08 - 0:25). Job: make the problem legible to a non-specialist.

| Time | On screen | Caption |
|---|---|---|
| 0:08 - 0:13 | Scene 9, the life cycle: sources to Gold to the Control Tower. Slow push in. | MIZAN: one Saudi retail sale, followed end to end. |
| 0:13 - 0:19 | Hold on the four source boxes, highlight each as the caption names it | The till, ZATCA, the bank, the ledger. Four systems that disagree. |
| 0:19 - 0:25 | Cut to the hero, scale level, SAR 22,391,236.23 and the 0.00 tile both visible | SAR 22.39M reconciled to exactly 0.00. |

### Act 2 - It runs itself, in the cloud (0:25 - 0:58). Job: separate this from every portfolio project.

This act is the one a data engineer is actually judging you on. Do not rush it; four shots, eight seconds
each, mouse still.

| Time | On screen | Caption |
|---|---|---|
| 0:25 - 0:33 | **AF_MIZAN -> Monitor DAG -> Graph**: `mizan_fabric_daily`, six green tasks, the fan-out from `zatca_chain`. Hover `bronze_land` so the duration tooltip appears | Apache Airflow, running inside Microsoft Fabric. |
| 0:33 - 0:41 | Fabric Monitoring hub, filtered to today: the same six notebook runs, all **Succeeded**, timestamps seconds after the DAG tasks | Six real Fabric notebook runs. Nothing runs on my laptop. |
| 0:41 - 0:50 | Terminal, `dbt build --target fabric` scrolling to **PASS=99 ERROR=0**. Let it actually run; do not cut to a finished screen | dbt builds and tests the Gold layer in the warehouse: 99 of 99. |
| 0:50 - 0:58 | GitHub Actions, newest run, three green jobs | And the whole suite runs on every push. 444 tests. |

Use `--target fabric`, not the local DuckDB target. Both are 99/99 now, so the Fabric one is free and says
"a warehouse in the cloud" instead of "a file on my laptop".

### Act 3 - The proof, in the app (0:58 - 1:58). Job: show that it is interrogable, not a dashboard.

| Time | On screen | Caption |
|---|---|---|
| 0:58 - 1:04 | Open the app from the workspace. Hero settles. Mouse rests on the green **Live** label, bottom left | Live DAX against the semantic model. |
| 1:04 - 1:11 | Mouse to the amber chip: `112 MID-days not assessed (bank file pending)` | 112 days have no bank file yet. They are never called balanced. |
| 1:11 - 1:19 | Filter bar: **City = Jeddah**. Scroll to Reconciliation; the heatmap redraws | Every filter re-queries the model. |
| 1:19 - 1:29 | Click one bright heatmap cell. The drill panel opens | One merchant, one day: captures, fees, bank paid, GL, both variances. |
| 1:29 - 1:38 | **Clear**. Press `B`. Scroll up; the scale tilts, the stamp reddens, the candidate run is flagged | This is the error from the first three seconds. |
| 1:38 - 1:41 | Press `B` again. The scale settles | |
| 1:41 - 1:50 | Menu: **ZATCA**. Hover the EGS cards, then the outcome bar. Type `102` in search, Enter | 25,001 e-invoices. Zero chain breaks. |
| 1:50 - 1:58 | Hold on ICV 102's history row, then press `L` for Arabic, hold two seconds | A timeout and a worker crash. Retried with the identical signed bytes. |

The `L` press is where the RTL layout gets its three seconds. It is also a KSA hiring signal that costs you
nothing: the page works in Arabic and the numerals still read left to right.

### Act 4 - The honest part (1:58 - 2:15). Job: convert a skeptic.

This act is the differentiator and most people will cut it. Do not. Every technical viewer watching at 2:00
is already composing the question "but is any of this real?" Answering it before they ask is worth more
than another feature.

| Time | On screen | Caption |
|---|---|---|
| 1:58 - 2:07 | `HONESTY.md` on GitHub, scrolling slowly through the table. Let the row count be visible | I also wrote down everything it is not. |
| 2:07 - 2:15 | Cut to the proof manifest, a SHA-256 per claim | Synthetic data. Not certified by ZATCA. One engineer, no second reviewer. Every number generated, never typed. |

### Act 5 - End card (2:15 - 2:30). Job: one action, not five.

| Time | On screen | Caption |
|---|---|---|
| 2:15 - 2:30 | Static card: **MIZAN-KSA**, your name, `github.com/Shaadink/mizan-ksa`. Nothing animated | Built by Shadin K. Repo in the comments. |

One call to action. Not "follow, like, connect, DM and star".

---

## Part 2. The LinkedIn cut, 1:10, square

Same footage, harder edit. Nothing new is recorded for this.

| Time | From the master | Caption |
|---|---|---|
| 0:00 - 0:06 | Act 0, both shots, trimmed | I hid a 0.01 SAR error in 22 million rows. / It found it, and refused to publish. |
| 0:06 - 0:12 | Act 1, the hero with 22.39M and 0.00 | One Saudi retail sale, end to end. SAR 22.39M to exactly 0.00. |
| 0:12 - 0:26 | Act 2: Airflow (5s), dbt PASS=99 (5s), CI green (4s) | Airflow inside Microsoft Fabric. dbt 99/99 in the warehouse. 444 tests on every push. |
| 0:26 - 0:40 | Act 3: Live label (4s), Jeddah filter (5s), the drill (5s) | Live DAX. Filter a city, everything recomputes. Drill one merchant-day. |
| 0:40 - 0:50 | Act 3: ZATCA + ICV 102 | 25,001 e-invoices, zero chain breaks - through a timeout and a worker crash. |
| 0:50 - 0:54 | Act 3: the `L` flip | Arabic, right to left. |
| 0:54 - 1:02 | Act 4, compressed to one card over the HONESTY scroll | Synthetic data. Not ZATCA-certified. Every number generated, never typed. |
| 1:02 - 1:10 | Act 5 | Built by Shadin K. Repo in the comments. |

Crop to 1:1 from the 1920x1080 source. Record at 1920x1080 and crop in the edit - do not record square, or the
app's right-hand rail will be cut off at capture time and you cannot get it back.

---

## Part 3. How to actually record it

### Record in blocks, not in timeline order

Four sittings. Within each block, record each shot **three times** and keep the best. Retaking a shot an
hour later means re-signing in, re-warming the pool and re-matching the window size.

| Block | What | Watch out for |
|---|---|---|
| **A. Fabric browser** | workspace, Airflow DAG graph, Monitoring hub | Sign in first. Run the DAG **before** you record so the six boxes are already green. |
| **B. Terminal** | `dbt build --target fabric`, `pytest -q` | Run them for real on camera. A cut to a finished screen looks exactly like what it is. |
| **C. The app** | everything in Act 3 | Press `P` for presenter mode where the chrome is noise. Check the label says **Live** in green, not amber. |
| **D. GitHub** | Actions, HONESTY.md, the proof manifest | Light mode or dark mode - pick one and keep it for all four shots. |

### Settings

- **Capture:** OBS Studio (free), display capture, 1920x1080, 30 fps, CQP 18. Windows Game Bar works too but
  gives you less control over the cursor.
- **Browser:** zoom 100%, dark mode, full screen (`F11`), bookmarks bar hidden, one window, no second monitor
  bleeding in.
- **Notifications off.** Windows Focus Assist on. Close Teams, Outlook, Slack, the lot. One toast ruins a take.
- **Cursor:** enlarge it slightly in Windows mouse settings. At 1080p scaled into a phone feed, the default
  pointer disappears.
- **Edit:** DaVinci Resolve (free) or CapCut. Both do square crops and burned-in captions.
- **Export:** MP4, H.264, 1080p for the master; 1080x1080 for the cut. Burn the captions in - do not rely on
  LinkedIn's auto-captions, which will mangle "halala", "ZATCA" and "mada".

### Caption rules

- Seven words a line, two lines maximum.
- On screen at least 1.2 seconds, however short the line.
- Bottom third, white text, 55-65% black scrim behind it so it survives a bright heatmap.
- One idea per caption. If a caption needs an "and", it is two captions.
- Never caption a replay or a proof-run scene as "live". The stream, PDPL, MDM and Spark scenes are replays
  and their provenance line says so on screen - do not contradict your own page.

### What will go wrong

- **The Fabric starter pool is cold** and the first notebook sits "Queued" for minutes. Warm it before Block A
  by running anything trivial.
- **The SQL analytics endpoint lags** behind the lakehouse, so a freshly written table can read empty. Give it
  a few minutes before you film a figure.
- **The app shows an amber "Snapshot" label** if your Fabric session expired. Sign in again; do not film it.
- **The scale is mid-swing.** It physically settles over several seconds. Start the clip after it stops, or
  you have filmed an UNBALANCED scale while the caption claims balance.

### If a live capture fails

`docs/artifacts/demo/` holds the eight screenshots at 2400x1500, taken from the standalone page. They are a
legitimate fallback for any app shot, and they are also the carousel if you post stills alongside the video.
They label themselves *exported Gold snapshot* rather than *Live* - so if you use one, do not caption it
"live DAX". Everything else about them is the same code and the same figures.

---

## Part 4. The numbers you are allowed to say

Every figure in the captions above traces to a generated artifact. These are the current ones; re-check
them against `docs/PROOF_MANIFEST.md` on the day you record, because this project's whole argument is that
its numbers are derived rather than typed.

| | |
|---|---|
| Reconciled | SAR 22,391,236.23 across 2,233 merchant-days |
| Variance | 0.00, on the 2,121 merchant-days whose bank file has arrived |
| Held back | 112 merchant-days, in transit, never counted as balanced |
| ZATCA | 25,001 documents, 0 chain breaks |
| Lineage | 94 of 94 Gold columns |
| Scale test | 20M rows at 62:1 skew, same checksum three ways |
| dbt | 99/99 on WH_MIZAN and 99/99 on the local target |
| Tests | 444 Python, 184 Fabric App (183 pass, 1 skipped) |

And the four you must not leave out: **synthetic data**, **not certified by ZATCA or any regulator**,
**one engineer with no second reviewer**, **standards-informed reference architecture, not a product**.

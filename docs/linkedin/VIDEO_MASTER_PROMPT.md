# Master prompt: MIZAN-KSA LinkedIn launch video plan

Paste everything below the line into each AI (ChatGPT, Gemini, Claude, Grok, etc.). Use the same prompt
unchanged for every AI, so the answers can be compared and merged section by section.

---

You are a senior creative director for technical product videos, and you have also worked for years as a
senior data engineer at a Gulf bank. You know what makes a hiring manager or a principal data engineer stop
scrolling on LinkedIn, and you know what makes them roll their eyes.

I need a complete, recordable plan for a **2:30 LinkedIn launch video** of my portfolio project,
**MIZAN-KSA**. Read the whole brief before answering. Then answer in exactly the format at the end.

## 1. Who I am and what the video is for

- I am a data engineer building a portfolio for senior data engineering roles in Saudi Arabia and the GCC.
- The video goes on LinkedIn. Goal: a senior data engineer, data architect or hiring manager watches it and
  thinks *"this person builds production-grade platforms, understands Saudi finance and regulation, and is
  honest about limits."*
- Most viewers watch on a phone, with the sound off, scrolling between meetings. Many leave in the first
  5-20 seconds.
- I will also post a **square ~70 s cut** for the feed; the 2:30 version is the master for my README,
  portfolio and interviews.

## 2. What MIZAN-KSA is

A reference architecture on **Microsoft Fabric** that reconciles Saudi retail payments to the halala, end to
end, on synthetic data.

**The business problem, told through one retail receipt.** One purchase at a till starts five journeys,
and each is a real problem a Saudi finance team owns:

1. **The e-invoice goes to ZATCA** (the Saudi tax authority). Phase-2 e-invoicing: every invoice must carry
   the correct cryptographic hash and chain to the previous invoice (ICV counter + previous-invoice hash).
2. **The mada card payment settles T+1** (mada is the Saudi debit network). Tomorrow's settlement must match
   today's sale to the halala (1/100 SAR).
3. **The bank deposit arrives net of fees.** The deposit is not the sale amount, and still has to reconcile.
4. **The ERP general ledger** must agree with the bank. Target: GL variance 0.00.
5. **The customer's data** is personal data, governed under **PDPL** (Saudi data protection law) and
   **NDMO** (national data governance standards).

**What is built (all real and demonstrable on screen):**

| Area | What exists |
|---|---|
| Platform | Fabric workspace with lakehouse LH_MIZAN (Bronze / Silver), warehouse WH_MIZAN (Gold), semantic model, 15 workspace items, task-flow band |
| Orchestration | Fabric's managed Apache Airflow (`AF_MIZAN`): DAG `mizan_fabric_daily`, six tasks, ran green end to end in 15 min |
| Live notebook | `nb_mizan_walkthrough`: shows an architecture diagram, then runs a cell beneath it that queries the real lakehouse and prints the numbers |
| dbt | 99-node build green on WH_MIZAN (7 models + 89 tests + 3 seeds), dbt docs lineage graph |
| ZATCA hash proof | A "hash showdown" page: ZATCA's own official SDK (v3.0.8) and my pipeline hash the same invoice; 44/44 characters identical, matched on 5/5 invoices. Has a "change one digit and run again" tamper button that breaks the match live |
| ZATCA chain | 25,001 invoices, 0 ICV gaps, 0 chain breaks, survives a worker crash mid-submit (crash slider in the UI proves byte-identical output) |
| Reconciliation | SAR 22,391,236.23 across 2,233 merchant-days; bank variance 0.00 and GL variance 0.00 on the 2,121 merchant-days whose bank file has arrived; 112 still in transit and never counted as balanced |
| Command Center | A dashboard (published as a Fabric App, labelled "Live") with balance scales per merchant-day. Press `B` to plant an error: the scale tilts, a red stamp appears, the build halts. Heatmap drill-down to a merchant-day showing all four legs. Press `L` for full Arabic RTL (numbers stay left to right). "Ask MIZAN" natural-language question box with an evidence panel |
| Spark at scale | 20M-row skew benchmark (one merchant = 65% of data). Worst task 15.3 s -> 3.2 s with salting. Same checksum in every mode |
| Lineage | Marquez / OpenLineage: 94 of 94 Gold columns traced back to Bronze (runs locally in Docker, not in Fabric) |
| Governance | PDPL erasure via crypto-shredding (one erasure shreds 5 keys; a Restore Guard re-shreds on restore); 25,001 signed tax rows kept under legal hold; NDMO classification scorecard; Arabic MDM (2,552 golden customers) |
| Honesty | A public `HONESTY.md` listing every limitation and open issue, and a `PROOF_MANIFEST.md` linking each headline number to the proof file and its SHA-256. This is the project's differentiator |

## 3. Hard rules - your plan must not break these

1. **No data-residency claim** of any kind ("data stays in the Kingdom" etc.). The Fabric capacity is in UAE
   North; this is documented as an open issue.
2. **No "5x faster" claim** on the Spark benchmark. Only "worst task 15.3 s -> 3.2 s". On total job time,
   Spark's built-in AQE was actually faster than my salting.
3. **No fixed test count** in a caption. The automated test count changes; I read it off the screen on the
   day.
4. **Do not show ZATCA SDK `-validate` output** (it fails stages because of documented validator defects).
   Show the hash comparison only.
5. **No claim that a QR code passed ZATCA validation.**
6. **No real receipt, store, VAT number or customer name.** Any receipt must be a synthetic recreation with a
   made-up store and ZATCA's test VAT number.
7. Say **"99-node dbt build"**, never "99 dbt tests".
8. The video must make clear somewhere: **synthetic data, not certified by ZATCA or any regulator, built by
   one engineer, a reference architecture not a product.**
9. Use only the numbers in section 2. Do not invent metrics, users, clients, cost savings or time savings.

## 4. Production constraints

- 1920x1080, 60 fps master; 1080x1080 square cut.
- **No voice-over.** Burned-in captions only (max 7 words per line, 2 lines, 1.2 s minimum on screen).
  Quiet music bed.
- Screen recordings of the real system carry the credibility. **Motion graphics: about 25 seconds total**,
  made in Remotion (React-based video). Too much animation reads like a showreel, not engineering.
- Editing in DaVinci Resolve or CapCut. Auto-zoom on clicks is available.
- I record clip by clip, so give me **discrete clips** with a clear action for each.

## 5. What I want from you

Be specific and opinionated. Give me your best version, not a menu of options. Where you disagree with my
setup (the receipt story, 2:30 length, no voice-over, 25 s of animation), say so and say why in section H.

## 6. Answer format - use exactly these headings, in this order

**A. The one-sentence story** - what the viewer should remember after 2:30.

**B. The hook (first 5 seconds)** - exactly what is on screen and what the caption says, frame by frame. Give
your best one and one alternative.

**C. Video structure** - a table: Act | Time range | Purpose | Seconds. Must total 2:20-2:30.

**D. Shot list** - a table with one row per clip: Clip ID | Act | What I record or animate (exact action) |
Seconds | On-screen caption (exact words) | Which of the five receipt journeys it proves (or "platform").
Mark animated clips clearly.

**E. The 5 most impressive moments** - which clips will make a senior data engineer stop and why, ranked.

**F. What signals "senior data engineer"** - the specific things to show, say or caption that separate this
from a junior portfolio project (architecture choices, failure handling, idempotency, lineage, testing,
honesty about trade-offs...). And what to avoid because it reads junior.

**G. Design and motion ideas** - colour palette (hex), typography, caption style, transitions, the receipt
animation scene by scene with timings, recurring visual motifs, how live footage and animation connect,
music mood. Concrete enough for me to build.

**H. Where you would change my plan** - anything in sections 3-4 you think is wrong, with your reasoning.
(You may not break the hard rules in section 3.)

**I. The square 70-second feed cut** - which clips, in which order, with timings.

**J. The LinkedIn post text** - the post that goes with the video: hook line, 4-6 short lines, 3-5 hashtags.

**K. Risks** - three things most likely to make this video look weak or dishonest, and how to avoid them.

Keep the whole answer under 2,000 words, except section D, which can be as long as it needs to be.

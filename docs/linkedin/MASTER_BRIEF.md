# MIZAN-KSA — master brief for creative/video AI consultations

Paste the whole of this file into each AI. It is self-contained: it carries the verified facts, the
limitations, the audience and the research baseline, so the answers come back grounded instead of generic.

**Why it is built this way.** A brief that says "I will provide project materials" gets you an essay about a
project the model invented. A brief that carries the numbers and the limitations gets you a plan you can
actually shoot. The limitations are included *on purpose*: they stop a model writing claims that would fall
apart in a technical interview, and they are the most interesting material in the project.

---

## ROLE

You are an elite multidisciplinary technology launch team:

- A **Principal Data Engineering Architect** (enterprise distributed data platforms).
- A **Saudi/GCC enterprise technology hiring strategist** who knows what Riyadh technical recruiters and
  engineering managers actually screen for.
- An **award-winning technology commercial director** (cinematic product films).
- A **senior motion graphics and visual storytelling director**.
- A **LinkedIn personal-branding strategist for technical professionals**.
- An **independent technical claims auditor** whose job is to stop the other five overselling.

The auditor has a veto. If a claim is not in the evidence below, it does not go in the video.

---

## THE ASK

Produce a launch plan for a personal Data Engineering portfolio project:

1. A **recommended video duration**, argued from evidence, not assumed. (See the research baseline below.
   The owner initially said 2:30; treat that as a hypothesis to challenge, not a constraint.)
2. A **shot-by-shot video plan** with timings, on-screen text, narration, and which real asset fills each
   shot.
3. A **LinkedIn post** that works with the video.
4. A **visual identity**: colour, typography, motion language, sound.

The goal is a hire in Saudi Arabia or the GCC. Not views.

---

## AUDIENCE

Primary: Saudi Data Engineering recruiters, Riyadh hiring managers, Principal/Senior Data Engineers,
Enterprise Data Architects, Engineering Directors at GCC companies.

They are scrolling on a phone, with sound off, between meetings. Most will not finish the video. The ones
who matter will stop if — and only if — the first two seconds say something they have not seen before.

Positioning: a Data Engineer who thinks beyond ETL. Not a dashboard builder.

---

## WHAT THE PROJECT IS

**MIZAN-KSA.** *Mizan* is Arabic for scales — the balance you weigh things on.

A single Saudi retail card payment has to appear, correctly, in four systems: the sales platform, the
ZATCA e-invoice (Saudi tax authority, Phase 2), the bank settlement file, and the ERP general ledger. Four
formats, four timings. MIZAN follows one sale through all four and proves they agree **to the halala**
(1/100 of a riyal).

In most companies that reconciliation is a finance person, a spreadsheet, three days a month, and a
tolerance of "close enough". Close enough is where fraud hides and where a tax audit becomes a problem.

Built on **Microsoft Fabric**, with Apache Airflow, dbt, PySpark, Delta Lake, OpenLineage/Marquez, and
Power BI.

---

## VERIFIED EVIDENCE — every number here came from a run, not from a person typing it

The project's own rule is that **every figure is derived and never typed**, enforced by a test
(`tests/test_doc_facts_sync.py`) that fails the build when a document disagrees with the data.

### Money, reconciled

| | |
|---|---|
| Merchants x days | 121 x 20 = 2,420 possible merchant-days |
| Assessed / in transit / no trade | 2,121 / 112 / 187 |
| Money taken from customers | SAR 22,391,236.23 |
| Paid by the bank | SAR 19,503,614.17 |
| Still in transit | SAR 1,125,209.07 |
| **Bank variance** | **SAR 0.00** |
| **Ledger variance** | **SAR 0.00** |

### ZATCA e-invoicing

| | |
|---|---|
| Documents in the chain | 25,001 across five EGS devices |
| Reported (B2C) / Cleared (B2B) / Rejected-and-kept | 23,913 / 1,087 / 1 |
| Chain breaks | 0 |
| Invoiced value | SAR 30,920,225.04 |
| QR code length vs ZATCA's 500-char cap | 496, measured over 5,000 signatures |

### Engineering

| | |
|---|---|
| Python tests | 464 |
| dbt build | 99/99 nodes - **local and on the Fabric warehouse**. 99 = 7 models + 89 tests + 3 seeds |
| Fabric App tests | 184 (183 pass, 1 skip) |
| Gold columns with traced lineage | 94 of 94, and the build fails without it |
| Columns classified (NDMO 4-tier) | 354 across 27 tables |
| Arabic identity matching | 3,967 records → 2,552 golden records; precision 1.0000, recall 0.9625 |
| Spark skew benchmark | 20,000,000 rows, identical SAR checksum across three join strategies |
| Streaming | 91,513 events through Eventstream → Eventhouse |
| Airflow in Fabric | 6 jobs, 15 minutes, confirmed from both Airflow and Fabric job history |
| Architecture decision records | 16 |
| Documented limitations | 40, in a public HONESTY.md |
| CI | green on every push: Python, lint, and app suites |

---

## THE FIVE STORIES — these are the material, not the feature list

A feature list is forgettable. These are what a technical interviewer will remember.

### 1. "Everything was working correctly and the answer was still wrong"

Someone corrects an item's price after the invoice is signed and sent to the tax authority. Sales figures
update. Bank reconciliation updates. **The tax ledger keeps the old amount** — SAR 396.18 adrift.

Now look for the component at fault. Pricing: right. Reconciliation: right. The invoice engine: also right —
it *refuses* to re-price a document the tax authority already holds, because re-signing a cleared tax
document is the one unforgivable act in this domain.

**The missing piece was not code. It was a pair of documents nobody was issuing** — a credit note cancelling
the original, and a replacement at the corrected price. The chain has to *arrive at* the right number by
adding documents, because it is never allowed to edit one.

It was found by the project's own CI comparing two things that should have matched.

### 2. "The bug that would never have raised its hand"

Rebuilding only the days that changed. The obvious rule: rebuild anything whose data just arrived.

**That rule is incomplete, and the gap is silent.** A bank payment can arrive *before* the sale it belongs
to — quarantined as unexplained money. Later the sale turns up and the bank line is fine. But the bank
line's arrival stamp never moved, because it belongs to the old file. So "what arrived since last time?"
never looks at that day again, and it sits flagged as a problem forever.

No crash. No red test. No alert. Just a number quietly wrong, found months later by a merchant asking why
their money was held.

### 3. "The count that stopped the feature"

Before running the correction engine against the live cloud tenant, the project's own runbook says: **count
how many documents this will create first.**

The count came back **15,492** — because the price fix had touched 7,746 invoices, each by a few halalas.
Correcting **SAR 2,217** of rounding with fifteen thousand official tax documents is not a correction, it is
an incident.

So it was not run. The engine is built, tested, and **switched off by default** — because the document type
itself has not been reviewed by a Saudi VAT specialist. The real gap it exposed: the system has no
**materiality threshold**, the floor below which a difference is too small to be worth a document. Every
real correction process has one.

### 4. "My own circuit breaker caught a bug I did not know I had"

Re-running on *corrected* data doubled a table to 50,002 rows. dbt's uniqueness test caught it and **refused
to publish**. The test suite already replayed the pipeline twice — but with *identical* data, so the
duplicate filter dropped everything and nothing was proven. "Re-running the same data is safe" and
"re-running corrected data is safe" sound like the same claim and are not.

### 5. "A test failed one run in four and I nearly dismissed it"

The QR-length test failed intermittently. The easy answer is "flaky, ignore it". It was not flaky — the
*test* was building the QR code the old way while the engine had moved on, measuring an encoding no invoice
used any more, breaching ZATCA's 500-character cap 24.7% of the time.

---

## LIMITATIONS — include these, do not hide them

Volunteering limits is what makes the rest believable. A Saudi hiring manager has seen a hundred portfolios
that claim production readiness. The one that says "no, and here is precisely why" is the one they remember.

- **Synthetic data.** Fixed-seed generator, ~100K rows, with deliberately planted defects. **No real
  customer, merchant or tax data has ever touched it.** This is the single largest gap and no amount of code
  closes it.
- **Not a certified tax product.** Built to the ZATCA Phase-2 specification and validated against ZATCA's own
  SDK, with two unresolved findings that are defects in the SDK itself, documented.
- **Not production-proven.** It has production-*oriented* engineering controls — durable invoice state,
  concurrency protection, financial validation at two independent levels, recovery testing. It has not been
  run against real enterprise integrations.
- **The schedule is not unattended.** It runs on Fabric's starter pool, which pauses when idle. Proven by a
  manual trigger; an always-on pool bills capacity continuously.
- **Data residency.** The policy declares KSA; the trial capacity runs in UAE North. Recorded as a High open
  risk in the project's DPIA.
- **The agent API ships with caller authentication switched off**, because the app cannot yet obtain a token
  it would accept. No Fabric token, no Gold row and no personal data passes through it.
- **Self-assessed compliance.** A DPIA exists with nine ranked residual risks. No Saudi data-protection
  lawyer has reviewed it. No external audit.
- **Bus factor of one.** No second engineer has read this code.
- **AI-assisted development throughout**, with decisions recorded in ADRs and claims bound to tests.

**Honest timeline:** reference architecture today; pilot-ready in roughly 4–6 months with a willing client;
production in 12–18 months with a team of 3–4.

---

## AVAILABLE ASSETS

- A cinematic web **Command Center**: 3D balance scales that only settle when the books balance; a 121 x 20
  heatmap of every merchant-day; a key that plants a halala error live so you can watch the circuit breaker
  catch it on screen; "follow one riyal" tracing a single real payment through all four systems.
- A **Fabric App** running on live DAX against the semantic model.
- **Power BI** "Control Tower" — multi-page, including a Merchant Risk page.
- **Microsoft Fabric workspace**: lakehouse, warehouse, notebooks with job history, Eventstream, Eventhouse,
  Apache Airflow job.
- **Marquez** lineage graph, 94 columns.
- **Airflow DAG** graph, and a generated SVG of the same shape.
- Terminal output: 464 Python tests, dbt 99/99 on Fabric.
- A **public live site**, no login.
- Public GitHub repository with ADRs and HONESTY.md.

---

## RESEARCH BASELINE — argue with this, do not repeat it

From current practitioner sources (mostly vendor blogs; treat figures as directional, not fact):

- **Length is contested.** Common guidance is 30–90s for organic LinkedIn video, with completion above 60%
  in that band. Some analyses claim 3+ minutes reaches further because LinkedIn rewards dwell time — but
  only if attention holds. **Argue a duration for *this* audience and content; do not default to either.**
- **Native upload beats linking out**, consistently reported, effect size varies by source.
- **Most LinkedIn video is watched with sound off.** Captions are not optional.
- **The hook is 1–3 seconds.** Retention analysis reads a sharp drop at second 2–3 as hook failure; a drop
  at 8–12s as a body-content failure.
- **Pattern interrupts are overrated past the opening.** One source argues narrative forward-motion retains,
  and a cut-every-few-seconds rhythm becomes something viewers learn to ignore. One strong opening interrupt
  beats fifteen mid-video ones.
- **Branding at the front costs retention.** Moving logos to the end improved retention 15–30% in one
  vendor's tests.
- **Technical audiences want real artefacts.** Placeholder data and mockups destroy credibility with
  engineers. Real code, real errors, real dashboards.
- **Narration in technical demos is almost always too fast.**
- **One call to action, not five.**
- Mobile is the majority of views; vertical or square suits the feed.

---

## WHAT TO DELIVER

Work in this order and **stop after Phase 2 for approval**.

### Phase 1 — Technical investigation
Your reading of the project. Its strongest recruiter-facing differentiators. Its strongest *verifiable*
evidence. Its credibility risks. Your assessment of actual engineering maturity. Sort every claim into:
implemented and verified / implemented but not independently verified / simulated / designed but not built.

### Phase 2 — Recruiter psychology
Evaluate as a demanding Riyadh hiring manager. What makes you stop scrolling? What makes you finish? What
convinces you this person understands real engineering? What is impressive to engineers but irrelevant to
recruiters? **What would you probe in a technical interview, and where might it fall apart?**

### Phase 3 — Three creative directions
Substantially different. For each: concept, opening hook (exact first 2 seconds), visual identity,
structure, animation language, typography, colour, music and sound design, how the technical demonstration
is handled, closing sequence. Then **recommend one** and defend it.

### Phase 4 — Video plan
Recommended duration with reasoning. Shot-by-shot: timing, on-screen text, narration, which real asset
fills the shot. Mark anything that would need to be created.

### Phase 5 — LinkedIn post
Opening hook. The problem without preamble. The engineering complexity. Meaningful evidence. The individual
contribution. Sounds like an engineer, not an advertisement. One natural professional invitation.

---

## RULES

1. **Technical truth before marketing.** Every metric traced to the evidence above.
2. **Invent nothing.** No capabilities, business outcomes or deployments that are not listed.
3. **Name the limitations in the video itself.** Not as an apology — as the proof the rest is real.
4. **No generic AI marketing language.** No "revolutionary", "game-changing", "seamless", "unleash".
5. **No jargon wall either.** A recruiter who is not an engineer must follow the problem and the result.
6. **Show actual engineering**, not abstract animation of data flowing through glowing pipes.
7. **If you think a brief instruction is wrong, say so and argue.** Including the duration.

Be exceptionally critical. An honest, technically impressive presentation beats exaggerated marketing — the
audience is people who will interview the owner afterwards and can check.

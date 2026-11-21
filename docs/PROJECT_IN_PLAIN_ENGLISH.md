# MIZAN-KSA in plain English

Read this before recording anything. It explains every part of the project the way you would explain it to a
hiring manager who knows retail and finance but not Fabric, and it gives you the exact numbers so you never
have to guess on camera.

**"Mizan" means scales** — the balance you weigh things on. That is the whole idea: money in equals money
out, to the last halala (1/100 of a riyal), and the scales only settle when it does.

---

## The one-sentence version

> A Saudi retail chain takes a card payment. That single sale has to appear, correctly, in four different
> places — the sales system, the ZATCA e-invoice, the bank settlement file, and the accounting ledger. MIZAN
> follows it through all four and proves they agree.

If you say nothing else, say that.

---

## The problem a real Saudi business has

Picture a chain of 121 stores across Riyadh, Jeddah and Dammam. Every day:

- Customers pay by **mada**, Visa, Apple Pay, BNPL (Tamara, Tabby)
- Every sale must produce a **ZATCA-compliant e-invoice**, signed and reported to the tax authority
- Two days later the **bank** sends a settlement file saying what it actually paid, minus fees
- The **ERP** (SAP) posts journal entries to the general ledger

Four systems. Four different formats. Four different timings.

**The question nobody can answer quickly: do they agree?**

In most companies, the answer is a finance person with a spreadsheet, three days a month, and a tolerance of
"close enough". And "close enough" is where fraud hides, where VAT gets misdeclared, and where a ZATCA audit
becomes a problem.

MIZAN answers that question automatically, every night, to the halala.

---

## The pieces, one at a time

Each section is: **what it is → the real problem → what I built → what it proves → the number**.

---

### 1. The data generator

**What it is.** A program that invents a realistic Saudi retail business: 121 merchants, 20 days of trading,
customers, orders, payments, bank files, invoices and ledger entries.

**The real problem.** I could not use a real company's payment data — it is confidential, and it would breach
PDPL to put it in a portfolio. But fake data that is too clean proves nothing: if every bank file arrives on
time and every amount matches, a reconciliation engine has nothing to catch.

**What I built.** A generator that produces *realistically broken* data, deliberately:

- A bank file that arrives late, so some days have no settlement yet
- An Arabic text file saved in the old Windows CP1256 encoding, which corrupts some names
- The same customer spelled five different ways in Arabic
- A duplicate bank file sent twice
- One invoice that ZATCA rejects

**What it proves.** Every defect the system catches is a defect somebody deliberately planted, so "it found
nothing" is never an acceptable result.

**Honest limit, say it out loud:** the data is synthetic. The engineering is real; the business is invented.

**The number:** a fixed seed, so running the generator twice produces byte-identical files. That is how you
know a difference in the output came from a code change and not from randomness.

---

### 2. Bronze, Silver, Gold (the "medallion" layers)

**What it is.** Three stages the data passes through.

**Real-world analogy.** A restaurant kitchen:
- **Bronze** = the delivery at the back door. Nothing is thrown away, nothing is trimmed. Exactly as it
  arrived, including the bruised vegetables.
- **Silver** = prepped ingredients. Cleaned, chopped, labelled, checked.
- **Gold** = the plated dish that goes to the customer.

**The real problem.** Most teams clean data on the way in and throw the original away. Then an auditor asks
*"what did the bank actually send you on 3 March?"* and nobody can say, because the only copy was the cleaned
one.

**What I built.** Bronze is **append-only** — it never updates and never deletes. If a bank re-sends a file,
both versions are kept and the system knows which is newer. Silver takes the latest and cleans it. Gold is
what finance reads.

**What it proves.** You can always go back to exactly what arrived. That is what makes an audit survivable.

**The number:** when a corrected file re-landed, Bronze held **50,000 rows for 25,000 invoices** — two
versions of each — and Silver still produced exactly **25,001 documents**, not 50,002. (More on that in
"what went wrong" below; that one took a bug to prove.)

---

### 3. ZATCA e-invoicing (the hardest part)

**What it is.** Saudi Arabia's tax authority requires every invoice to be electronically signed and either
*reported* to them (for consumer sales) or *cleared* by them before issue (for business sales). This is
Phase 2, "Fatoora".

**The real problem.** Three things make it genuinely hard:

1. **The invoices form a chain.** Each invoice carries a hash of the previous one, like links. If one link is
   wrong, every invoice after it is suspect. There is no "fix it later" — a correction is a *new* document.
2. **You cannot un-send one.** Once an invoice is signed and sent, it is in the chain forever. Even a rejected
   one stays.
3. **The network is unreliable.** If the connection drops after you send but before you get an answer, you do
   not know whether ZATCA received it. Send it again and you might double-report. Do not send it and you might
   be missing an invoice.

**What I built.**

- The chain, with the exact genesis value ZATCA specifies for the very first invoice
- A state machine where **only five HTTP responses are treated as final** (200, 202, 400, 401, 403). Anything
  else — a timeout, a 503, a dropped connection — becomes `UNKNOWN_OUTCOME` and is retried with the
  *identical* signed bytes and the *identical* UUID, so a duplicate is recognisably the same document.
- The system writes "I am about to submit" to the database **before** making the call. If the worker dies
  mid-flight, the restart finds that record and knows the outcome is unknown rather than assuming failure.
- The QR code every Saudi invoice must carry, which has a hard **500-character limit**.

**What it proves.** This is the part that separates a demo from a system. Anybody can send an invoice. Knowing
what to do when you do not know whether it arrived is the actual job.

**The numbers:**
- **25,001 documents**, zero chain breaks
- **23,913 REPORTED** (consumer sales), **1,087 CLEARED** (business sales), **1 CONFIRMED_REJECTION** kept in
  the chain, because deleting it would break every invoice after it
- **SAR 30,920,225.04** of invoiced value
- QR codes land at **496 characters** against the 500 limit — four to spare, measured over 5,000 signatures

**Two defects found on 2026-11-21, both worth telling:**

**"Clearance is switched off" was an infinite loop.** ZATCA can turn clearance off for the whole country at
once; it then answers `303` and you must send the same document to the *reporting* endpoint instead. We
treated 303 as "unknown", whose correct response is to retry — to the endpoint that is still switched off,
which answers 303 again. Forever. It would have hit every business invoice in the country simultaneously.
A reviewer raised it; I checked ZATCA's own technical guideline before changing anything, because the
five-final-responses rule is frozen. It turned out not to be a change to that rule at all: a 303 says
*where to send the document*, not *what happened to it*. Same UUID, same signed bytes, different endpoint.

**A corrected price never reached the tax ledger.** If someone fixed an item's price after the invoice was
signed, the sales figures moved, the bank reconciliation moved, and the tax chain kept the old amount —
SAR 396.18 adrift. The interesting part is that **nothing was misbehaving**: the engine refuses to re-price
a signed invoice, which is exactly right, because re-signing a document the tax authority already holds is
the one unforgivable act in this whole domain. The missing piece was never a fix to the engine. It was a
pair of documents nobody was issuing: a credit note cancelling the original, and a replacement invoice at
the corrected price. The chain now *arrives at* the right number by adding documents, never by editing one.

That is the shape of the expensive bugs. Every component doing its job, and the system still wrong.

**For Saudi employers:** this is the single most relevant thing in the project. Every company in the Kingdom
has had to do ZATCA Phase 2. Most did it badly, and most cannot explain what happens on a timeout.

---

### 4. Reconciliation — the halala test

**What it is.** Proving the money agrees across all four systems.

**The real problem.** Three sources of truth, all slightly different:

- The till says the customer paid **SAR 100.00**
- The bank deposits **SAR 98.50** (it kept SAR 1.30 in fees plus SAR 0.20 VAT on the fee)
- The ledger has to show all three figures, separately

And the bank's file arrives **days later**. So on any given day, some money is genuinely *in transit* — not
missing, just not arrived.

**What I built.**

- A **key spine**: a list of every merchant-and-day from *all three* sources combined. Most people write a
  LEFT JOIN from payments to bank, which silently drops any bank line that has no matching payment — exactly
  the line you most need to see.
- An explicit **IN_TRANSIT** state for days whose bank file has not arrived, so they are never shown as
  "balanced" and never shown as "broken". They are shown as pending.
- Fees are taken **from the bank's file**, never recalculated. If you recompute the fee you will be right 99%
  of the time and the 1% will be a real discrepancy you have just hidden.
- All money is handled as exact decimals, never floating-point. `0.1 + 0.2` in floating point is
  `0.30000000000000004`, and across 20 million rows that becomes real riyals.

**What it proves.** Both variances are **0.00** — not "small", not "within tolerance". Zero.

**The numbers:**
- **121 merchants x 20 days = 2,420 possible merchant-days**
- **2,233** had trading activity: **2,121 assessed** and **112 still in transit**
- **187** had no trading at all
- **SAR 22,391,236.23** taken from customers
- **SAR 19,503,614.17** paid by the bank
- **SAR 1,125,209.07** in transit
- **Bank variance SAR 0.00, ledger variance SAR 0.00**

**The honest bit:** I was told, correctly, that if my generator and my reconciler share the same rules then
zero is guaranteed by construction and proves nothing. So I wrote a test that **damages the data in 50
different ways** and checks the reconciler notices all 50. It does. And it found one blind spot I then wrote
down: two offsetting errors on the same merchant-day cancel out inside the daily sum. No sum over a day can see
that, so on 2026-11-21 the build gained a second, line-by-line check that compares each single payment to the
single bank line that settled it -- where nothing is added up and the two errors cannot hide behind each other.
The daily figure still nets to zero, because arithmetic; the line check catches it. The old limitation, kept
here because it is the honest history: the model works at
merchant-day level, not line level. That limitation is in `HONESTY.md`.

---

### 5. Only rebuilding the days that changed

**What it is.** Not re-doing all the work every night.

**The real problem.** Until 2026-11-20 the system added up *every* sale ever made, every night, just to tell
you today's figures. That is an accountant re-counting the whole year's receipts each evening. Correct, and
unusable once the pile gets big. Fine at 25,000 invoices; hopeless at 25 million.

**Why the obvious fix is wrong here.** Everyone's first answer is "only rebuild the last few days". In card
payments that is a quiet disaster, because late data is the normal case, not the exception:

- A sale on **Tuesday**; the bank's settlement file for it lands **Wednesday or Thursday**.
- A customer disputes a charge — the chargeback can arrive **45 days** after the sale it claws back.
- A bank re-sends a file weeks later because the first one was wrong.

A "last 7 days" window would silently stop reconciling exactly the cases this system exists to catch. Not
crash — *silently*. The numbers would keep looking fine.

**What I built instead.** Every row records **when it arrived**, not just what day it is about. Each night
the question is: what landed since last time, and which business days do those rows belong to? Rebuild those
days. However late a row is, its day gets rebuilt. There is no window to fall off the end of.

And a day is rebuilt **whole** — deleted and re-derived — never added to. A reconciliation is a sum across
three sides: what the shop sold, what the bank paid, what the ledger booked. Half a sum is not a smaller
sum, it is a wrong one.

Three of the seven Gold tables work this way. The other four cannot, and each one's file now says why in its
first paragraph — for example, the customer table shows only *current* records, so when a record stops being
current the right answer is that it **disappears**, and an incremental build can update rows it is handed
but cannot delete rows it is not. Left alone, retired records would pile up looking current forever.

**The bug that nearly shipped with it.** This is the part worth telling.

A bank payment can arrive **before** the sale it belongs to. With no sale to match, it is quarantined as
unexplained money. Later the sale turns up and the same bank line is perfectly fine.

But **the bank line's arrival stamp never moved** — it is still the old file's. So "what arrived since last
time?" would never point at that day again, and it would sit there flagged as a problem forever, with
nothing raising a hand. Not a crash. Not a failing test. Just a number quietly wrong.

The fix is a fourth rule: *any settlement day whose missing payment just arrived also counts as changed.*
There is a test that delivers data in the wrong order on purpose to prove it.

**How it is tested.** Every test builds the tables **twice** — once incrementally, once from scratch — and
demands the two match exactly. The first run of an incremental model is just a full build, so a test that
runs it once proves nothing at all. Two of my own test fixtures were caught being wrong *by the project's
own circuit breaker* while I was writing them: I had forgotten a ledger line both times.

**What it proves.** On the real data: a full rebuild passes **98 of 98** checks, a second incremental run
passes **98 of 98** in 2.2 seconds, and all **10 Gold tables come back byte-identical**. Every money figure
is unchanged.

**The honest bit:** I am claiming **no speed-up**. The whole of Gold already rebuilt in 18.2 seconds at this
data volume, so there is nothing to boast about. This is the design that survives growth, not a benchmark —
and it has not yet run on Fabric, only locally. If anyone asks "how much faster?", the answer is "I do not
know, because I have not run it at a size where it matters."

---

### 6. Matching Arabic customer names (MDM)

**What it is.** Working out that five records are the same person.

**The real problem.** Arabic names are written many ways. The same man might appear as:

- with and without "al-" on the family name
- with the honorific "Abu ..." or without
- with Arabic-Indic digits in his ID instead of Western ones
- with different spacing or a different form of the same letter
- and once, mangled, because a file was saved in **CP1256** instead of UTF-8

Meanwhile two *different* brothers may share a surname, a city and a similar first name — and merging them is
much worse than failing to merge, because you would then show one brother the other's purchases.

**What I built.** A ladder of rules: exact ID match first, then normalised name plus phone, then fuzzy
similarity — with a deliberate bias toward *not* merging when unsure. Unresolvable records go to a
**quarantine** table with the reason, rather than being guessed at.

**What it proves.** I scored it against the generator's own answer key:

- **Precision 1.0000** — it never merged two people who were not the same person. Zero false merges.
- **Recall 0.9625** — it found 96.25% of the real matches, missing 56 out of 1,492
- **F1 0.9809**

**Say it this way:** *"It never makes the dangerous mistake. It occasionally makes the safe one."* That is a
deliberate trade and you should present it as one.

**The numbers:** 3,967 records became **2,552 golden records**, the largest merging 5 spellings into one
person. **15 rows** were quarantined as genuinely unrecoverable CP1256 corruption, with the reason recorded.

---

### 7. Privacy — PDPL and the right to be forgotten

**What it is.** Saudi Arabia's Personal Data Protection Law. Among other things, a person can demand that you
erase their data.

**The real problem — and this is a genuinely interesting conflict.** PDPL says *erase the customer's data*.
Saudi tax law says *keep invoices for years*. Those two rules point in opposite directions on the same row.

**What I built.**

- Personal data is **encrypted at the moment it lands in Bronze** — not later, not in a separate cleanup job.
  Each customer gets their own encryption key.
- An erasure request **destroys that customer's key**. The encrypted data remains, but it is now permanently
  unreadable. This is called crypto-shredding.
- The **tax documents stay**, because the law requires them — but with no way to link them back to a person.
- A **tombstone** record proves the erasure happened and when.
- Then — and this is the part people forget — **`VACUUM` with zero-hour retention**, because Delta tables keep
  old versions for "time travel". Without that step you can restore the deleted key from yesterday's snapshot
  and the erasure was theatre.
- A **Restore Guard** that tests exactly that: it tries to bring the key back from a backup, and must fail.

**What it proves.** Erasure that survives a restore. Most "right to be forgotten" implementations do not.

**The numbers:** one erasure removed **5 linked records** and **5 keys**, kept **25,001 tax documents** worth
**SAR 30,920,225.04**, and the guard confirmed the key could not be resurrected. `VACUUM RETAIN 0 HOURS`.

**For Saudi employers:** PDPL enforcement is live. An engineer who has already thought about the tax-versus-
erasure conflict is unusual.

---

### 8. Data classification (NDMO)

**What it is.** Saudi Arabia's National Data Management Office requires data to be classified —
PUBLIC, CONFIDENTIAL, SECRET, TOP SECRET — and handled accordingly.

**The real problem.** Classification is usually a spreadsheet somebody wrote once and nobody updated. It
drifts from reality within a month and nothing enforces it.

**What I built.** Classification derived from **versioned rules in code**, applied to every column
automatically, plus a **gate that fails the build** if a SECRET column ends up somewhere it should not be.

**What it proves.** The classification cannot drift from the data, because it is recomputed from the data.

**The numbers:** **354 columns** across **27 tables** — 1 PUBLIC, 17 CONFIDENTIAL, 6 SECRET, 3 TOP SECRET.

**Honest limit:** these are my rules, chosen for this dataset, not a regulator-issued catalogue. That is
stated in `HONESTY.md`.

---

### 9. The circuit breaker (dbt)

**What it is.** dbt builds the Gold tables and runs **98 tests** every time. If a test fails, the build stops
and Gold is not published.

**Real-world analogy.** The electrical trip switch in your house. It does not repair the fault — it stops the
fault from burning the house down, and it makes the fault obvious.

**The real problem.** Bad data in a dashboard is worse than no dashboard. If the CFO reads a wrong number on
Monday and acts on it, the damage is done before anyone notices.

**What I built.** Tests that assert things like: every invoice ID is unique; every payment type is one of the
three allowed values; every money column is `DECIMAL(18,2)` and never a float; every Gold column can be traced
back to a source column.

**What it proves — and this is the story worth telling.** On 19 November, a corrected price file caused the
ZATCA table to double to 50,002 rows. The uniqueness test failed, the build stopped, and **Gold was never
published**. I found out from a test, not from a dashboard being wrong.

**The number:** **98 tests, all passing** on the local engine. The Fabric warehouse last ran 91/91 on
2026-11-19 and has not been re-run since Gold became incremental, so it is not claimed as current.

---

### 10. Orchestration (Apache Airflow)

**What it is.** The scheduler. It decides what runs, in what order, and what to do when something fails.

**Real-world analogy.** A restaurant's head chef. The chef does not cook everything personally — they decide
what starts when, and they stop the dish going out if the sauce is wrong.

**The real problem.** Running six jobs by hand is fine until you are on holiday. And the order matters: Silver
cannot run before Bronze, and Gold cannot be built before the catalogue it reads is refreshed.

**What I built.** A pipeline that runs inside **Microsoft Fabric itself** — not on my laptop:

```
bronze_land -> silver_build -> mdm_resolve -> zatca_chain -> ai_index     -> dbt_build_gold
                                                          -> ndmo_catalog -^
```

The last two run **in parallel** because neither needs the other, then both must finish before Gold is built.

**What it proves.** The pipeline does not need me. That is the difference between a project and a system.

**The numbers:** six jobs, **15 minutes**, confirmed from both sides — Airflow's task list and Fabric's own
job history.

**Honest limit, and say it:** it runs on Fabric's *starter pool*, which sleeps when idle, so the 3am schedule
is written and proven by a manual run but is not yet dependable unattended. Making it dependable costs
capacity that a trial does not justify.

---

### 11. Lineage (OpenLineage and Marquez)

**What it is.** A record of where every number came from, column by column.

**Real-world analogy.** The ingredient list on food packaging — but traced right back to the farm.

**The real problem.** An auditor points at a VAT figure and asks where it came from. Without lineage, the
answer is an engineer reading SQL for an afternoon.

**What I built.** The build works out the ancestry of **every Gold column** from the SQL itself, and **fails if
any column cannot be traced**. Each run also records the code version and the exact data snapshot it used.

**What it proves.** Not "we have lineage" but "the build will not go green without it".

**The number:** **94 of 94 Gold columns traced**.

**Honest limit:** Marquez, the viewer that draws the graph, runs locally in Docker. Fabric's Airflow cannot
reach it, because Fabric does not support private networking for Airflow jobs. The *lineage* is computed and
gated regardless; Marquez only draws it.

---

### 12. Handling a huge, lopsided dataset (Spark skew)

**What it is.** Making 20 million rows process efficiently when one merchant has most of them.

**Real-world analogy.** Twelve supermarket checkouts open, and one of them has a customer with 400 items while
the others have three each. Eleven staff stand idle. The shop is not slow because it lacks staff — it is slow
because the work is distributed badly.

**The real problem.** In this dataset one mega-merchant holds **73.8% of the money**. A naive join sends all of
that to a single worker, which then runs for ten times as long as everything else.

**What I built.** Two fixes, compared honestly: Spark's built-in adaptive skew handling, and a manual
"salting" technique that splits the big merchant across 16 buckets. Same data, same total, measured.

**What it proves.** I can diagnose *why* something is slow, not just that it is. And the salted and unsalted
results produce an identical checksum, so the optimisation did not change the answer.

**The number:** **20,000,000 rows**, with identical row counts and SAR totals across all three runs.

**Honest limit:** the skew ratios are not directly comparable between runs because the task counts differ. The
durations and the checksum are. That caveat is on the page.

---

### 13. Real-time fraud detection (Eventstream)

**What it is.** Watching events as they happen rather than waiting for tonight's batch.

**Real-world analogy.** A security guard watching the camera feed, not reviewing the tape next week.

**The real problem.** Card testing — a fraudster trying stolen card numbers in rapid succession — is obvious
within seconds and invisible in a daily summary.

**What I built.** A live stream of checkout, payment and invoice events into Fabric, with rules that fire on
velocity patterns.

**The number:** **91,513 events** streamed — 50,002 invoice events, 23,511 checkout, 18,000 payment — with the
rules producing the same answers in Fabric as in the local reference.

---

### 14. The Command Center

**What it is.** A web page that shows all of the above, running as an app inside Fabric.

**The real problem.** Everything above is invisible. A hiring manager will not read your SQL.

**What I built.** A single page where a 3D balance scale **only settles when the books balance**, a heatmap
shows every merchant-day, and pressing one key plants a halala error so you can watch the circuit breaker
catch it on screen.

**What it proves.** That you can explain your own system to a non-engineer. Which, in an interview, is being
tested whether anyone says so or not.

**Important:** every figure on that page is exported from the real Gold tables. Nothing is typed in.

---

### 15. Testing and the honesty ledger

**What it is.** **411 automated tests** on the data side and **184** on the app side (174 passing; 10 skip
themselves until the Fabric pipeline is re-run), running on every push.

**And `HONESTY.md`** — a document listing everything this project does *not* do, everything that is
approximate, and everything that broke.

**Why that document exists.** Portfolio projects overclaim. A reviewer's instinct is to go looking for what
you are hiding. If you hand them the list yourself, they stop looking and start trusting.

**It currently has 36 numbered entries**, including three found in the last two days. That is not weakness —
every entry is something I measured rather than assumed.

---

## The five stories worth telling

These are better than any feature. Lead with them.

### "My own circuit breaker caught a bug I did not know I had"

Re-running the pipeline on **corrected** data doubled a table to 50,002 rows. dbt's uniqueness test caught it
and refused to publish Gold.

**The interesting half:** my test suite already replayed the pipeline twice — but with *identical* data, so
the duplicate filter dropped everything and nothing was proven. I had proven "re-running the same data is
safe". I had never proven "re-running *corrected* data is safe". Those sound like the same claim and are not.

### "A test failed one run in four and I nearly dismissed it"

The QR-code limit test failed intermittently. The easy answer is "flaky, ignore it".

It was not flaky. The *test* was building the QR code the old way, while the engine had moved on — so it was
measuring an encoding no invoice used any more, which breached the 500-character limit 24.7% of the time. One
rule written down twice, and the copies drifted. Now both go through one function.

### "Everything was working correctly and the answer was still wrong"

Someone corrects an item's price after the invoice has already been signed and sent to the tax authority.
The sales figures update. The bank reconciliation updates. The tax ledger keeps the old amount.

Now look for the component at fault. The pricing is right. The reconciliation is right. And the invoice
engine is right too — it **refuses** to re-price a document the tax authority already holds, because
re-signing a cleared tax document is the one unforgivable act in this domain. Every part is behaving
exactly as designed.

**The missing piece was not code at all. It was a pair of documents nobody was issuing** — a credit note
cancelling the original, and a replacement at the corrected price. The chain has to *arrive at* the right
number by adding documents, because it is never allowed to edit one.

**The interesting half:** this is the condition the entire project exists to detect — a tax ledger
disagreeing with the books — happening inside the project itself, worth SAR 396.18. And it was found by my
own CI comparing two things that should have matched, not by anyone reading the code. If you are ever asked
for an example of a bug that no amount of code review would have caught, this is it.

### "The bug that would never have raised its hand"

I made the pipeline rebuild only the days that changed. The obvious rule is: rebuild anything whose data
just arrived.

**That rule is incomplete, and the gap is silent.** A bank payment can arrive *before* the sale it belongs
to — with no sale to match, it is quarantined as unexplained money. Later the sale turns up and the same
bank line is perfectly fine. But the bank line's arrival stamp never moved, because it belongs to the old
file. So "what arrived since last time?" would never look at that day again, and it would sit there flagged
as a problem forever.

**The interesting half:** nothing would have failed. No crash, no red test, no alert. Just a number quietly
wrong, found months later by a merchant asking why their money was being held. The only way to catch it was
to write a test that delivers data in the *wrong order* on purpose — which is not something you do unless
you have already decided that "it passed" and "it is correct" are different claims.

### "The first Fabric run failed in four seconds and that was the useful part"

Bad client secret. The log named the step, the app registration and the exact cause, and it was one read and
one fix.

**Say this:** *"I wrote the failure path so that it tells you what broke, not that something broke. That is
why it took four seconds to diagnose instead of an afternoon."*

---

## What NOT to claim

Protect your credibility. Volunteering limits is what makes the rest believable.

| Do not say | Say instead |
|---|---|
| "Production system" | "Engineering reference architecture, not a certified product" |
| "Real Saudi transaction data" | "Synthetic data with deliberately planted defects" |
| "Runs automatically every night" | "Deployed and proven by a manual run; the starter pool sleeps, so unattended scheduling needs an always-on pool" |
| "ZATCA certified" | "Built to the Phase 2 specification and validated against ZATCA's own SDK, with two findings I could not resolve, documented" |
| "Full data lineage in Fabric" | "Column lineage computed and gated in the build; Marquez is a local viewer" |
| Nothing about Arabic review | "The Arabic has not been reviewed by a native speaker of Saudi financial Arabic" |
| "It scales to millions of rows" | "Gold rebuilds incrementally so it *can* grow; I have not run it at a volume where that matters, so I am not claiming a speed-up" |

---

## The numbers, on one card

Keep this open while filming.

| | |
|---|---|
| Merchants x days | 121 x 20 = 2,420 possible merchant-days |
| Assessed / in transit / no trade | 2,121 / 112 / 187 |
| Money taken | SAR 22,391,236.23 |
| Bank paid | SAR 19,503,614.17 |
| In transit | SAR 1,125,209.07 |
| **Bank and ledger variance** | **SAR 0.00 and SAR 0.00** |
| ZATCA documents | 25,001 (23,913 reported, 1,087 cleared, 1 rejected and kept) |
| Invoiced value | SAR 30,920,225.04 |
| QR length vs the 500 limit | 496 |
| Golden customer records | 2,552 from 3,967 (precision 1.0000, recall 0.9625) |
| Columns classified | 354 across 27 tables |
| Gold columns traced | 94 of 94 |
| dbt tests | 98 passing locally; Fabric last ran 91/91 on 2026-11-19 and has not been re-run since |
| Stream events | 91,513 |
| Skew benchmark | 20,000,000 rows |
| Tests | 411 Python + 184 app (174 pass, 10 skip until Fabric is re-run) |
| Airflow in Fabric | 6 jobs, 15 minutes |
| Documented limitations | 36 |
| Gold tables rebuilt incrementally | 3 of 7; a re-run takes 2.2 s and changes nothing |

---

## "Is this production ready?" — the answer that wins

You will be asked this. The answer that gets you hired is **no**, said precisely. Most candidates can describe
what they built; very few can describe, accurately and unprompted, the distance between what they built and a
running system. That gap is the interview.

### Say this

> "No. The *data engineering* is production-grade — the ZATCA state machine, the reconciliation model and the
> erasure design would survive review. What is missing is everything around the code: real data, live ZATCA
> onboarding, security hardening on the agent API, and an operational layer. Pilot-ready in about five months
> with a willing client; production in about a year with a small team."

### What is already production-grade, and why

Four decisions here are the ones experienced reviewers single out, because they are the ones people get wrong:

- **The ZATCA timeout design.** Persisting SUBMITTING before the call, treating only five HTTP codes as final,
  retrying with identical bytes and identical UUID. Many live Saudi integrations catch the exception and retry
  with a fresh UUID — and double-report.
- **Crypto-shredding with VACUUM and a Restore Guard.** Most "right to be forgotten" implementations fail a
  restore test. This one actively tries to resurrect the key and demands failure.
- **The key spine instead of a LEFT JOIN.** A small decision that separates people who have been burned by
  reconciliation from people who have not.
- **Decimal money, append-only Bronze, lineage gating the build.** Correct, and none of them obvious.

### What is genuinely missing

**1. Real data has never touched it.** The generator invents the broken cases, so every edge case handled is
one already imagined. The 50-way damage test mitigates this; it does not remove it. Real data brings things
nobody designs for: a merchant changing VAT number mid-month, the bank adding a column, a refund arriving
before its sale, staff test transactions indistinguishable from real ones, a holiday shifting settlement by
four days instead of two. **This is the biggest gap, and it cannot be closed by writing code.**

**2. ZATCA sandbox is not ZATCA production.** Live onboarding is its own project: CSR generation, compliance
CSID, production CSID, per-device onboarding for each EGS unit, certificate renewal, and the real endpoint's
rate limits and failure behaviour. The two unresolved SDK findings stop being documentation and start being
blockers at that point.

**3. The operational layer exists now, except the part that is a person.** As of 2026-11-20 there are
alerts that name the step and link to a runbook, ten runbooks for the failures that actually happen, a
stated close deadline of 06:00 Riyadh that is measured, and a tested re-run procedure that fingerprints
Gold before and after. **What is still missing is a human:** nobody is on call, there is no paging rotation
or escalation, and no DR drill has been run against the Fabric tenant. The starter pool also sleeps, so it
cannot yet run unattended. Say it that way - "I built the operational tooling; I have not staffed it" is
accurate and sounds like somebody who knows the difference.

**4. Security needs switching on before any real tenant.** The Ask MIZAN Function *can* verify its caller
as of 2026-11-20 - a full Entra token check against the tenant's published keys, with sixteen tests attacking
it - and ships with the check disabled, because the app cannot yet obtain a token it would accept (ADR-013:
Fabric and the Function sit in different directories). Until it is switched on, an Origin header is the only
check, and an Origin header is set by browsers and forged trivially by anything else. Production also needs
managed identity everywhere, Key Vault with rotation, network isolation and an access audit log. **Be precise
about the blast radius, though** (HONESTY row 15): no Fabric token, no Gold row and no personal data passes
through that Function, and rate limits plus a USD 5 budget cap bound the loss to Azure credit. It is a gap to
close, not a data breach waiting to happen - and knowing the difference is itself the senior answer.

**5. Scale is a benchmark, not a load.** 121 merchants x 20 days, and one controlled 20-million-row join. A
real chain is 500+ merchants and years of accumulating history, with concurrent dashboard users. As of
2026-11-20 Gold *does* rebuild incrementally — only the days that changed, found by arrival time so late
data is never missed — which removes the structural reason it could not grow. **That is not the same as
having grown.** The incremental path has only ever run on 25,000 invoices, where the full rebuild already
took 18.2 seconds, so there is no measured saving to quote and I do not quote one.

**6. Compliance is self-asserted.** The NDMO classification uses rules I wrote. There is now a DPIA with
nine ranked residual risks, four of six subject rights implemented including access and erasure, and a
breach procedure - but **no review by a Saudi data protection lawyer and no external audit**. For a
regulated system a thorough self-assessment is still a self-assessment.

**7. Bus factor of one.** No second engineer has read this code. Regulated finance needs two or three people
who genuinely understand the system.

### Honest timeline

| Stage | What it means | From today |
|---|---|---|
| Reference architecture | The design is right | **Here now** |
| Pilot-ready | One real client runs it in parallel; nobody acts on the output | 4-6 months, one person full-time, plus a willing client |
| Production | Their month-end close runs on it and money decisions depend on it | 12-18 months, team of 3-4, including someone who has run operations |
| Product | Many clients, multi-tenant, supportable | 2+ years, and a company around it |

Most of the pilot gap is waiting on other people — ZATCA onboarding, a client's IT team, a lawyer. Very little
of it is coding.

### Why this section helps rather than hurts

Nobody interviewing you expects a portfolio project to be production-ready. Claiming it is would be the only
real mistake available here. Saying the above, unprompted and specifically, is what a senior engineer sounds
like.

---

## A LinkedIn post you could actually use

> I spent the last few weeks building MIZAN-KSA: a data platform that follows one Saudi retail sale from the
> till to the general ledger, and proves the money agrees to the last halala.
>
> A single card payment has to appear correctly in four places — the sales system, the ZATCA e-invoice, the
> bank settlement file, and the accounting ledger. Four formats, four timings. Most teams answer "do they
> agree?" with a spreadsheet and a tolerance.
>
> MIZAN answers it every night. Bank variance SAR 0.00. Ledger variance SAR 0.00. Across 2,121 assessed
> merchant-days, with 112 more correctly marked as still in transit rather than quietly treated as balanced.
>
> The parts I found hardest:
>
> - ZATCA Phase 2 is a chain. You cannot un-send an invoice, so a timeout is not a failure — it is an unknown
>   outcome, and the retry has to carry the identical signed bytes.
> - PDPL says erase the customer. Tax law says keep the invoice. Crypto-shredding resolves it, but only if you
>   also VACUUM the old versions — otherwise the key comes back from a restore and the erasure was theatre.
> - Arabic name matching has an asymmetric cost. Merging two brothers is far worse than missing a match, so I
>   tuned for zero false merges and accepted 96% recall.
>
> The thing I am most pleased with is not a feature. Re-running the pipeline on corrected data doubled a
> table. My own data tests caught it and refused to publish. The reason no test had caught it earlier: I had
> been re-running identical data, which proves a weaker claim than I thought it did.
>
> A later one I liked even more. I made Gold rebuild only the days that changed. A bank payment can arrive
> *before* the sale it belongs to; when the sale finally turns up, that payment stops being a problem — but
> its arrival timestamp never moved, so a naive "what's new?" rule would never revisit that day. Nothing
> would have failed. The number would just have been quietly wrong. Caught only by a test that delivers
> data out of order on purpose.
>
> Synthetic data, deliberately planted defects, and a HONESTY.md listing all 36 things it does not do.
>
> Built on Microsoft Fabric with Airflow, dbt, PySpark and OpenLineage.
>
> [repo link] [video link]

Cut it to half that if you want engagement. Keep the paragraph about the bug either way — it is the one thing
in there that nobody else's post will have.

---

## Where this came from

Every figure above is generated, not typed: `scripts/facts.py` derives them from the Gold tables, and
`tests/test_doc_facts_sync.py` fails the build if a document disagrees with them. If a number here looks
wrong, the test will have caught it before you did.

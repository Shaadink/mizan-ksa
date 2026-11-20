# MIZAN-KSA runbooks

What to do when the pipeline breaks. One section per failure that can actually happen, written to be read
at 03:00 by somebody who did not build the system.

**Every alert carries a link to a heading here.** `src/mizan/orchestration/oncall.py` maps each step to its
runbook, and `tests/test_oncall.py` fails the build if an alert ever points at a heading that does not exist
— because a dead link in an alert is worse than no link.

## Before anything

| | |
|---|---|
| **Close deadline** | 06:00 Asia/Riyadh, the morning after the business date |
| **Schedule** | 03:00 Asia/Riyadh, so there are three hours of slack |
| **Severity PAGE** | wake someone: the money path is blocked |
| **Severity TICKET** | next working day: serving is degraded, money is unaffected |
| **Golden rule** | **Never edit Gold by hand.** Fix the cause and re-run. Gold is rebuilt from Silver every time, so a manual edit is overwritten and the discrepancy comes back next run, untraceable. |

**Is it safe to just re-run?** Yes. Bronze is append-only with a duplicate ledger keyed on
`(event_key, payload_hash)`, so re-landing the same files changes nothing and re-landing corrected files lands
only the rows whose payload actually changed. This is tested
(`test_a_corrected_zatca_resend_does_not_double_the_silver_documents`) and was proven in anger on 2026-11-19.
**Re-running is the default remedy for almost everything below.**

---

## The bank file did not arrive

**Alert:** `bronze_land` or `freshness_gate`, severity PAGE.

**What it means.** A settlement file this run expected is not in the landing zone. The freshness gate stops
the run rather than publishing a Gold layer that silently shows a merchant as having taken no money.

**This is usually not a defect.** Banks miss their window. The pipeline is designed so a missing file is a
*state*, not an error: those merchant-days are reported as `IN_TRANSIT`, never as balanced.

**Do this:**

1. Check which batch is missing — the gate names it in the task log.
2. Look in the landing zone (`LH_MIZAN/Files/_staging/`). If the file is there but arrived after the gate
   ran, simply re-run the DAG; it will land.
3. If the file genuinely has not arrived, **do not force the run through**. Let the day stay `IN_TRANSIT`.
   The reconciliation is still correct — 112 merchant-days were in exactly this state in the reference run.
4. Tell finance which business dates are unassessed. They are visible in the Command Center as the
   "not assessed" chip, and in `fact_merchant_settlement_recon` where `status = 'IN_TRANSIT'`.
5. When the file arrives, re-run. The day moves from `IN_TRANSIT` to assessed on its own.

**Escalate** if the same date is still missing after two banking days: that is a bank-side incident, not a
pipeline one.

---

## The circuit breaker tripped

**Alert:** `dbt_build_gold`, severity PAGE.

**What it means.** dbt built the Gold models, ran its tests, one failed, and **the build refused to publish**.
Gold still holds the previous good version. This is the system working.

**Do this:**

1. Read the failing test name in the task log. The task deliberately prints the failure lines rather than the
   whole build, so the useful part is at the end.
2. Identify which class it is:

| Failing test | Meaning | Action |
|---|---|---|
| `source_unique_...` / `unique_...` | a key that should be unique is not — usually a fan-out in a join | **Do not re-run blindly.** Find the duplicate first: `SELECT <key>, COUNT(*) ... GROUP BY <key> HAVING COUNT(*) > 1` |
| `accepted_values_...` | a new enum value appeared in a source | A value nobody designed for. Decide: is it legitimate (add it, with a test) or junk (quarantine it)? Never add an `else` branch. |
| `no_float_columns` | a money column lost its `DECIMAL(18,2)` type | A model changed. Fix the cast; do not round. |
| `recon ... variance` | bank or GL variance is not 0.00 | Genuine money discrepancy. Go to **the money does not balance** below. |
| `gold_column_lineage` | a Gold column has no traceable source | A new column was added without lineage. Add the override or fix the model. |

3. Fix the cause, then re-run.

**Why you must not "just re-run" a uniqueness failure:** on 2026-11-19 this exact test caught a corrected
re-send doubling `slv.zatca_invoice_documents` to 50,002 rows. Re-running would have reproduced it. The fix
was a one-line change in `zatca_land.py`. A test that fails twice the same way is telling you something.

---

## The money does not balance

**Alert:** `dbt_build_gold` with a variance test, severity PAGE.

**What it means.** Captures minus fees no longer equals what the bank paid, or the ledger disagrees. The
reference state is **SAR 0.00 on both**, so any non-zero figure is real.

**Do this:**

1. Find the merchant-days. In the Command Center, the heatmap colours them; in SQL:
   ```sql
   SELECT merchant_id, settlement_for_date_ksa, bank_variance_sar, gl_variance_sar
   FROM gld.fact_merchant_settlement_recon
   WHERE bank_variance_sar <> 0 OR gl_variance_sar <> 0;
   ```
2. Open one. The Command Center drill panel shows every leg — captures, refunds, chargebacks, MDR fee, VAT on
   fee, bank paid, GL posted.
3. Common causes, in the order they actually occur:
   - **An orphan bank line.** The bank paid for something with no matching capture. The key spine makes this
     visible rather than dropping it — that is why it is a UNION and not a LEFT JOIN.
   - **A chargeback landing in a different period from its sale.** Known limitation; see `HONESTY.md`.
   - **A fee recomputed instead of read.** If anyone has "improved" the model by calculating MDR, revert it.
     Fees come from the bank's file at the bank's grain, always.
4. **Do not adjust Gold.** Fix the model or quarantine the source row, then re-run.

**One known blind spot, documented:** two offsetting errors on the same merchant-day cancel out and are
invisible, because the model reconciles at merchant-day grain. If you ever suspect this, line-level matching
is the fix, and it is not implemented.

---

## ZATCA documents are stuck in an unknown outcome

**Alert:** `zatca_chain`, severity PAGE.

**What it means.** The system sent an invoice to ZATCA and did not get a definitive answer — a timeout, a
5xx, or the worker died mid-flight. The document is persisted as `SUBMITTING` or `UNKNOWN_OUTCOME`.

**This is the most dangerous state in the system. Read before acting.**

**Do this:**

1. **Do not generate a new UUID. Do not re-sign.** The retry must carry the *identical* signed bytes and the
   *identical* `invoice_uuid`, so that if ZATCA did receive it, the duplicate is recognisable as the same
   document rather than a second invoice.
2. Re-run `zatca_chain`. The engine resumes from `ctl.invoice_outbox` and retries exactly those documents.
3. Check the chain is intact:
   ```sql
   SELECT COUNT(*) FROM quarantine.zatca_chain_violations;   -- must be 0
   ```
4. If ZATCA answers **400**, the document is a `CONFIRMED_REJECTION`. **Leave it in the chain.** Deleting it
   breaks the hash of every invoice after it. The remedy is a *new* document with a new ICV.
5. If ZATCA answers **401 or 403**, stop. That is `AUTH_HOLD` — a credential or certificate problem, not a
   data problem. Go to **ZATCA credentials expired** below.

**Never** clear the outbox to make the error go away. The outbox is the only record of what was sent.

---

## ZATCA credentials expired

**Alert:** `zatca_chain` with `AUTH_HOLD`, severity PAGE.

**What it means.** ZATCA returned 401 or 403. Certificates expire; CSIDs are per-device and have to be
renewed.

**Do this:**

1. Stop the ZATCA step. Documents held in `AUTH_HOLD` are safe — they are persisted and will be retried.
2. Renew the credential. **This is not a pipeline task**, and this project does not implement live onboarding
   (see `HONESTY.md` and `docs/PROJECT_IN_PLAIN_ENGLISH.md`): CSR generation, compliance CSID and production
   CSID are a separate, manual ZATCA process per EGS unit.
3. Once renewed, re-run. The held documents retry with their original bytes.

**Prevention:** certificate expiry is a calendar item, not an alert. Whoever owns this system should have a
reminder 30 days before each CSID expires.

---

## A Silver step failed

**Alert:** `silver_build` or `mdm_resolve`, severity PAGE.

**Do this:**

1. Read the task log. Silver failures are usually a schema change in a source: a new column, a renamed one, or
   a type that no longer parses.
2. Check quarantine — Silver routes what it cannot parse rather than guessing:
   ```sql
   SELECT reason, COUNT(*) FROM quarantine.<table> GROUP BY reason;
   ```
3. If it is an encoding problem (`CP1256_UNRECOVERABLE`), that is expected for genuinely corrupt rows. 15 such
   rows exist in the reference data and are *meant* to be quarantined, not rescued.
4. Fix the parser or accept the quarantine, then re-run.

**Never** add an `else` branch that maps an unknown value to a default. Unknown values quarantine or raise.
That rule is enforced by `accepted_values` tests and exists because a silent default becomes a wrong number in
a ledger.

---

## A serving step failed

**Alert:** `ai_index` or `ndmo_catalog`, severity TICKET.

**What it means.** The AI search index or the data catalogue did not rebuild. **No money is affected** —
nothing downstream of these moves a riyal. This is why they do not page.

**Do this:**

1. Re-run the step the next working day.
2. If `ndmo_catalog` fails repeatedly, the classification rules may disagree with a changed schema. Check
   `meta.column_classification` against the live columns.
3. Until it is rebuilt, the Command Center's classification view is stale. Say so rather than hiding it.

---

## The residency gate failed

**Alert:** `residency_gate`, severity PAGE.

**What it means.** A column classified SECRET or above is in a zone that may not hold it, or a classification
is missing. The gate fails the build rather than publishing.

**Do this:**

1. The gate names the column and the zone. Decide which is wrong — the classification or the placement.
2. If the column genuinely belongs there, the rule needs updating, with a version bump, not a suppression.
3. Re-run.

**Known limitation, do not be surprised by it:** `config/residency_policy.yml` declares `region: KSA`, while
the capacity actually runs in UAE North. The gate checks classification against zone; it does not check the
physical region. See `HONESTY.md`.

---

## The close will miss its deadline

**Alert:** `close_sla`, severity PAGE.

**What it means.** The run has not published Gold and 06:00 Riyadh is approaching or past.

**Do this:**

1. Find where the run is. If a step is still running, let it finish — killing a half-written step costs more
   than the delay.
2. Tell finance **before** the deadline, not after. They can work from the previous close; what they cannot do
   is discover at 08:00 that today's numbers are not there.
3. If the run has failed, work the relevant runbook above.
4. Record the breach. An SLA nobody measures is a wish.

---

## An unrecognised failure

**Alert:** any step with no matching runbook, severity PAGE.

**Do this:**

1. Capture the full task log before anything else. Re-running destroys the evidence.
2. Establish whether Gold published. If it did not, the system is in its safe state and you have time.
3. Re-run once. Many failures are transient — a Lakehouse SQL endpoint lagging behind a Spark write is a known
   one (`HONESTY.md`), and the identical build a minute later passes.
4. **If it fails twice the same way, stop re-running.** It is a defect.
5. Write a new section here. This file grows from real incidents, which is the only way a runbook stays true.

---

## Answering a right of access request

**Not an alert.** A person has asked what you hold about them, under PDPL.

**Do this:**

1. **Authenticate the requester first.** Everything below hands over personal data. An access request is a
   recognised way to steal someone's identity data, and the only defence is being sure who is asking.
2. Run the summary. It prints what is held and nothing sensitive:
   ```powershell
   .\.venv\Scripts\python.exe scripts\subject_access.py --national-id <id>
   ```
3. Read the status:
   - **`NOT_FOUND`** — nothing is held. That is a complete answer; send it.
   - **`ERASED`** — this person was erased. The report carries the DSR id and the date. Tell them their data
     was destroyed and that signed tax invoices are retained under a statutory obligation with no link to
     their identity. **Do not** attempt to reconstruct anything from surviving rows; the tool will not, and
     neither should you.
   - **`DISCLOSED`** — proceed.
4. Produce the file only when you are ready to deliver it:
   ```powershell
   .\.venv\Scripts\python.exe scripts\subject_access.py --national-id <id> --out dsar.json
   ```
   Add `--portability` for the machine-readable subset the subject provided.
5. Deliver it through a channel the subject is authenticated on. Not email to an address from the request.
6. **Destroy the file.** It is a cleartext copy of personal data outside every control that protects it at
   rest. The script will not delete it for you, deliberately — that is a decision a person makes.

**What is withheld, and say so rather than omitting it:** the signed tax invoices. They are retained under
ZATCA and tax record-keeping obligations, and the subject is entitled to know they exist.

**Rights not implemented:** restriction and objection. If one is requested, it has to be handled manually and
recorded. Do not claim the system supports them.

---

## A personal data breach

**Not an alert** — no automated detection exists for this, which is itself worth knowing.

**What counts.** Unauthorised access to, loss of, or disclosure of personal data. In this system the
realistic routes are: the KEK or HMAC key leaking, a `.env` reaching source control, an access-request file
sent to the wrong person, or the agent Function being abused while caller verification is off.

**First hour, in order:**

1. **Stop the bleeding.** Revoke the credential, delete the file, disable the endpoint. Containment before
   investigation.
2. **Preserve evidence.** Do not re-run anything, do not clear logs. Capture Delta table history before it is
   vacuumed away.
3. **Scope it.** Which subjects, which categories, how many, and over what period. `audit.pdpl_dsr_evidence`,
   the Delta history and the run manifests are where this comes from.
4. **Ask whether the data was readable.** PII is encrypted per subject. A leak of ciphertext without the KEK
   is a different incident from a leak of the KEK. Say which, precisely.
5. **Notify.** PDPL requires notifying SDAIA, and affected subjects where the risk to them is high.
   **The controller's legal counsel decides the timing and wording — not the engineer.** Escalate within the
   first hour; do not draft the notification yourself.

**Then:** write what happened, what was affected, what was done, and what changed so it cannot recur. Add a
runbook section here if the cause was operational.

**What this project does not have:** no breach detection, no notification template, no agreed escalation
contact, no tabletop exercise has been run. This section is a procedure, not a capability. See
`docs/compliance/DPIA.md` residual risk 8.

---

## Re-running and backfilling

**`scripts/backfill.py` is the tested procedure.** It is not a partial-date re-run — this pipeline rebuilds
Silver and Gold from the whole of Bronze every time, which is slower but means there is no "which days do I
re-run?" question to get wrong.

What it does:

1. Fingerprints every Gold table **before**.
2. Re-runs the pipeline.
3. Fingerprints **after** and reports exactly which tables and values changed.

Run it with `--dry-run` first — that is the default, and it refuses to execute without `--execute`.

**A backfill that changes nothing is the expected result** when re-running identical source data. If a
fingerprint moves and you did not change source data, that is a finding, not noise.

---

## What this project does not have

Stated plainly, because a runbook that implies more than exists is a liability:

- **There is nobody on call.** This file describes what to do; it does not say who.
- **Alerting delivers to a webhook if one is configured**, and to the task log otherwise. There is no paging
  rotation, no escalation ladder and no acknowledgement tracking.
- **The schedule is not dependable unattended** while the job runs on Fabric's starter pool, which sleeps.
- **No DR drill has been run against the Fabric tenant.** `scripts/dr_drill.py` exercises the local warehouse.

See `HONESTY.md` and `docs/PROJECT_IN_PLAIN_ENGLISH.md` for the full distance to production.

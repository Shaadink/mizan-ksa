# MIZAN-KSA: brief for an outside review (copy everything below into another AI)

---

## Your role and task

Act as a panel of four experts reviewing one portfolio project:

1. a **principal data architect** who has shipped regulated payment platforms on Microsoft Fabric / Azure;
2. a **senior technical recruiter** hiring data engineers and analytics engineers in Saudi Arabia and the GCC;
3. a **world-class product and UI/UX designer** (think Linear, Stripe, Vercel, Apple keynote demos);
4. a **creative technologist** who builds cinematic, interactive data experiences (WebGL, motion, storytelling).

The project is complete and working (details below). Your job is to propose what would make it **more
impressive, clearer and more memorable to a recruiter or hiring manager in the first 30 seconds**, and more
convincing to a senior engineer in a 30-minute deep dive. Research current (2025-2026) features of Microsoft
Fabric, Azure AI and modern data tooling, and current best-in-class product UI, before you answer.

Be concrete and honest. Say when an idea is gimmicky, risky, or would hurt credibility. Do not suggest faking
data, numbers, customers or certifications.

---

## 1. What MIZAN-KSA is (in one paragraph)

MIZAN-KSA ("mizan" is Arabic for *the balance / the scales*) is a **Saudi regulated-commerce and payments data
integrity platform**, built as an engineering reference architecture on **synthetic data** (fixed seed,
byte-identical reruns). It follows one commercial transaction end to end: order capture, **ZATCA Phase-2
e-invoice** (signed, hash-chained, cleared or reported), **mada / card / BNPL / SADAD payment**, the bank's
**T+1 settlement file**, and an **ERP general ledger** (SAP ACDOCA-shaped). It proves that bank, payments and
ledger agree **to the last halala (SAR 0.01)**, that the invoice chain survives network failures and worker
crashes, and that personal data is encrypted on arrival and erasable under the Saudi **PDPL** without touching
signed tax evidence. It runs locally and on **Microsoft Fabric**. It is a portfolio project by one data engineer
(job hunting in KSA/GCC); it is honest about being a reference architecture, not a certified product.

## 2. Stack (frozen by design; additions need the owner's approval)

- **Data plane: Microsoft Fabric.** OneLake Delta Lakehouse `LH_MIZAN` (schemas brz, ctl, slv, quarantine,
  security, audit, meta, ai), PySpark notebooks, Warehouse `WH_MIZAN` (schema gld, built with dbt-fabric),
  Eventstream + Eventhouse (KQL) for real-time risk events, Direct Lake semantic model, Power BI report.
- **Control plane:** Apache Airflow, dbt (fabric + local DuckDB for CI), OpenLineage + Marquez (column lineage),
  pytest, Docker, GitHub Actions (3 CI jobs).
- **Approved additions (with decision records):** the MIZAN Command Center web front end (Three.js, GSAP, D3),
  deployed as a **Fabric App** (Microsoft's Rayfin SDK, preview); and the **Ask MIZAN agent**: Azure OpenAI
  `gpt-4.1-mini` behind one Azure Function (managed identity, no keys).
- Not allowed: other databases, Great Expectations, Kubernetes, extra business domains.

## 3. What has been built (all working and tested)

| Module | What it proves | Evidence |
|---|---|---|
| Deterministic generator | 121 merchants, 20 business days (12 Feb to 3 Mar 2026, spanning Ramadan 1447), captures, refunds, chargebacks, cash, credit notes, bank files, GL | same seed gives byte-identical files |
| ZATCA engine | UBL XML, C14N 1.0 canonicalisation, SHA-256 invoice hash, PIH chain, ICV counters, TLV QR codes, ECDSA secp256k1 signing (test key), state machine SUBMITTING / UNKNOWN_OUTCOME / CLEARED / REPORTED / CONFIRMED_REJECTION / AUTH_HOLD | 25,001 documents, **0 chain breaks**; a timeout plus a killed worker recovers and retries identical bytes; a 400 rejection stays in the chain and is fixed by a new document |
| Bronze / Silver (PySpark + Delta) | PII encrypted at the Bronze write (HMAC token + AES-256-GCM per-subject key), quarantine for bad rows, Asia/Riyadh timezone | resend of all files is fully de-duplicated |
| Gold (dbt) | Reconciliation on a **key spine** (union of keys, no LEFT JOIN that drops rows), IN_TRANSIT rows for missing bank files, payment-method split, ZATCA clearance ledger, NDMO scorecard, Saudi calendar (Umm al-Qura Hijri) | captures **SAR 22,390,730.16**; bank variance **0.00** and GL variance **0.00** on 2,121 assessed merchant-days; 112 merchant-days honestly "not assessed" (bank file pending, SAR 1,125,184.70 in transit); dbt **65/65 PASS on Fabric**; planted defects trip a circuit breaker |
| Arabic MDM | Arabic normalisation (mojibake, tashkeel, ligatures, Arabic-Indic digits, nicknames), deterministic match ladder | 3,985 records into 2,552 golden customers, five spellings into one id, brothers never merged |
| PDPL + NDMO | Erasure shreds keys and removes the token-to-identity link; legal hold keeps signed tax records; Restore Guard re-shreds restored backups; 350 columns classified in four NDMO tiers, fail-closed | one request erases 5 linked records; totals unchanged |
| Spark skew | One mega-merchant on 65% of 20M rows; AQE skew join and 16-bucket salting | identical row counts and SAR checksum in all runs |
| Streaming | 91,513 events replayed through Eventstream into Eventhouse; KQL rules for velocity bursts, a mule ring and late ZATCA reports | detections fire exactly where planted |
| Governed AI (local) | Entitlement filtering before retrieval, money only from read-only SQL, audited refusals | tests |
| Orchestration and lineage | Airflow DAGs, OpenLineage events into Marquez | **76/76 Gold columns** traced to source |
| Power BI | 3-page report generated as code (CFO Settlement, Tax ZATCA Health, CDO Data Trust), custom dark theme | numbers verified by DAX through the API |
| Tests and CI | 269 Python tests, 183 app tests, CI on every push | all green |

Twelve architecture decision records (ADR-001 to ADR-012) and an **HONESTY.md** that lists every limitation.

## 4. The MIZAN Command Center (the showpiece UI): please review this closely

**What it is:** a cinematic, scroll-driven web control tower that tells the platform's story. It runs as a
**Fabric App** (protected: Fabric sign-in plus app permission), where **every figure is a live DAX query** on the
semantic model; filters re-query Fabric. A standalone copy shows the same scenes from an exported snapshot.

**Visual theme ("MIZAN Night"):**
- Deep night-navy background (`#060b16`), translucent glass panels (`rgba(16,27,48,.66)`), thin gold hairlines.
- Accent **gold** `#d9b25f` / `#f3d99c` (the scales, money), **emerald** `#2fbf8f` (balanced / pass), cyan
  `#5cc8ff`, amber `#f2a93b` (pending / warning), red `#ff5d63` (break).
- Fonts: **Bricolage Grotesque** (display headlines), **IBM Plex Sans** (body), **IBM Plex Mono** (numbers, IDs,
  labels), **IBM Plex Sans Arabic** (Arabic).
- Honesty rules in the design: green only for a real pass; every status has an icon or sign, not colour alone;
  a provenance line under every scene; money animates in integer halalas and lands on the exact value; no
  official brand logos (own simple badges for mada, card, BNPL, SADAD).

**Layout:** left sidebar menu, top bar (search for MID / invoice UUID / ICV / EGS / city, role views ALL / CFO /
TAX / CDO, "Play the story" button, Arabic toggle, profile), a sticky filter bar (date range, merchant, city, bank
file status, payment method, EGS, invoice flow, ZATCA outcome) with removable chips.

**Scenes (scroll order):**
- **00 The scales:** a Three.js golden balance scale. Captures pour in, the bank file follows a day later, and
  the scales settle only when bank and ledger agree; a SAR counter and an identity line
  (expected net = bank paid + in transit + quarantined).
- **01 Executive pulse:** KPI tiles with sparklines, plus payment-method cards with their own fee rates.
- **02 Money flow:** a D3 Sankey from gross captures to refunds, fees, net sales, GL and the bank.
- **03 Daily ledger:** a day-by-day chart on the Umm al-Qura calendar, with Ramadan marked; the last day is
  hatched as "in transit".
- **04 Reconciliation:** a merchant-by-day heatmap (2,233 cells), with hatched "not assessed" cells. Pressing B
  injects planted defects and the circuit breaker stops the build.
- **05 ZATCA chain:** an animated chain tape (ICV 102 timeout, the worker killed mid-submit, recovery with identical
  bytes), EGS device cards, an outcome bar and 24-hour reporting rings.
- **06 PDPL erasure:** keys shredding, legal hold kept.
- **07 Arabic MDM:** five spellings collapsing into one golden customer.
- **08 Risk stream:** the replayed event stream with detections.
- **09 Store map:** stores by Saudi city, coloured by reconciliation status, with routes to acquirer and bank.
- **10 Data trust:** lineage graph and the NDMO classification breakdown.
- **11 Platform:** the Spark skew "race" and the Fabric run timeline.
- **12 Data life cycle:** a clickable flow from sources to Bronze, Silver, Gold and the apps; each box jumps to its
  proof.
- **13 Ask MIZAN:** a chat-first assistant (described below).

**Interactions:** cross-filtering by clicking any chart, a merchant-day drill panel, presenter mode (P), number
keys for scenes, T ("trace one riyal"), B ("break a halala"), L (Arabic, right-to-left, with numbers and IDs kept
left-to-right), Ctrl K command palette, story mode with captions.

**Ask MIZAN (just redesigned):**
- **Layout:** headline "Ask your data. See the proof.", a role switcher (Finance, Tax, Data office, All staff), an
  Agent / Guided pill, a welcome screen with role-aware starter cards, chat bubbles with badges
  ("Agent · 2 queries", "✓ Numbers verified", "Refused · Nothing retrieved"), and a right panel "How this answer
  was found" (numbered steps, the exact DAX behind "Show DAX").
- **Agent mode:** Azure OpenAI plans which of eight approved tools to call (reconciliation, daily, top merchants,
  ZATCA, payment methods, data quality, calendar, glossary). The tools run in the browser on live DAX under the
  viewer's own Fabric login. Code checks that every number in the answer appears in a tool result before it is
  shown. Personal data and write requests are refused before the model sees them. It answers English and Arabic.
- **Guided mode:** no language model, a fixed list of approved questions, used as the automatic fallback.

## 5. Current stage

- All 13 build phases and the 5-stage Fabric App plan are **done**, deployed and tested. The Ask MIZAN agent is
  live and verified end to end (English and Arabic, multi-step tool chains, role refusals).
- **Owner to-dos:** record the 2:30 demo video (shot list exists); capture 8 README screenshots; have a native
  speaker review the Arabic.
- **Known limits:**
  - The Fabric workspace is on a free **trial** capacity in a college tenant, so the Fabric Data Agent is
    unavailable (it needs paid F2+).
  - The app is visible only to people in that tenant (not public); a private snapshot copy exists for sharing.
  - The agent's Azure credit expires mid-December 2026; after that the assistant falls back to Guided mode.
  - The Azure Function cannot verify the caller's college login; it uses origin checks, rate limits and a budget
    alert instead.
  - Synthetic data only.

## 6. Rules any suggestion must respect

1. **Every number comes from Gold or a named proof run**: never typed by hand, never invented.
2. **Money is exact**: Decimal / DECIMAL(18,2), integer halalas in the browser, never floats.
3. **Honesty:** synthetic data and reference-architecture status stay visible; no fake customers, logos,
   certifications or "AI-generated" claims that are not true.
4. **Frozen data design:** schemas, table and module names stay; new Gold columns or tables need the owner's
   approval; new tools or services need approval (say what they cost).
5. **Privacy:** no personal data shown; IDs and phones masked.
6. Arabic must be correct and right-to-left; Saudi context (ZATCA, SAMA, mada, PDPL, NDMO, Hijri calendar)
   should feel native, not decorative.

## 7. What I want from you

Answer in these sections:

1. **First impression audit:** what a recruiter understands in 30 seconds today, and what they miss.
2. **Top 10 ideas, ranked by impact divided by effort.** Use one table:
   | # | Idea | Why it impresses (recruiter / engineer) | Effort (S/M/L) | Where it lives (Fabric, Command Center, README, video, LinkedIn) | Risk or caveat |
3. **Cinematic and "mind-blowing" UI/UX ideas** for the Command Center. Be specific: what moves, when, why it
   tells the story, which library, how it stays fast and accessible (reduced motion, keyboard, phone). Include
   at least one idea for the **first 5 seconds** of the page and one for **Ask MIZAN**.
4. **Enterprise-grade features** that a principal engineer would respect (observability, SLAs, data contracts,
   cost, security, CI/CD, disaster recovery...) that fit the frozen stack.
5. **Microsoft Fabric and Azure AI features (2025-2026)** this project should showcase, with links to the official
   documentation you relied on.
6. **Storytelling:** a sharper one-line pitch, a 30-second recruiter pitch, and the three numbers to lead with.
7. **What to remove or simplify:** anything that adds noise or could hurt credibility.
8. **Three ideas nobody else would think of**: bold, original, still honest.

Keep every idea buildable by one engineer with an AI coding assistant. Prefer depth and specificity over long
lists.

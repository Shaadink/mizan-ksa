# Improvement ideas: research notes from the builder (2026-11-16)

Written by the AI that built MIZAN-KSA, after researching current Microsoft Fabric / Azure features, portfolio
reviews and data-experience design. To be merged with the ideas from the outside reviews (AI_IDEA_BRIEF.md).
Effort: S = under a day, M = 1-3 days, L = a week. "Approval" = needs the owner's OK under the frozen-stack rule.

## What the research says (short)

- **Reviewers decide fast.** Portfolio reviews are short (one 2026 checklist reports a median of 47 seconds), so the
  README, the first screen and a video carry most of the weight. One deep end-to-end project beats many shallow
  ones, and quantified results matter. MIZAN already has the depth; its first 30 seconds can be sharper.
- **Fabric's 2026 headline features** are Fabric IQ (ontologies over OneLake and semantic models, with Activator
  rules that turn them into actions), Real-Time Intelligence (Real-Time Dashboards, Activator, MCP servers for
  Eventhouse and Activator), data agents that can be consumed over MCP, and translytical task flows (Power BI
  writing back through user data functions, GA in 2026). Several are preview, and some may not run on a trial
  capacity, so test each one before promising it.
- **Azure OpenAI realtime voice** works in the browser over WebRTC with a short-lived token from a small service
  (we already have that Function). Arabic quality is not documented, so a test is needed first.
- **Design trend:** award sites are dominated by scroll-driven, immersive storytelling. MIZAN already uses that
  language; the next step is interaction that *proves* something, not more decoration.

## Ranked ideas

| # | Idea | Why it impresses | Effort | Approval |
|---|---|---|---|---|
| 1 | **Record the 2:30 video and the 8 README screenshots** (shot list exists) | The single biggest lever for a 47-second review; recruiters rarely get a tenant login | S | no |
| 2 | **"Verify it yourself" in the browser**: pick any invoice, and the page recomputes its SHA-256 hash and checks the PIH link to the previous one with the browser's built-in WebCrypto; show green ticks hop by hop | A dashboard that invites the viewer to check the math instead of trusting it; deeply on-brand (MIZAN = the balance); no new tool | M | no (needs the signed sample in the export) |
| 3 | **Recruiter mode**: a toggle that overlays each scene with "What I built / skill used / why it matters" chips (PySpark, dbt, KQL, Fabric, Azure OpenAI...) and a 5-scene "Highlights" path | Makes the depth readable in 60 seconds without removing anything for engineers | S | no |
| 4 | **Time machine scrubber**: drag through the 20 days; the heatmap, scales and in-transit band replay as each T+1 bank file lands, and Ramadan shading sweeps across | Turns the hardest concept (T+1, "not assessed") into a visible story; uses data already exported | M | no |
| 5 | **"Explain this number"**: click any KPI to see its path, KPI to Gold column to Silver table to source file, using the OpenLineage graph already built | Answers the senior engineer's first question ("where does this come from?") in one click | M | no |
| 6 | **Resolve-a-break workflow (translytical task flow)**: a finance user annotates or approves a variance from Power BI; a Fabric user data function writes an audited case row | Shows write-back, audit trail and human-in-the-loop, the step from "report" to "operations" | M | yes (new ctl table) |
| 7 | **Fabric IQ ontology + Activator rule**: Merchant, Invoice, Payment, Settlement and GL Posting entities; rules such as "bank variance not 0" or "simplified invoice not reported within 24 h" raise an alert | Matches Microsoft's 2026 headline story; a strong interview topic | M-L | yes, and preview/trial support must be checked first |
| 8 | **CFO morning briefing**: one button, and the agent writes a 5-line briefing with verified numbers, exportable as PDF | Shows an AI use that saves real time, with the same number check | S-M | no |
| 9 | **Observability page**: freshness SLOs per Gold table, pipeline run history, dbt contract status, Fabric capacity use and cost per run | What principal engineers look for after the demo: is it operable? | M | no |
| 10 | **Public "MIZAN in 60 seconds" page**: a separate public project page (not the internal tool) with the video, the three headline numbers and a glossary-only explainer chat on snapshot figures | Recruiters outside the college tenant can see it; keeps internal and public worlds apart, as real companies do | M | yes (public hosting, e.g. a free Azure Static Web App) |
| 11 | **Voice Ask MIZAN** ("speak to your ledger", English and Arabic) with Azure OpenAI realtime over WebRTC; same tools and number check | High wow factor in a live demo | M | yes; test Arabic quality and per-minute cost first |
| 12 | **dbt model contracts on Gold**, shown as contract badges in the lineage scene | Cheap, credible enterprise signal (schemas enforced, not just tested) | S | no |

## Cinematic ideas for the Command Center

- **First 5 seconds:** the page opens dark; a single gold hairline draws the beam of the scales while the live
  status types out "Querying Fabric... 2,233 merchant-days... balanced to SAR 0.00". The scale's pans drop exactly
  as the real DAX result arrives, so the animation is tied to a real round trip and not a fake timer. Reduced-motion
  users get the final state at once.
- **Follow one riyal (upgrade of T):** a single gold particle travels a 3D path, till to e-invoice to acquirer to
  bank file to GL, and stops at each hop to show the real record ID (masked) and timestamp. The camera follows it.
- **Break a halala (upgrade of B):** the scale tips, a red crack runs across the heatmap to the broken cell, the
  publish button greys out, and the circuit-breaker test name appears like a court ruling.
- **Ask MIZAN:** while the agent works, the proof panel builds live, one step lighting up per tool call, and each
  number in the answer is underlined in emerald as it passes the check. Hovering a number highlights the tool
  result it came from.
- **Arabic switch:** the layout mirrors with a smooth reflow; headlines morph between scripts rather than snapping.

## What I would simplify

- 14 scenes is a lot for a first visit: lead with a 5-scene highlights path (scales, pulse, reconciliation,
  ZATCA chain, Ask MIZAN) and keep the rest one click away.
- Hide Guided mode behind the agent when the agent is available; keep it as a silent fallback.
- Keep every claim matched to HONESTY.md; no "AI-powered" wording without the number check behind it.

## Three original ideas

1. **Trustless dashboard:** every headline number has a "verify" action that recomputes it in the browser from the
   exported Gold rows and shows a match tick (built-in WebCrypto/JS for hashes and sums; DuckDB-WASM would make it
   SQL but needs approval).
2. **Regulator replay:** a "ZATCA audit" button produces an auditor pack in seconds: chain continuity proof,
   sample signed-invoice hashes, the rejection and correction pair, and the 24-hour reporting compliance. It is
   framed as a reference demo, never as a certified tool.
3. **Ramadan-aware operations:** a scene showing how sales, refunds and settlement timing shift during Ramadan,
   on the Umm al-Qura calendar, using the dates already in Gold. Saudi context that feels native, not decorative.

## Sources

- [Microsoft Fabric: What's new](https://learn.microsoft.com/en-us/fabric/fundamentals/whats-new)
- [Introducing Microsoft Fabric IQ (Fabric blog)](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/from-data-platform-to-intelligence-platform-introducing-microsoft-fabric-iq/5172484)
- [Bringing Fabric Activator into Ontology (Fabric blog)](https://community.fabric.microsoft.com/t5/Fabric-Updates-Blog/From-insight-to-action-Bringing-Fabric-Activator-into-Ontology/ba-p/5172260)
- [Gartner first take: Fabric IQ](https://www.gartner.com/en/insights/gartner-first-takes/microsoft-fabric-iq)
- [FabCon and SQLCon 2026 (Azure blog)](https://azure.microsoft.com/en-us/blog/fabcon-and-sqlcon-2026-in-barcelona-building-the-data-foundation-for-microsoft-copilot-and-agents/)
- [Choose a Microsoft Fabric MCP server](https://learn.microsoft.com/en-us/rest/api/fabric/articles/mcp-servers/fabric-mcp-servers-list)
- [Translytical task flows overview](https://learn.microsoft.com/en-gb/power-BI/create-reports/translytical-task-flow-overview)
- [Translytical task flows generally available](https://powerbi.microsoft.com/blog/translytical-task-flows-generally-available/)
- [Azure OpenAI realtime audio over WebRTC](https://learn.microsoft.com/en-ie/Azure/foundry/openai/how-to/realtime-audio-webrtc)
- [Data engineer portfolio review checklist 2026](https://dataengineeracademy.com/blog/data-engineer-portfolio-review-checklist-2026-what-hiring-managers-actually-score/)
- [Data engineering portfolio projects that get hired](https://www.dataexpert.io/blog/data-engineering-portfolio-projects-get-hired)
- [Scrollytelling trends 2026 (vendor opinion)](https://svilenkovic.com/3d/scrollytelling-trends-2026)

# ADR-012: Ask MIZAN agent: Azure OpenAI plans, code governs

- **Status:** Accepted (owner-approved addition to the frozen stack, 2026-11-16: Azure OpenAI + one Azure Function)
- **Date:** 2026-11-16

## Context

Ask MIZAN (Command Center scene 13) began as guided questions: fixed intents, no language model. The owner wanted
an agent that understands free wording (English or Arabic) and chains several queries. The Fabric Data Agent is
not an option: it needs a paid F2+ capacity in the college tenant, and Fabric Apps have no data-agent connector
(connector list: lakehouse, warehouse, SQL database, semantic model). The owner's Azure credit lives in a different
directory (personal tenant) from the Fabric workspace (college tenant).

## Decision

- **Model:** Azure OpenAI `gpt-4.1-mini`, Global Standard pay-per-use (no hourly cost), throughput capped at 30K
  tokens per minute, in the owner's subscription (`rg-mizan-agent`, UAE North). API keys are disabled.
- **Service:** one Azure Function (`apps/ask-agent/`, Flex Consumption, Python 3.12). Its managed identity holds
  "Cognitive Services OpenAI User"; no key exists anywhere. It accepts only the Fabric App's origin, is rate
  limited, and caps request and reply sizes. A USD 5 monthly budget alert emails the subscription owners.
- **Tools, not queries.** The model may only request seven tools (`get_reconciliation`, `get_daily`,
  `get_top_merchants`, `get_zatca`, `get_payment_methods`, `get_data_quality`, `get_calendar`) whose only
  arguments are validated filters. It never writes DAX or SQL.
- **Tools run in the browser**, on live DAX through the Fabric App connector under the viewer's own Fabric login
  (Build permission). The server never sees a Fabric token or row-level data; the cross-tenant split does not
  matter because only tool results travel.
- **Entitlements twice:** the server offers the model only the tools whose Gold tables the role may read (same
  tiers and groups as `mizan.ai.governed.GOLD_ACL`); the browser checks again before running a tool.
- **Code computes, the model copies.** Derived values (expected net per day, fee rate in bps, share of SAR) are
  computed in code with integer halalas. Business rules travel inside tool results.
- **Number check:** every number in an answer must appear in a tool result, checked on the server (one corrective
  retry) and again in the browser. A failing answer is never shown; the guided answer is shown instead.
- **Refused before the model:** personal data (national ID, iqama, phone, email, names, IBAN) and write requests.
- **Fallback:** guided mode answers whenever the agent is unavailable, rate limited, or unverified; the standalone
  page (no live connector) always uses guided mode. Each answer is labelled AGENT or GUIDED.

## Consequences

- Cost is per question (well under one US cent); idle cost is a few cents a month for the Function's storage.
- The Function cannot verify the caller's college Fabric login (separate directory); origin check, rate limits, the
  throughput cap and the budget alert bound misuse. Stated in HONESTY.md.
- Global Standard may process a request in any Azure region (data at rest stays in UAE North); the in-region
  option has zero quota on this subscription. Only Gold aggregates are sent, never personal data.
- The number check is lexical: it proves each number appeared in a tool result, not that it is used in the right
  sentence. Business rules in tool results and temperature 0 reduce, but do not remove, wrong wording.
- The free Azure credit expires 2026-12-14; afterwards the agent stops unless the subscription is upgraded, and
  Ask MIZAN falls back to guided mode by itself.

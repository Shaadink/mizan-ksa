# ADR-007: Event amounts stay positive; only derived net positions are signed

- **Status:** Accepted (Phase 3, project decision within spec v1.1 build rule 1)
- **Date:** 2026-11-13

## Context

Build rule 1 says amounts are positive and `event_type` carries the sign. The spec's Gold reference SQL sums
`net_settled_sar` from `slv.settlement_lines` directly, which only works if refund and chargeback lines reduce
the total. The bank file and the ACDOCA-shaped GL both use a direction indicator (`dr_cr`, `DRCRK`).

## Decision

- Every event amount (`payment_lifecycle.amount_sar`, settlement `gross_amount_sar`, fees, GL `amount_sar`) is
  stored positive. Direction lives in `event_type`, `dr_cr` or `debit_credit`. Delta CHECK constraints enforce `> 0`.
- `slv.settlement_lines.net_settled_sar` is the bank's **signed net position** (CR +, DR -): a derived balance,
  not an event amount. The Gold circuit breaker sums it as in the spec.
- Gold applies the GL sign from `debit_credit` (S = +, H = -) when it aggregates card clearing.

## Consequences

The spec SQL for the bank leg is used verbatim. The GL leg adds one `CASE` on `debit_credit`. No negative event
amount can enter Silver.

"""Reference implementations of the EH_MIZAN KQL rules (kql/), used by tests to fix the expected alerts.

Named as velocity rules, not regulatory controls (no SAMA clause is cited). Thresholds mirror
docs/policies/fraud_velocity_rules.md: >5 checkouts per customer token in 10 minutes; one mobile token on >3
distinct customer tokens in 24 hours; simplified (REPORTING) invoices not reported within 24 hours of issue.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

VELOCITY_MAX, VELOCITY_WINDOW = 5, timedelta(minutes=10)
MULE_MAX, MULE_WINDOW = 3, timedelta(hours=24)
SLA = timedelta(hours=24)


def _t(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def velocity_alerts(events: list[dict]) -> set[str]:
    by: dict[str, list[datetime]] = defaultdict(list)
    for e in events:
        if e["event_kind"] == "CHECKOUT" and e.get("customer_token"):
            by[e["customer_token"]].append(_t(e["event_ts"]))
    hits = set()
    for tok, ts in by.items():
        ts.sort()
        j = 0
        for i in range(len(ts)):
            while ts[i] - ts[j] > VELOCITY_WINDOW:
                j += 1
            if i - j + 1 > VELOCITY_MAX:
                hits.add(tok)
                break
    return hits


def mule_ring_alerts(events: list[dict]) -> set[str]:
    by: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for e in events:
        if e["event_kind"] == "CHECKOUT" and e.get("mobile_token") and e.get("customer_token"):
            by[e["mobile_token"]].append((_t(e["event_ts"]), e["customer_token"]))
    hits = set()
    for mob, rows in by.items():
        rows.sort()
        for i, (t0, _) in enumerate(rows):
            if len({c for t, c in rows[i:] if t - t0 <= MULE_WINDOW}) > MULE_MAX:
                hits.add(mob)
                break
    return hits


def sla_breaches(events: list[dict]) -> set[str]:
    """REPORTING invoices whose first REPORTED event is later than issue + 24h (or missing)."""
    issued: dict[str, datetime] = {}
    reported: dict[str, datetime] = {}
    for e in events:
        if e["event_kind"] != "INVOICE" or e["invoice_flow"] != "REPORTING":
            continue
        if e["invoice_event"] == "ISSUED":
            issued[e["invoice_uuid"]] = _t(e["event_ts"])
        elif e["invoice_event"] == "REPORTED":
            t = _t(e["event_ts"])
            reported[e["invoice_uuid"]] = min(t, reported.get(e["invoice_uuid"], t))
    return {u for u, t in issued.items() if u not in reported or reported[u] - t > SLA}

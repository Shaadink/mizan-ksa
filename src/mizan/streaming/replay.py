"""Phase 9b: replay the generated day of commerce into Eventstream ES_MIZAN (-> Eventhouse EH_MIZAN, KQL).

    python -m mizan.streaming.replay --data data/generated --dry-run data/out/stream/events.jsonl
    python -m mizan.streaming.replay --data data/generated --send          # needs EVENTSTREAM_CONNECTION in .env

Events are operational telemetry (KQL is never the ledger). No cleartext PII leaves this script: customers and
mobiles are sent as HMAC tokens. Three event kinds: CHECKOUT, PAYMENT, INVOICE (issue + outcome). Invoice
outcome latencies are synthetic (seconds), except the fault-plan document, whose final REPORTED event is placed
26 hours after issue so the 24-hour reporting SLA rule has a case to catch. `--inject-velocity-burst` adds a clearly
labelled synthetic burst (event_source = REPLAY_INJECTED) for the velocity and mule-ring rules.

Transport: the Eventstream custom endpoint speaks the Event Hubs protocol; this uses its HTTPS REST API with a SAS
token built from the connection string (no extra client library).
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

EVENT_KINDS = ("CHECKOUT", "PAYMENT", "INVOICE")
SLA_BREACH_HOURS = 26


def _ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _token(key: bytes, purpose: str, value: str | None) -> str | None:
    if not value:
        return None
    return "tok_" + hmac.new(key, f"{purpose}|{value}".encode(), hashlib.sha256).hexdigest()[:20]


def build_events(data: Path, hmac_key: bytes, *, inject_burst: bool = False) -> list[dict]:
    data = Path(data)
    out: list[dict] = []
    with (data / "orders/commerce_events.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["event_type"] != "ORDER_PLACED":
                continue
            out.append({"event_kind": "CHECKOUT", "event_id": r["event_id"], "event_ts": r["event_ts_utc"],
                        "order_id": r["order_id"], "merchant_id": r["merchant_id"], "channel": r["channel"],
                        "customer_token": _token(hmac_key, "CUSTOMER", r["customer_ref"]),
                        "mobile_token": _token(hmac_key, "MOBILE", r["buyer_mobile"]),
                        "payment_means": r["payment_means"], "amount_sar": r["amount_sar"],
                        "event_source": "GENERATED"})
    with (data / "payments/payment_events.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out.append({"event_kind": "PAYMENT", "event_id": r["payment_event_id"], "event_ts": r["event_ts_utc"],
                        "order_id": r["order_id"], "merchant_id": r["merchant_id"],
                        "payment_type": r["event_type"], "payment_scheme": r["payment_scheme"],
                        "amount_sar": r["amount_sar"], "invoice_uuid": r["invoice_uuid"] or None,
                        "event_source": "GENERATED"})
    plan = json.loads((data / "zatca/fatoora_fault_plan.json").read_text(encoding="utf-8"))
    slow = set(plan.get("responses", {}))
    with (data / "zatca/invoice_requests.jsonl").open(encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            issued = _ts(q["issue_ts_utc"])
            base = {"event_kind": "INVOICE", "invoice_uuid": q["invoice_uuid"], "request_id": q["request_id"],
                    "egs_id": q["egs_id"], "invoice_flow": q["invoice_flow"], "document_type": q["document_type"],
                    "merchant_id": q["merchant_id"], "amount_sar": q["total_incl_vat_sar"],
                    "issue_ts": q["issue_ts_utc"], "event_source": "GENERATED"}
            ok = "REPORTED" if q["invoice_flow"] == "REPORTING" else "CLEARED"
            out.append({**base, "event_id": f"{q['request_id']}:ISSUED", "event_ts": q["issue_ts_utc"],
                        "invoice_event": "ISSUED"})
            if q["request_id"] in slow:
                steps = [("UNKNOWN_OUTCOME", timedelta(seconds=30)),
                         ("REJECTED" if "HTTP_400" in plan["responses"][q["request_id"]] else ok,
                          timedelta(hours=SLA_BREACH_HOURS))]
            else:
                lag = int(hashlib.sha256(q["request_id"].encode()).hexdigest()[:4], 16) % 55 + 3
                steps = [(ok, timedelta(seconds=lag))]
            for name, delta in steps:
                out.append({**base, "event_id": f"{q['request_id']}:{name}", "event_ts": _iso(issued + delta),
                            "invoice_event": name})
    if inject_burst:
        out += _burst(hmac_key)
    out.sort(key=lambda e: (e["event_ts"], e["event_id"]))
    return out


def _burst(hmac_key: bytes) -> list[dict]:
    """Synthetic, labelled: 7 checkouts by one customer in 6 minutes (velocity) and 4 customers on one mobile."""
    t0 = datetime(2026, 2, 20, 17, 0, 0)
    cust = _token(hmac_key, "CUSTOMER", "INJECTED-C1")
    mob = _token(hmac_key, "MOBILE", "INJECTED-M1")
    ev = []
    for i in range(7):
        ev.append({"event_kind": "CHECKOUT", "event_id": f"INJ-V{i}", "event_ts": _iso(t0 + timedelta(minutes=i)),
                   "order_id": f"INJ-ORD-V{i}", "merchant_id": "MID900001", "channel": "ECOM",
                   "customer_token": cust, "mobile_token": None, "payment_means": "MADA", "amount_sar": "499.00",
                   "event_source": "REPLAY_INJECTED"})
    for i in range(4):
        ev.append({"event_kind": "CHECKOUT", "event_id": f"INJ-M{i}", "event_ts": _iso(t0 + timedelta(hours=i)),
                   "order_id": f"INJ-ORD-M{i}", "merchant_id": "MID900001", "channel": "ECOM",
                   "customer_token": _token(hmac_key, "CUSTOMER", f"INJECTED-MULE-{i}"), "mobile_token": mob,
                   "payment_means": "MADA", "amount_sar": "250.00", "event_source": "REPLAY_INJECTED"})
    return ev


# ----------------------------------------------------------------------------- Event Hubs REST transport

def parse_connection_string(cs: str) -> dict:
    parts = dict(p.split("=", 1) for p in cs.strip().split(";") if p)
    for k in ("Endpoint", "SharedAccessKeyName", "SharedAccessKey", "EntityPath"):
        if k not in parts:
            raise ValueError(f"connection string misses {k}")
    host = parts["Endpoint"].removeprefix("sb://").rstrip("/")
    return {"host": host, "key_name": parts["SharedAccessKeyName"], "key": parts["SharedAccessKey"],
            "entity": parts["EntityPath"]}


def sas_token(uri: str, key_name: str, key: str, ttl_s: int = 3600, now: float | None = None) -> str:
    expiry = str(int((now if now is not None else time.time()) + ttl_s))
    enc = urllib.parse.quote_plus(uri)
    sig = base64.b64encode(hmac.new(key.encode(), f"{enc}\n{expiry}".encode(), hashlib.sha256).digest())
    return (f"SharedAccessSignature sr={enc}&sig={urllib.parse.quote_plus(sig.decode())}&se={expiry}"
            f"&skn={key_name}")


def batches(events: list[dict], max_bytes: int = 900_000) -> list[list[dict]]:
    out, cur, size = [], [], 2
    for e in events:
        body = {"Body": json.dumps(e, separators=(",", ":"))}
        n = len(json.dumps(body, separators=(",", ":"))) + 1        # + the comma between items
        if cur and size + n > max_bytes:
            out.append(cur)
            cur, size = [], 2
        cur.append(body)
        size += n
    if cur:
        out.append(cur)
    return out


def send(events: list[dict], connection_string: str, *, speedup: float = 0) -> int:
    c = parse_connection_string(connection_string)
    url = f"https://{c['host']}/{c['entity']}/messages"
    sent = 0
    for b in batches(events):
        req = urllib.request.Request(url, data=json.dumps(b, separators=(",", ":")).encode(), method="POST", headers={
            "Authorization": sas_token(f"https://{c['host']}/{c['entity']}", c["key_name"], c["key"]),
            "Content-Type": "application/vnd.microsoft.servicebus.json"})
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (https URL built above)
            if r.status not in (200, 201):
                raise RuntimeError(f"Event Hubs returned {r.status}")
        sent += len(b)
        if speedup:
            time.sleep(speedup)
    return sent


def main() -> None:
    import os

    from mizan.privacy.crypto import Keys, load_dotenv
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data/generated"))
    ap.add_argument("--dry-run", type=Path, help="write JSONL here instead of sending")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--inject-velocity-burst", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pause", type=float, default=0, help="seconds between batches")
    a = ap.parse_args()
    events = build_events(a.data, Keys.from_env().hmac_key, inject_burst=a.inject_velocity_burst)
    if a.limit:
        events = events[:a.limit]
    if a.dry_run:
        a.dry_run.parent.mkdir(parents=True, exist_ok=True)
        with a.dry_run.open("w", encoding="utf-8", newline="\n") as f:
            for e in events:
                f.write(json.dumps(e, separators=(",", ":"), sort_keys=True) + "\n")
        print(f"wrote {len(events)} events to {a.dry_run}")
    if a.send:
        load_dotenv()
        cs = os.environ.get("EVENTSTREAM_CONNECTION")
        if not cs:
            raise SystemExit("EVENTSTREAM_CONNECTION is not set in .env (Eventstream custom endpoint, see "
                             "docs/STREAMING.md)")
        print(f"sent {send(events, cs, speedup=a.pause)} events")


if __name__ == "__main__":
    main()

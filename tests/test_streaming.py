"""Phase 9b: replay into Eventstream (event shape, no PII, determinism, Event Hubs REST transport) and the reference
velocity / mule-ring / reporting-SLA rules that the KQL functions mirror."""

import base64
import hashlib
import hmac
import json
import urllib.parse
from pathlib import Path

import pytest

from mizan.streaming import replay as R
from mizan.streaming import rules

KEY = b"k" * 32
KQL = Path(__file__).resolve().parents[1] / "kql"


@pytest.fixture(scope="module")
def events(gen_dir):
    return R.build_events(gen_dir, KEY, inject_burst=True)


def test_event_counts_and_order(events, gen_dir):
    kinds = {}
    for e in events:
        kinds[e["event_kind"]] = kinds.get(e["event_kind"], 0) + 1
    assert kinds["PAYMENT"] == 18_000 and kinds["CHECKOUT"] == 23_500 + 11
    assert kinds["INVOICE"] == 25_000 * 2 + 2                     # issue + outcome; 2 fault docs have 2 outcomes
    assert [e["event_ts"] for e in events] == sorted(e["event_ts"] for e in events)
    assert set(kinds) == set(R.EVENT_KINDS)


def test_replay_is_deterministic(events, gen_dir):
    again = R.build_events(gen_dir, KEY, inject_burst=True)
    digest = lambda ev: hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()  # noqa: E731
    assert digest(events) == digest(again)


def test_no_cleartext_pii_in_stream(events, gen_dir):
    from tests_helpers_pii import cleartext_probes
    probes = set(cleartext_probes(gen_dir, limit=3000))
    cells = {v for e in events for v in e.values() if isinstance(v, str)}
    assert not cells & probes
    assert all(k not in e for e in events for k in ("buyer_name", "buyer_mobile", "customer_ref"))


def test_rules_catch_exactly_the_planted_cases(events):
    v = rules.velocity_alerts(events)
    assert v == {R._token(KEY, "CUSTOMER", "INJECTED-C1")}           # only the injected burst
    assert rules.mule_ring_alerts(events) == {R._token(KEY, "MOBILE", "INJECTED-M1")}
    breaches = rules.sla_breaches(events)
    late = {e["invoice_uuid"] for e in events if e["event_kind"] == "INVOICE" and e["request_id"] == "IR-0000102"}
    rejected = {e["invoice_uuid"] for e in events if e["event_kind"] == "INVOICE" and e["request_id"] == "IR-0000103"}
    # IR-0000102: timeout -> crash -> REPORTED 26h late; IR-0000103: rejected (HTTP 400), so never reported (the
    # corrected re-issue is not part of the replay)
    assert breaches == late | rejected


def test_rules_quiet_without_injection(gen_dir):
    ev = R.build_events(gen_dir, KEY)
    assert rules.velocity_alerts(ev) == set() and rules.mule_ring_alerts(ev) == set()


def test_connection_string_and_sas_token():
    cs = ("Endpoint=sb://esns.servicebus.windows.net/;SharedAccessKeyName=key_1;"
          "SharedAccessKey=c2VjcmV0;EntityPath=es_abc")
    c = R.parse_connection_string(cs)
    assert c == {"host": "esns.servicebus.windows.net", "key_name": "key_1", "key": "c2VjcmV0", "entity": "es_abc"}
    uri = "https://esns.servicebus.windows.net/es_abc"
    tok = R.sas_token(uri, "key_1", "c2VjcmV0", ttl_s=60, now=1_000)
    enc = urllib.parse.quote_plus(uri)
    sig = base64.b64encode(hmac.new(b"c2VjcmV0", f"{enc}\n1060".encode(), hashlib.sha256).digest()).decode()
    assert tok == f"SharedAccessSignature sr={enc}&sig={urllib.parse.quote_plus(sig)}&se=1060&skn=key_1"
    with pytest.raises(ValueError):
        R.parse_connection_string("Endpoint=sb://x/;SharedAccessKeyName=k")


def test_batches_stay_under_the_size_limit(events):
    bs = R.batches(events[:20_000], max_bytes=200_000)
    assert sum(len(b) for b in bs) == 20_000
    assert all(len(json.dumps(b, separators=(",", ":"))) <= 200_000 for b in bs)


def test_kql_functions_exist_for_every_rule():
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(KQL.glob("*.kql")))
    for fn in ("VelocityAlerts", "MuleRingAlerts", "InvoiceReportingSlaBreaches", "ReportingLagByEgs"):
        assert "function with (folder" in text and fn in text
    assert "> 5" in text and "> 3" in text and "24h" in text and "10m" in text   # same thresholds as rules.py
    assert "MizanEventsMapping" in text

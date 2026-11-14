# Streaming: replay -> Eventstream ES_MIZAN -> Eventhouse EH_MIZAN (KQL)

KQL here is operational telemetry and hot risk alerting. It is never the financial ledger: money totals come only
from the Gold marts in WH_MIZAN.

## What flows

`src/mizan/streaming/replay.py` turns the generated data into one time-ordered stream of three event kinds:

| event_kind | from | key fields |
|---|---|---|
| CHECKOUT | orders/commerce_events.csv (ORDER_PLACED) | customer_token, mobile_token (HMAC tokens, no PII), merchant_id, amount_sar |
| PAYMENT | payments/payment_events.csv | payment_type (CAPTURE/REFUND/CHARGEBACK), payment_scheme, invoice_uuid |
| INVOICE | zatca/invoice_requests.jsonl | invoice_event ISSUED, then REPORTED / CLEARED / UNKNOWN_OUTCOME / REJECTED |

Invoice outcome latencies are synthetic (3 to 57 seconds). The fault-plan document IR-0000102 gets its final
REPORTED event 26 hours after issue, and the rejected IR-0000103 is never reported, so the 24-hour reporting SLA rule
has two real cases. `--inject-velocity-burst` adds 11 clearly labelled events (`event_source = REPLAY_INJECTED`) so
the velocity and mule-ring rules each have one alert. Without it, both rules are silent on the generated data.

## Setup (automated in Phase 10; manual fallback below)

1. **Eventhouse** `EH_MIZAN` with a KQL database `MIZAN_RT`.
2. In the KQL database, run `kql/01_tables.kql` (table `MizanEvents` + JSON mapping `MizanEventsMapping`), then
   `kql/02_velocity_rule.kql`, `kql/03_mule_ring_rule.kql`, `kql/04_invoice_reporting_sla.kql`.
3. **Eventstream** `ES_MIZAN`: source **Custom endpoint** (Event Hubs protocol); destination **Eventhouse** ->
   `EH_MIZAN` / `MIZAN_RT` / table `MizanEvents`, input format JSON, mapping `MizanEventsMapping`.
4. Open the custom endpoint source, tab **Event Hub** -> **Keys**, copy the **Connection string-primary key**
   (it contains `EntityPath=...`). Put it in the git-ignored `.env` as one line:
   `EVENTSTREAM_CONNECTION=Endpoint=sb://...;SharedAccessKeyName=...;SharedAccessKey=...;EntityPath=...`
   Never paste it anywhere else.

## Run

```powershell
# dry run: writes the exact events that would be sent
.\.venv\Scripts\python.exe -m mizan.streaming.replay --data data/generated --inject-velocity-burst `
    --dry-run data/out/stream/events.jsonl
# send to ES_MIZAN (uses EVENTSTREAM_CONNECTION from .env; Event Hubs REST + SAS token, batches under 1 MB)
.\.venv\Scripts\python.exe -m mizan.streaming.replay --data data/generated --inject-velocity-burst --send
```

## Check in KQL

```kusto
MizanEvents | summarize count() by event_kind
VelocityAlerts()                 // 1 row: the injected customer token
MuleRingAlerts()                 // 1 row: the injected mobile token
InvoiceReportingSlaBreaches()    // 2 rows: IR-0000102 (26 h late) and IR-0000103 (rejected, never reported)
ReportingLagByEgs()              // live tile: p95 / max reporting lag per EGS
```

The same thresholds are implemented in `src/mizan/streaming/rules.py`, and `tests/test_streaming.py` proves which
events each rule must catch, so the KQL and the Python reference cannot drift silently.

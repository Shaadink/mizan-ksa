"""Phase 10 streaming: KQL objects in EH_MIZAN, ES_MIZAN topology (custom endpoint -> Eventhouse), connection
string into .env (never printed), then the replay.

    .\\.venv\\Scripts\\python.exe scripts\\fabric_streaming.py setup
    .\\.venv\\Scripts\\python.exe scripts\\fabric_streaming.py replay        # sends with --inject-velocity-burst
    .\\.venv\\Scripts\\python.exe scripts\\fabric_streaming.py check         # counts + rule results from KQL
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from fabric_deploy import API, _req, env  # noqa: E402

from mizan.orchestration.fabric_client import sp_token  # noqa: E402
from mizan.privacy.crypto import load_dotenv  # noqa: E402

TABLE = "MizanEvents"


def fabric_token() -> str:
    return sp_token(env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET"))


def kql_db(token: str) -> dict:
    ws = env("FABRIC_WORKSPACE_ID")
    _, _, raw = _req("GET", f"{API}/workspaces/{ws}/kqlDatabases", token)
    dbs = [d for d in json.loads(raw).get("value", []) if (d.get("properties") or {}).get("parentEventhouseItemId")
           == env("EH_MIZAN_ID")]
    if not dbs:
        raise SystemExit("no KQL database under EH_MIZAN")
    _, _, raw = _req("GET", f"{API}/workspaces/{ws}/kqlDatabases/{dbs[0]['id']}", token)
    return json.loads(raw)


def kusto(uri: str, db: str, csl: str, mgmt: bool = True) -> dict:
    tok = sp_token(env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET"),
                   scope=f"{uri.rstrip('/')}/.default")
    path = "/v1/rest/mgmt" if mgmt else "/v1/rest/query"
    body = json.dumps({"db": db, "csl": csl}).encode()
    st, _, raw = _req("POST", uri.rstrip("/") + path, tok, body, {"Content-Type": "application/json"})
    if st != 200:
        raise RuntimeError(f"KQL {st}: {raw[:600]!r}\n{csl[:200]}")
    return json.loads(raw)


def kql_commands() -> list[str]:
    """Split kql/*.kql into management commands (each starts with a dot at column 0)."""
    cmds = []
    for f in sorted((REPO / "kql").glob("*.kql")):
        text = "\n".join(ln for ln in f.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("//"))
        for block in re.split(r"\n(?=\.)", "\n" + text):
            if block.strip():
                cmds.append(block.strip())
    return cmds


def eventstream_definition(db: dict) -> dict:
    ws = env("FABRIC_WORKSPACE_ID")
    return {
        "compatibilityLevel": "1.0",
        "sources": [{"name": "mizan-replay", "type": "CustomEndpoint", "properties": {}}],
        "destinations": [{"name": "eh-mizan", "type": "Eventhouse",
                          "properties": {"dataIngestionMode": "ProcessedIngestion", "workspaceId": ws,
                                         "itemId": db["id"], "databaseName": db["displayName"], "tableName": TABLE,
                                         "inputSerialization": {"type": "Json", "properties": {"encoding": "UTF8"}}},
                          "inputNodes": [{"name": "ES_MIZAN-stream"}]}],
        "streams": [{"name": "ES_MIZAN-stream", "type": "DefaultStream", "properties": {},
                     "inputNodes": [{"name": "mizan-replay"}]}],
        "operators": []}


def set_env(key: str, value: str) -> None:
    p = REPO / ".env"
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.startswith(key + "=")]
    p.write_text("\n".join([*lines, f"{key}={value}"]) + "\n", encoding="utf-8", newline="\n")


def setup() -> None:
    token = fabric_token()
    db = kql_db(token)
    uri, name = db["properties"]["queryServiceUri"], db["displayName"]
    for c in kql_commands():
        kusto(uri, name, c)
    print(f"KQL: {len(kql_commands())} commands applied in {name}")
    ws, es = env("FABRIC_WORKSPACE_ID"), env("ES_MIZAN_ID")
    part = {"path": "eventstream.json", "payloadType": "InlineBase64",
            "payload": base64.b64encode(json.dumps(eventstream_definition(db)).encode()).decode()}
    st, headers, raw = _req("POST", f"{API}/workspaces/{ws}/eventstreams/{es}/updateDefinition", token,
                            json.dumps({"definition": {"parts": [part]}}).encode(),
                            {"Content-Type": "application/json"})
    if st == 202:
        loc = headers.get("Location")
        for _ in range(60):
            time.sleep(5)
            _, _, r2 = _req("GET", loc, token)
            status = json.loads(r2 or b"{}").get("status")
            if status in ("Succeeded", "Failed"):
                if status == "Failed":
                    raise RuntimeError(r2[:600])
                break
    elif st not in (200, 201):
        raise RuntimeError(f"eventstream definition {st}: {raw[:600]!r}")
    print("ES_MIZAN topology: custom endpoint -> EH_MIZAN." + TABLE)
    fetch_connection(token)


def fetch_connection(token: str) -> None:
    ws, es = env("FABRIC_WORKSPACE_ID"), env("ES_MIZAN_ID")
    for _ in range(30):                          # the endpoint becomes available shortly after publishing
        st, _, raw = _req("GET", f"{API}/workspaces/{ws}/eventstreams/{es}/topology", token)
        src = next((s for s in json.loads(raw or b"{}").get("sources", []) if s.get("type") == "CustomEndpoint"),
                   None) if st == 200 else None
        if src and src.get("status") in ("Running", None, "Active"):
            st2, _, raw2 = _req("GET", f"{API}/workspaces/{ws}/eventstreams/{es}/sources/{src['id']}/connection",
                                token)
            if st2 == 200:
                conn = json.loads(raw2)
                cs = (conn.get("accessKeys") or {}).get("primaryConnectionString")
                if cs:
                    if "EntityPath=" not in cs:
                        cs += f";EntityPath={conn['eventHubName']}"
                    set_env("EVENTSTREAM_CONNECTION", cs)
                    print("EVENTSTREAM_CONNECTION written to .env (not shown)")
                    return
        time.sleep(10)
    raise SystemExit("custom endpoint connection not available yet; re-run setup in a minute")


def check() -> None:
    token = fabric_token()
    db = kql_db(token)
    uri, name = db["properties"]["queryServiceUri"], db["displayName"]
    for q in (f"{TABLE} | summarize n = count() by event_kind | order by event_kind asc",
              "VelocityAlerts() | count", "MuleRingAlerts() | count", "InvoiceReportingSlaBreaches() | count"):
        res = kusto(uri, name, q, mgmt=False)
        rows = res["Tables"][0]["Rows"]
        print(f"{q[:60]:<62} -> {rows}")


def main() -> None:
    load_dotenv()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"
    if cmd == "setup":
        setup()
    elif cmd == "replay":
        from mizan.privacy.crypto import Keys
        from mizan.streaming.replay import build_events, send
        events = build_events(REPO / "data" / "generated", Keys.from_env().hmac_key, inject_burst=True)
        print(f"sent {send(events, env('EVENTSTREAM_CONNECTION'))} events to ES_MIZAN")
    elif cmd == "conn":
        fetch_connection(fabric_token())
    elif cmd == "check":
        check()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as e:
        raise SystemExit(f"network error: {e}") from e

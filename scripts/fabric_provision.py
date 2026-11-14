"""Provision the MIZAN Fabric workspace through the Fabric REST API (idempotent: reuses items that exist).

    .\\.venv\\Scripts\\python.exe scripts\\fabric_provision.py
Uses the Azure CLI profile in %USERPROFILE%\\.azure-fabric (signed in as the Fabric trial owner). Writes item ids,
never secrets, to the git-ignored .env.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
API = "https://api.fabric.microsoft.com/v1"
REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
WORKSPACE = "mizan-ksa-dev"


def token() -> str:
    profile = os.environ.get("MIZAN_AZ_PROFILE", ".azure-fabric")      # which signed-in Fabric identity to use
    env = {**os.environ, "AZURE_CONFIG_DIR": str(Path.home() / profile)}
    cmd = [AZ, "account", "get-access-token", "--resource", "https://api.fabric.microsoft.com", "--query",
           "accessToken", "-o", "tsv"]
    out = subprocess.run(cmd, capture_output=True, text=True, env=env, check=True)  # noqa: S603 (fixed argv)
    return out.stdout.strip()


TOKEN = None


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict, dict]:
    url = path if path.startswith("https://") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={  # noqa: S310 (fixed https API)
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (fixed https API)
            raw = r.read()
            return r.status, dict(r.headers), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, dict(e.headers), json.loads(raw)
        except ValueError:
            return e.code, dict(e.headers), {"raw": raw[:300].decode("utf-8", "replace")}


def wait(headers: dict) -> dict:
    """Follow a long-running operation (202 + Location) to its result."""
    loc = headers.get("Location") or headers.get("location")
    while True:
        time.sleep(int(headers.get("Retry-After", 3) or 3))
        st, headers, body = call("GET", loc)
        if body.get("status") in ("Succeeded", "Failed") or (st == 200 and "status" not in body):
            if body.get("status") == "Failed":
                raise RuntimeError(f"operation failed: {body}")
            st2, _, result = call("GET", loc.rstrip("/") + "/result")
            return result if st2 == 200 else body


def ensure_item(ws: str, kind: str, name: str, payload: dict | None = None) -> dict:
    st, _, body = call("GET", f"/workspaces/{ws}/{kind}")
    for it in body.get("value", []):
        if it["displayName"] == name:
            print(f"  {kind[:-1]:<12} {name:<10} exists   {it['id']}")
            return it
    req = {"displayName": name, **({"creationPayload": payload} if payload else {})}
    st, headers, body = call("POST", f"/workspaces/{ws}/{kind}", req)
    if st == 202:
        body = wait(headers)
    elif st not in (200, 201):
        raise RuntimeError(f"create {kind} {name} failed ({st}): {body}")
    print(f"  {kind[:-1]:<12} {name:<10} created  {body.get('id')}")
    return body


def set_env(values: dict[str, str]) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    keep = [ln for ln in lines if ln.split("=", 1)[0] not in values]
    keep += [f"{k}={v}" for k, v in values.items()]
    ENV.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    global TOKEN
    TOKEN = token()
    st, _, caps = call("GET", "/capacities")
    active = [c for c in caps.get("value", []) if c.get("state") == "Active"]
    if not active:
        raise SystemExit(f"No active Fabric capacity visible ({st}): start the Fabric trial first. {caps}")
    # Fabric capacities have F... SKUs (F2..F2048, trials FT1/FTL64); PP3 = Power BI Premium Per User, no Fabric items.
    # Prefer a Fabric SKU, then UAE North (closest to KSA), then the newest trial.
    cap = sorted(active, key=lambda c: (not str(c.get("sku", "")).startswith("F"), c.get("region") != "UAE North",
                                        [-ord(ch) for ch in c["displayName"]]))[0]
    print(f"capacity: {cap['displayName']} sku={cap.get('sku')} region={cap.get('region')}")

    st, _, wss = call("GET", "/workspaces")
    ws = next((w for w in wss.get("value", []) if w["displayName"] == WORKSPACE), None)
    if ws is None:
        st, _, ws = call("POST", "/workspaces", {"displayName": WORKSPACE, "capacityId": cap["id"],
                                                 "description": "MIZAN-KSA dev workspace (Fabric trial)"})
        if st not in (200, 201):
            raise SystemExit(f"workspace create failed ({st}): {ws}")
        print(f"workspace {WORKSPACE} created {ws['id']}")
    else:
        if ws.get("capacityId") != cap["id"]:
            call("POST", f"/workspaces/{ws['id']}/assignToCapacity", {"capacityId": cap["id"]})
        print(f"workspace {WORKSPACE} exists {ws['id']}")
    wid = ws["id"]

    lh = ensure_item(wid, "lakehouses", "LH_MIZAN", {"enableSchemas": True})
    wh = ensure_item(wid, "warehouses", "WH_MIZAN")
    eh = ensure_item(wid, "eventhouses", "EH_MIZAN")
    es = ensure_item(wid, "eventstreams", "ES_MIZAN")

    _, _, whd = call("GET", f"/workspaces/{wid}/warehouses/{wh['id']}")
    _, _, lhd = call("GET", f"/workspaces/{wid}/lakehouses/{lh['id']}")
    _, _, ehd = call("GET", f"/workspaces/{wid}/eventhouses/{eh['id']}")
    sql = (whd.get("properties") or {}).get("connectionString", "")
    props = lhd.get("properties") or {}
    set_env({"FABRIC_TENANT_ID": cap.get("tenantId", "") or os.environ.get("FABRIC_TENANT_ID", ""),
             "FABRIC_CAPACITY_ID": cap["id"], "FABRIC_WORKSPACE_ID": wid, "LH_MIZAN_ID": lh["id"],
             "WH_MIZAN_ID": wh["id"], "EH_MIZAN_ID": eh["id"], "ES_MIZAN_ID": es["id"],
             "FABRIC_SQL_ENDPOINT": sql,
             "LH_MIZAN_ONELAKE": props.get("oneLakeTablesPath", ""),
             "EH_MIZAN_QUERY_URI": (ehd.get("properties") or {}).get("queryServiceUri", "")})
    print(f"schemas enabled on LH_MIZAN: {'defaultSchema' in props}")
    print(f"WH_MIZAN SQL endpoint: {sql or '(pending)'}")
    print("ids written to .env")


if __name__ == "__main__":
    main()

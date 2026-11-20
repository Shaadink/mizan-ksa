"""Stand up AF_MIZAN, the Apache Airflow job inside Fabric, over REST with the service principal from .env.

    .\\.venv\\Scripts\\python.exe scripts\\fabric_airflow.py status     # what exists right now
    .\\.venv\\Scripts\\python.exe scripts\\fabric_airflow.py create     # the AF_MIZAN item (idempotent)
    .\\.venv\\Scripts\\python.exe scripts\\fabric_airflow.py push       # upload dags/mizan_fabric_daily.py
    .\\.venv\\Scripts\\python.exe scripts\\fabric_airflow.py settings   # the five non-secret ids
    .\\.venv\\Scripts\\python.exe scripts\\fabric_airflow.py start      # start the Airflow environment
    .\\.venv\\Scripts\\python.exe scripts\\fabric_airflow.py all        # the four above, in order

WHAT THIS SCRIPT DELIBERATELY DOES NOT SEND: the client secret. Fabric's environment-settings API stores
values in plain text and hands them back in full on a GET, so anyone with workspace access could read a
secret put there. `dags/mizan_fabric_daily.py` asks Airflow for a Variable first and only falls back to an
environment variable, so the five identifiers travel through this script and the one secret is pasted once,
by hand, into Airflow's own Variables page, where Airflow masks any name containing "secret". One manual
paste is the price of not writing a credential somewhere it can be read back.

Git sync is not used. Microsoft documents no REST surface for configuring it, and uploading the DAG from the
repository keeps the deployment reproducible from one command without giving Fabric a GitHub credential.
`push` therefore uploads the exact file in `dags/`, and the file management API it uses is still in beta --
every such call carries `?beta=true` and may change under us.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mizan.orchestration.fabric_client import sp_token  # noqa: E402
from mizan.privacy.crypto import load_dotenv  # noqa: E402

API = "https://api.fabric.microsoft.com/v1"
JOB_NAME = "AF_MIZAN"
NOTEBOOK_NAME = "nb_mizan_step"
DAG_LOCAL = REPO / "dags" / "mizan_fabric_daily.py"
DAG_REMOTE = "dags/mizan_fabric_daily.py"
ENV_FILE = REPO / ".env"

# Only identifiers. The DAG reads mizan_client_secret from an Airflow Variable, never from here.
SETTING_KEYS = {"MIZAN_TENANT_ID": "FABRIC_TENANT_ID", "MIZAN_CLIENT_ID": "FABRIC_CLIENT_ID",
                "MIZAN_WORKSPACE_ID": "FABRIC_WORKSPACE_ID", "MIZAN_LAKEHOUSE_ID": "LH_MIZAN_ID"}


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} missing from .env (run scripts/fabric_provision.py first)")
    return value


def req(method: str, url: str, token: str, data: bytes | None = None,
        content_type: str | None = None, timeout: int = 180) -> tuple[int, dict, object]:
    if not url.startswith("https://"):
        raise ValueError(url)
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310 (https)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:  # noqa: S310 (https checked)
            raw = r.read()
            return r.status, dict(r.headers), (json.loads(raw) if raw[:1] in (b"{", b"[") else
                                               raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, dict(e.headers), (json.loads(raw) if raw[:1] in (b"{", b"[") else
                                         raw.decode("utf-8", "replace")[:600])


def follow(headers: dict, token: str) -> dict:
    """Follow a 202 long-running operation to its result."""
    location = headers.get("Location") or headers.get("location")
    for _ in range(60):
        time.sleep(int(headers.get("Retry-After", 5) or 5))
        _, headers, body = req("GET", location, token)
        if isinstance(body, dict) and body.get("status") == "Failed":
            raise SystemExit(f"operation failed: {body}")
        if isinstance(body, dict) and body.get("status") == "Succeeded":
            ok, _, result = req("GET", location.rstrip("/") + "/result", token)
            return result if ok == 200 and isinstance(result, dict) else body
    raise SystemExit("operation did not finish in time")


def set_env_value(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    kept = [ln for ln in lines if ln.split("=", 1)[0].strip() != key]
    ENV_FILE.write_text("\n".join([*kept, f"{key}={value}"]) + "\n", encoding="utf-8")


def item_named(token: str, kind: str, name: str) -> dict | None:
    status, _, body = req("GET", f"{API}/workspaces/{env('FABRIC_WORKSPACE_ID')}/items", token)
    if status != 200:
        raise SystemExit(f"cannot list workspace items ({status}): {body}")
    for item in body.get("value", []):
        if item["type"] == kind and item["displayName"] == name:
            return item
    return None


def job_id(token: str) -> str:
    cached = os.environ.get("AF_MIZAN_ID")
    if cached:
        return cached
    item = item_named(token, "ApacheAirflowJob", JOB_NAME)
    if not item:
        raise SystemExit(f"{JOB_NAME} does not exist yet -- run `fabric_airflow.py create` first")
    return item["id"]


def job_url(token: str, suffix: str = "", beta: bool = False) -> str:
    url = f"{API}/workspaces/{env('FABRIC_WORKSPACE_ID')}/apacheAirflowJobs/{job_id(token)}{suffix}"
    return url + ("?beta=true" if beta else "")


# ----------------------------------------------------------------------------- commands

def create(token: str) -> None:
    existing = item_named(token, "ApacheAirflowJob", JOB_NAME)
    if existing:
        print(f"  job        {JOB_NAME:<10} exists   {existing['id']}")
        set_env_value("AF_MIZAN_ID", existing["id"])
        return
    status, headers, body = req(
        "POST", f"{API}/workspaces/{env('FABRIC_WORKSPACE_ID')}/apacheAirflowJobs", token,
        data=json.dumps({"displayName": JOB_NAME,
                         "description": "MIZAN-KSA daily lakehouse pipeline (dags/mizan_fabric_daily.py)"
                         }).encode(), content_type="application/json")
    if status == 202:
        body = follow(headers, token)
    elif status not in (200, 201):
        raise SystemExit(f"create {JOB_NAME} failed ({status}): {body}")
    print(f"  job        {JOB_NAME:<10} created  {body.get('id')}")
    set_env_value("AF_MIZAN_ID", body["id"])


def push(token: str) -> None:
    path = urllib.parse.quote(DAG_REMOTE, safe="")
    status, _, body = req("PUT", job_url(token, f"/files/{path}", beta=True), token,
                          data=DAG_LOCAL.read_bytes(), content_type="application/octet-stream")
    if status not in (200, 201):
        raise SystemExit(f"upload {DAG_REMOTE} failed ({status}): {body}")
    print(f"  dag        {DAG_REMOTE:<30} {DAG_LOCAL.stat().st_size:,} bytes uploaded")


def settings(token: str) -> None:
    # updateSettings replaces the whole set, so every value this job needs goes in one call.
    values = {name: env(source) for name, source in SETTING_KEYS.items()}
    notebook = item_named(token, "Notebook", NOTEBOOK_NAME)
    if not notebook:
        raise SystemExit(f"{NOTEBOOK_NAME} not found -- run `fabric_deploy.py notebook` first")
    values["MIZAN_NOTEBOOK_ID"] = notebook["id"]
    status, _, body = req(
        "POST", job_url(token, "/environment/updateSettings", beta=True), token,
        data=json.dumps({"environmentVariables": [{"name": k, "value": v} for k, v in values.items()]}).encode(),
        content_type="application/json")
    if status not in (200, 202):
        # Measured 2026-11-20 on FTL64/UAE North: this endpoint answers 401 "does not have Write permissions"
        # to the same service principal that had just created the item and uploaded a DAG file through the
        # sibling beta API, and its GET answers 500. The capability is documented but not usable here, so say
        # what to do instead rather than failing with an API error nobody can act on.
        print(f"  environment settings refused ({status}): {body}")
        print("  Fabric's environment-settings API is in beta and is not answering for this service")
        print("  principal, so set these in the Airflow UI instead (Admin > Variables), lower-cased:")
        for name in values:
            print(f"      {name.lower()}")
        print("      mizan_client_secret      <- FABRIC_CLIENT_SECRET from .env; Airflow masks it")
        raise SystemExit(1)
    for name in values:
        print(f"  setting    {name:<22} set")
    print("  setting    mizan_client_secret    NOT SENT -- paste it into Airflow > Admin > Variables yourself")


def start(token: str) -> None:
    status, _, body = req("POST", job_url(token, "/environment/start", beta=True), token)
    print(f"  environment start requested ({status}) {body if status >= 400 else ''}".rstrip())


def status_cmd(token: str) -> None:
    item = item_named(token, "ApacheAirflowJob", JOB_NAME)
    if not item:
        print(f"  job        {JOB_NAME:<10} does not exist")
        return
    print(f"  job        {JOB_NAME:<10} {item['id']}")
    code, _, body = req("GET", job_url(token, "/environment", beta=True), token)
    print(f"  environment            {body.get('status') if isinstance(body, dict) else body} (HTTP {code})")
    code, _, body = req("GET", job_url(token, "/files", beta=True) + "&rootPath=dags", token)
    files = body.get("value", []) if isinstance(body, dict) else []
    print(f"  files in dags/         {[f['filePath'] for f in files] or 'none'} (HTTP {code})")
    code, _, body = req("GET", job_url(token, "/environment/settings", beta=True), token)
    names = [v["name"] for v in body.get("environmentVariables", [])] if isinstance(body, dict) else []
    print(f"  environment variables  {names or 'none'} (HTTP {code})")


COMMANDS = {"create": create, "push": push, "settings": settings, "start": start, "status": status_cmd}


def main() -> None:
    load_dotenv()
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    token = sp_token(env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET"))
    for name in (("create", "push", "settings", "start") if command == "all" else (command,)):
        if name not in COMMANDS:
            raise SystemExit(__doc__)
        print(f"=== {name} ===")
        COMMANDS[name](token)


if __name__ == "__main__":
    main()

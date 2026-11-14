"""Deploy and run MIZAN on Fabric (Phase 10), entirely through REST with the service principal from .env.

    .\\.venv\\Scripts\\python.exe scripts\\fabric_deploy.py upload          # code + policies + data + dev keys
    .\\.venv\\Scripts\\python.exe scripts\\fabric_deploy.py notebook        # create / update nb_mizan_step
    .\\.venv\\Scripts\\python.exe scripts\\fabric_deploy.py run [step ...]  # run steps as Fabric jobs (default: all)

OneLake is ADLS Gen2-compatible: files go to LH_MIZAN/Files via the DFS endpoint. The notebook adds the uploaded
source to sys.path, reads the dev keys from the workspace-private Files/_secrets (production: Azure Key Vault),
points staging at Files/_staging and runs mizan.spark.pipeline.run_step.
"""

from __future__ import annotations

import base64
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

from mizan.orchestration.fabric_client import FabricClient, sp_token  # noqa: E402
from mizan.privacy.crypto import load_dotenv  # noqa: E402

API = "https://api.fabric.microsoft.com/v1"
DFS = "https://onelake.dfs.fabric.microsoft.com"
NOTEBOOK = "nb_mizan_step"
STEPS = ("bronze_land", "silver_build", "mdm_resolve", "zatca_chain", "restore_guard", "ai_index", "ndmo_catalog")


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"{name} missing from .env (run scripts/fabric_provision.py first)")
    return v


def _req(method: str, url: str, token: str, data: bytes | None = None, headers: dict | None = None):
    if not url.startswith("https://"):
        raise ValueError(url)
    h = {"Authorization": f"Bearer {token}", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=h)  # noqa: S310 (https checked)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
            raw = r.read()
            return r.status, dict(r.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


# ----------------------------------------------------------------------------- OneLake upload

def onelake_put(token: str, rel: str, content: bytes) -> None:
    ws, lh = env("FABRIC_WORKSPACE_ID"), env("LH_MIZAN_ID")
    url = f"{DFS}/{ws}/{lh}/Files/{urllib.parse.quote(rel)}"
    st, _, body = _req("PUT", url + "?resource=file&overwrite=true", token, b"", {"Content-Length": "0"})
    if st not in (200, 201):
        raise RuntimeError(f"create {rel}: {st} {body[:300]!r}")
    pos = 0
    chunk = 4 * 1024 * 1024
    while pos < len(content) or pos == 0:
        part = content[pos:pos + chunk]
        st, _, body = _req("PATCH", f"{url}?action=append&position={pos}", token, part,
                           {"Content-Length": str(len(part)), "Content-Type": "application/octet-stream"})
        if st not in (200, 202):
            raise RuntimeError(f"append {rel}: {st} {body[:300]!r}")
        pos += len(part)
        if not part:
            break
    st, _, body = _req("PATCH", f"{url}?action=flush&position={len(content)}", token, b"", {"Content-Length": "0"})
    if st not in (200, 201):
        raise RuntimeError(f"flush {rel}: {st} {body[:300]!r}")


def upload(token: str) -> None:
    n = 0
    for src, dest in ((REPO / "src" / "mizan", "code/src/mizan"), (REPO / "docs" / "policies", "code/docs/policies"),
                      (REPO / "data" / "generated", "generated")):
        for f in sorted(src.rglob("*")):
            if f.is_dir() or "__pycache__" in f.parts or f.suffix == ".pyc":
                continue
            onelake_put(token, f"{dest}/{f.relative_to(src).as_posix()}", f.read_bytes())
            n += 1
    keys = "".join(f"{k}={os.environ[k]}\n" for k in ("MIZAN_HMAC_KEY_B64", "MIZAN_KEK_B64"))
    onelake_put(token, "_secrets/mizan_keys.env", keys.encode())
    print(f"uploaded {n} files + dev keys to LH_MIZAN/Files")


# ----------------------------------------------------------------------------- notebook

NOTEBOOK_CODE = '''# PARAMETERS
step = "all"
include_demo = "false"
ws_id = ""
lh_id = ""

# CELL
import json, os, sys, traceback
from pathlib import Path
ROOT = "/lakehouse/default/Files"
os.makedirs(f"{ROOT}/_logs", exist_ok=True)
log_path = f"{ROOT}/_logs/{step.replace(',', '_')}.txt"
results = {}
try:
    import importlib.util, subprocess
    missing = [p for p in ("lxml", "cryptography") if importlib.util.find_spec(p) is None]
    if missing:                       # driver-only deps (no Python UDFs, so executors never import them)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])
    for line in open(f"{ROOT}/_secrets/mizan_keys.env", encoding="utf-8"):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            os.environ[k] = v
    os.environ["MIZAN_ONELAKE_ROOT"] = f"abfss://{ws_id}@onelake.dfs.fabric.microsoft.com/{lh_id}"
    os.environ["MIZAN_FILES_MOUNT"] = ROOT
    os.environ["MIZAN_FILES_URI"] = f"abfss://{ws_id}@onelake.dfs.fabric.microsoft.com/{lh_id}/Files"
    os.environ["MIZAN_STAGING_DIR"] = f"{ROOT}/_staging"
    os.environ["MIZAN_STAGING_SPARK_PREFIX"] = f"abfss://{ws_id}@onelake.dfs.fabric.microsoft.com/{lh_id}/Files/_staging"
    sys.path.insert(0, f"{ROOT}/code/src")
    for m in [m for m in sys.modules if m == "mizan" or m.startswith("mizan.")]:
        del sys.modules[m]
    from mizan.privacy.crypto import Keys
    from mizan.spark.lake import Lake
    from mizan.spark.pipeline import STEPS, run_step
    from mizan.spark.session import TableLocator, get_spark
    lake = Lake(get_spark("fabric"), TableLocator("fabric"))
    todo = [s for s in STEPS if s != "restore_guard"] if step == "all" else step.split(",")
    results = {}
    for s in todo:
        out = run_step(s, lake, Keys.from_env(), Path(f"{ROOT}/generated"), include_demo=include_demo == "true")
        results[s] = out if s != "bronze_land" else [{k: r[k] for k in ("source_file", "status", "landed_rows",
                                                                         "sha_match")} for r in out]
        print(s, json.dumps(results[s], default=str)[:1500])

    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("OK " + json.dumps(results, default=str)[:200000])
except Exception:
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("ERROR " + traceback.format_exc())
    raise
notebookutils.notebook.exit(json.dumps(results, default=str)[:60000])
'''


def notebook_content(ws: str, lh: str) -> str:
    meta = {"kernel_info": {"name": "synapse_pyspark"},
            "dependencies": {"lakehouse": {"default_lakehouse": lh, "default_lakehouse_name": "LH_MIZAN",
                                           "default_lakehouse_workspace_id": ws}}}
    cell_meta = '# METADATA ********************\n\n# META {\n# META   "language": "python",\n' \
                '# META   "language_group": "synapse_pyspark"\n# META }\n'
    out = ["# Fabric notebook source\n", "# METADATA ********************\n",
           "\n".join("# META " + ln for ln in json.dumps(meta, indent=2).splitlines()) + "\n"]
    params, body = NOTEBOOK_CODE.split("# CELL\n")
    out.append("# PARAMETERS CELL ********************\n\n" + params.replace("# PARAMETERS\n", "") + "\n" + cell_meta)
    out.append("# CELL ********************\n\n" + body + "\n" + cell_meta)
    return "\n".join(out)


def ensure_notebook(token: str) -> str:
    ws, lh = env("FABRIC_WORKSPACE_ID"), env("LH_MIZAN_ID")
    part = {"path": "notebook-content.py", "payloadType": "InlineBase64",
            "payload": base64.b64encode(notebook_content(ws, lh).encode()).decode()}
    st, _, raw = _req("GET", f"{API}/workspaces/{ws}/notebooks", token)
    existing = next((n for n in json.loads(raw).get("value", []) if n["displayName"] == NOTEBOOK), None)
    if existing:
        url = f"{API}/workspaces/{ws}/notebooks/{existing['id']}/updateDefinition"
        body = {"definition": {"format": "fabricGitSource", "parts": [part]}}
        nid = existing["id"]
    else:
        url = f"{API}/workspaces/{ws}/notebooks"
        body = {"displayName": NOTEBOOK, "definition": {"format": "fabricGitSource", "parts": [part]}}
        nid = None
    st, headers, raw = _req("POST", url, token, json.dumps(body).encode(), {"Content-Type": "application/json"})
    if st == 202:
        loc = headers.get("Location")
        while True:
            time.sleep(3)
            _, _, r2 = _req("GET", loc, token)
            status = json.loads(r2 or b"{}").get("status")
            if status in ("Succeeded", "Failed"):
                if status == "Failed":
                    raise RuntimeError(r2[:500])
                break
    elif st not in (200, 201):
        raise RuntimeError(f"notebook {st}: {raw[:500]!r}")
    if nid is None:
        _, _, raw = _req("GET", f"{API}/workspaces/{ws}/notebooks", token)
        nid = next(n["id"] for n in json.loads(raw)["value"] if n["displayName"] == NOTEBOOK)
    print(f"notebook {NOTEBOOK} ready: {nid}")
    return nid


def read_log(step: str) -> str:
    tok = sp_token(env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET"),
                   scope="https://storage.azure.com/.default")
    ws, lh = env("FABRIC_WORKSPACE_ID"), env("LH_MIZAN_ID")
    st, _, raw = _req("GET", f"{DFS}/{ws}/{lh}/Files/_logs/{step.replace(',', '_')}.txt", tok)
    return raw.decode("utf-8", "replace") if st == 200 else f"(no log: HTTP {st})"


def run(steps: list[str]) -> None:
    ws, lh = env("FABRIC_WORKSPACE_ID"), env("LH_MIZAN_ID")
    token = sp_token(env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET"))
    nid = ensure_notebook(token)
    client = FabricClient(ws, {s: nid for s in STEPS}, token)
    for s in steps:
        t0 = time.time()
        r = client.run_job(s, {"step": s, "ws_id": ws, "lh_id": lh}, poll_seconds=20, timeout_s=5400)
        print(f"{s:<14} {r.status:<10} {time.time() - t0:7.0f}s  {r.failure or ''}")
        log = read_log(s)
        print("   ", log.splitlines()[0] if log else "", "|", log[-3000:] if r.status != "Completed" else "")
        if r.status != "Completed":
            raise SystemExit(f"step {s} failed: {r.failure}")


def main() -> None:
    load_dotenv()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "upload":
        tok = sp_token(env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET"),
                       scope="https://storage.azure.com/.default")
        upload(tok)
    elif cmd == "notebook":
        ensure_notebook(sp_token(env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET")))
    elif cmd == "run":
        run(sys.argv[2:] or [s for s in STEPS if s != "restore_guard"])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()

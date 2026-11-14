"""Fabric job client for the Airflow DAG: REST API with a service principal (real), or a deterministic mock (Docker).

Real mode: POST /v1/workspaces/{ws}/items/{item}/jobs/instances?jobType=RunNotebook -> 202 + Location; poll the
Location until Completed / Failed / Cancelled / Deduped. Credentials come only from the environment (.env).
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

FABRIC_API = "https://api.fabric.microsoft.com/v1"
TERMINAL = ("Completed", "Failed", "Cancelled", "Deduped")


def _http(method: str, url: str, *, token: str | None = None, body: dict | bytes | None = None,
          form: dict | None = None, timeout: int = 60) -> tuple[int, dict, dict]:
    if not url.startswith("https://"):
        raise ValueError("Fabric and Entra endpoints are HTTPS only")
    headers = {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 (https checked)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (https checked)
            raw = r.read()
            return r.status, dict(r.headers), (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, dict(e.headers), (json.loads(raw) if raw and raw[:1] in b"{[" else {"raw": raw[:500].decode(
            "utf-8", "replace")})


def sp_token(tenant: str, client_id: str, secret: str, scope: str = "https://api.fabric.microsoft.com/.default") -> str:
    status, _, body = _http("POST", f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                            form={"grant_type": "client_credentials", "client_id": client_id,
                                  "client_secret": secret, "scope": scope})
    if status != 200:
        raise PermissionError(f"token request failed ({status}): {body.get('error_description', body)}")
    return body["access_token"]


@dataclass
class JobRun:
    job: str
    instance_id: str
    status: str
    polls: int = 0
    failure: str | None = None


@dataclass
class MockFabricClient:
    """Docker / CI stand-in: same interface, deterministic, can be told to fail a job (for DAG tests)."""
    fail_jobs: set[str] = field(default_factory=set)
    log: list[str] = field(default_factory=list)

    def run_job(self, job: str, params: dict | None = None, poll_seconds: float = 0) -> JobRun:
        self.log.append(job)
        iid = f"mock-{len(self.log):04d}-{job}"
        if job in self.fail_jobs:
            return JobRun(job, iid, "Failed", 2, "injected failure")
        return JobRun(job, iid, "Completed", 2)


@dataclass
class FabricClient:
    workspace_id: str
    items: dict[str, str]                     # job name -> notebook / pipeline item id
    token: str

    @classmethod
    def from_env(cls) -> FabricClient:
        from mizan.privacy.crypto import load_dotenv
        load_dotenv()
        env = os.environ
        items = json.loads(env.get("FABRIC_JOB_ITEMS", "{}"))
        return cls(env["FABRIC_WORKSPACE_ID"], items,
                   sp_token(env["FABRIC_TENANT_ID"], env["FABRIC_CLIENT_ID"], env["FABRIC_CLIENT_SECRET"]))

    def run_job(self, job: str, params: dict | None = None, poll_seconds: float = 15,
                timeout_s: int = 3600) -> JobRun:
        item = self.items[job]
        body = {"executionData": {"parameters": {k: {"value": str(v), "type": "string"}
                                                 for k, v in (params or {}).items()}}} if params else None
        status, headers, resp = _http(
            "POST", f"{FABRIC_API}/workspaces/{self.workspace_id}/items/{item}/jobs/instances?jobType=RunNotebook",
            token=self.token, body=body)
        if status != 202:
            raise RuntimeError(f"{job}: job submit returned {status}: {resp}")
        location = headers.get("Location") or headers.get("location")
        run = JobRun(job, location.rstrip("/").rsplit("/", 1)[-1], "NotStarted")
        deadline = time.time() + timeout_s
        while run.status not in TERMINAL:
            if time.time() > deadline:
                raise TimeoutError(f"{job}: still {run.status} after {timeout_s}s")
            time.sleep(poll_seconds)
            _, _, body = _http("GET", location, token=self.token)
            run.status, run.polls = body.get("status", run.status), run.polls + 1
            run.failure = (body.get("failureReason") or {}).get("message") if body.get("failureReason") else None
        return run


def client(mode: str):
    mode = mode.strip().lower()
    if mode == "mock":
        return MockFabricClient()
    if mode == "fabric":
        return FabricClient.from_env()
    raise ValueError(f"unknown Fabric client mode {mode!r}")

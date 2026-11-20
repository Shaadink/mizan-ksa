"""MIZAN-KSA daily pipeline, orchestrated by the Apache Airflow job inside Microsoft Fabric (AF_MIZAN).

Spec Section 7 says Airflow owns the schedule and Fabric runs the jobs. `airflow/dags/mizan_daily.py` does
that from Docker on the owner's machine; this DAG does it from inside Fabric itself, so the schedule survives
the laptop being closed. The two are deliberately not the same file:

  airflow/dags/mizan_daily.py   Docker. Runs the Fabric jobs AND the freshness gate, the residency gate, the
                                dbt build and OpenLineage -> Marquez, because those need the repo, a mounted
                                lake and a reachable Marquez.
  dags/mizan_fabric_daily.py    Fabric. Runs the six Fabric notebook jobs over the REST API and nothing else.
                                Fabric's Airflow job has no private networking ("private networks and virtual
                                networks aren't supported"), so Marquez on a laptop is unreachable from it,
                                and the repo's `mizan` package is not installed there.

That second constraint is why this file imports nothing but the standard library and Airflow itself. There is
no requirements.txt to install and no wheel to build, so the only way this DAG can fail to start is a syntax
error -- which `tests/test_fabric_airflow_dag.py` catches before it is ever pushed.

Deployment is Git sync from the public repository, so the DAG that runs in Fabric is the file reviewers read.
Fabric syncs the repo to /opt/airflow/git/<repo>/ and reads DAGs from a `dags` folder, which is why this one
sits at the repository root rather than beside its Docker sibling. Setup: docs/FABRIC_AIRFLOW.md.

Credentials come from Airflow Variables, never from this file:
  mizan_tenant_id  mizan_client_id  mizan_client_secret  mizan_workspace_id  mizan_lakehouse_id
  mizan_notebook_id
Airflow masks any variable whose name contains "secret" in the UI and in task logs.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

FABRIC_API = "https://api.fabric.microsoft.com/v1"
LOGIN = "https://login.microsoftonline.com"
TERMINAL = ("Completed", "Failed", "Cancelled", "Deduped")

# The order the pipeline must run in. Silver reads what Bronze landed; the ZATCA chain reads Bronze and the
# control plane; the AI index and the NDMO catalogue read Silver and can run side by side.
CHAIN = ("bronze_land", "silver_build", "mdm_resolve", "zatca_chain")
FAN_OUT = ("ai_index", "ndmo_catalog")
STEP_ORDER = CHAIN + FAN_OUT

# A notebook step that has not finished in this long has not merely been slow: bronze_land, the longest,
# took 714 seconds on the 2026-11-19 run (docs/artifacts/10_fabric_run_evidence.json).
STEP_TIMEOUT_S = 5400


def edges() -> list[tuple[str, str]]:
    """The DAG's dependencies, as pairs, so the shape can be asserted without importing Airflow."""
    out = [(CHAIN[i], CHAIN[i + 1]) for i in range(len(CHAIN) - 1)]
    return out + [(CHAIN[-1], step) for step in FAN_OUT]


def setting(name: str) -> str:
    """An Airflow Variable, or the matching environment variable when Airflow is not present (tests).

    Variables beat environment variables because the Fabric portal is where the owner can rotate the client
    secret without touching the repository, and because Airflow masks `*secret*` in the UI and in logs.
    """
    try:
        from airflow.models import Variable
    except ImportError:
        pass
    else:
        value = Variable.get(name, default_var=None)
        if value:
            return value
    value = os.environ.get(name.upper())
    if not value:
        raise RuntimeError(
            f"missing Airflow Variable {name!r}. Set it under the Airflow UI > Admin > Variables, or export "
            f"{name.upper()} when running outside Fabric. See docs/FABRIC_AIRFLOW.md.")
    return value


def _http(method: str, url: str, *, token: str | None = None, body: dict | None = None,
          form: dict | None = None, timeout: int = 60) -> tuple[int, dict, dict]:
    if not url.startswith("https://"):
        raise ValueError("Fabric and Entra endpoints are HTTPS only")
    headers, data = {}, None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
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
        return e.code, dict(e.headers), (json.loads(raw) if raw and raw[:1] in b"{[" else
                                         {"raw": raw[:500].decode("utf-8", "replace")})


def service_principal_token() -> str:
    status, _, body = _http("POST", f"{LOGIN}/{setting('mizan_tenant_id')}/oauth2/v2.0/token",
                            form={"grant_type": "client_credentials",
                                  "client_id": setting("mizan_client_id"),
                                  "client_secret": setting("mizan_client_secret"),
                                  "scope": "https://api.fabric.microsoft.com/.default"})
    if status != 200:
        # The description can name the app registration but never the secret, so it is safe in a task log.
        raise PermissionError(f"Entra token request failed ({status}): {body.get('error_description', body)}")
    return body["access_token"]


def run_step(step: str, poll_seconds: float = 20, **_ctx) -> dict:
    """Start nb_mizan_step for one step and poll until Fabric says it has reached a terminal state.

    One notebook item runs every step; the `step` parameter chooses which. Submitting returns 202 and a
    Location header, and the run id is the last segment of that URL -- the same contract
    src/mizan/orchestration/fabric_client.py follows, kept here rather than imported because the repo's
    package is not installed in Fabric's Airflow workers.
    """
    token = service_principal_token()
    workspace = setting("mizan_workspace_id")
    item = setting("mizan_notebook_id")
    parameters = {"step": step, "ws_id": workspace, "lh_id": setting("mizan_lakehouse_id")}
    status, headers, resp = _http(
        "POST", f"{FABRIC_API}/workspaces/{workspace}/items/{item}/jobs/instances?jobType=RunNotebook",
        token=token,
        body={"executionData": {"parameters": {k: {"value": v, "type": "string"}
                                               for k, v in parameters.items()}}})
    if status != 202:
        raise RuntimeError(f"{step}: Fabric refused the job submission ({status}): {resp}")
    location = headers.get("Location") or headers.get("location")
    if not location:
        raise RuntimeError(f"{step}: Fabric accepted the job but returned no Location header to poll")

    instance, state, polls, body = location.rstrip("/").rsplit("/", 1)[-1], "NotStarted", 0, {}
    deadline = time.time() + STEP_TIMEOUT_S
    while state not in TERMINAL:
        if time.time() > deadline:
            raise TimeoutError(f"{step}: still {state} after {STEP_TIMEOUT_S}s (run {instance})")
        time.sleep(poll_seconds)
        _, _, body = _http("GET", location, token=token)
        state, polls = body.get("status", state), polls + 1
    if state != "Completed":
        reason = (body.get("failureReason") or {}).get("message") or state
        # Fail loudly: a Failed step that returns normally would let the next one read half-written tables.
        raise RuntimeError(f"{step}: Fabric reported {state} (run {instance}): {reason}")
    return {"step": step, "run_id": instance, "status": state, "polls": polls}


# pytest runs without Airflow installed, and the logic above is the part worth testing, so importing this
# module must not require it.
try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
except ImportError:                        # pragma: no cover - exercised only outside Fabric
    DAG = None

if DAG is not None:                        # pragma: no cover - needs a scheduler, not a unit test
    import pendulum

    with DAG(
        dag_id="mizan_fabric_daily",
        description="MIZAN-KSA Bronze to Gold on Fabric, scheduled by Fabric's own Airflow",
        # 03:00 Asia/Riyadh, not UTC: the business date this pipeline closes is a Riyadh date, and a UTC
        # schedule would start the run inside the previous Riyadh day for three hours of every year.
        start_date=pendulum.datetime(2026, 2, 12, tz="Asia/Riyadh"),
        schedule="0 3 * * *",
        catchup=False,                     # a missed night is re-run deliberately, never back-filled blindly
        max_active_runs=1,                 # Bronze is append-only; two concurrent runs would land twice
        tags=["mizan", "fabric", "ksa"],
        doc_md=__doc__,
    ) as dag:
        tasks = {step: PythonOperator(task_id=step, python_callable=run_step, op_kwargs={"step": step},
                                      retries=0)   # a step that failed is re-run by hand, after reading why
                 for step in STEP_ORDER}
        for upstream, downstream in edges():
            tasks[upstream] >> tasks[downstream]

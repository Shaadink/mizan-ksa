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

Deployment is `scripts/fabric_airflow.py push`, which uploads this exact file to AF_MIZAN over the Fabric
REST API, so the DAG that runs in Fabric is the file reviewers read. Git sync was the first plan and was
dropped: Microsoft documents no REST surface for configuring it, and an upload from the repository keeps the
whole deployment to one command without giving Fabric a GitHub credential. Fabric reads DAGs from a `dags`
folder either way, which is why this one sits at the repository root rather than beside its Docker sibling.
Setup: docs/FABRIC_AIRFLOW.md.

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
DBT_TASK = "dbt_build_gold"

# A notebook step that has not finished in this long has not merely been slow: bronze_land, the longest,
# took 714 seconds on the 2026-11-19 run (docs/artifacts/10_fabric_run_evidence.json).
STEP_TIMEOUT_S = 5400
DBT_TIMEOUT_S = 3600

# Uploaded beside this file by `scripts/fabric_airflow.py push-dbt`. dbt writes its target and logs under
# /tmp because the synced dags folder is not a safe place to assume is writable.
DBT_PROJECT_DIR = "/opt/airflow/dags/dbt"
DBT_SCRATCH = "/tmp/dbt-mizan"                                            # noqa: S108 (the worker's own tmp)


def edges() -> list[tuple[str, str]]:
    """The DAG's dependencies, as pairs, so the shape can be asserted without importing Airflow."""
    out = [(CHAIN[i], CHAIN[i + 1]) for i in range(len(CHAIN) - 1)]
    out += [(CHAIN[-1], step) for step in FAN_OUT]
    # Gold is built last and only after everything it reads exists. The fan-out pair feed it too: the NDMO
    # catalogue is a source of mart_ndmo_scorecard, so a dbt build that started earlier would read a stale one.
    return out + [(step, DBT_TASK) for step in FAN_OUT]


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


def dbt_build(**_ctx) -> dict:
    """Build and test Gold on WH_MIZAN with dbt, as the last step of the run.

    Shelled out rather than imported, which is the whole trick: this module still imports nothing but the
    standard library and Airflow, so a missing or broken dbt cannot stop the DAG from being parsed -- it
    fails one task, with a readable reason, and the five Fabric steps before it keep their result.

    dbt-fabric is not in the worker by default. It is added in the portal under **Apache Airflow
    requirements** (the REST route for requirements is refused for our service principal, see HONESTY row
    31), and it needs `ODBC Driver 18 for SQL Server` present in the image -- which is the part Microsoft
    does not promise. If that driver is missing this task is where it shows, and the project keeps running
    dbt from the developer machine as it did before.

    Credentials reach dbt the way dbt expects: profiles.yml is committed with `env_var(...)` and no secrets,
    so the values go into the subprocess environment here and never into a file.
    """
    # stdlib, imported late so the DAG still parses in an environment that has not run it
    import subprocess

    env = {**os.environ,
           "MIZAN_DBT_TARGET": "fabric",
           "FABRIC_SQL_ENDPOINT": setting("mizan_sql_endpoint"),
           "FABRIC_TENANT_ID": setting("mizan_tenant_id"),
           "FABRIC_CLIENT_ID": setting("mizan_client_id"),
           "FABRIC_CLIENT_SECRET": setting("mizan_client_secret"),
           "DBT_LOG_PATH": f"{DBT_SCRATCH}/logs"}
    cmd = ["dbt", "build", "--target", "fabric", "--project-dir", DBT_PROJECT_DIR,
           "--profiles-dir", DBT_PROJECT_DIR, "--target-path", f"{DBT_SCRATCH}/target"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True,  # noqa: S603 (fixed argv, no shell)
                              timeout=DBT_TIMEOUT_S, env=env, check=False)
    except FileNotFoundError:
        raise RuntimeError(
            "dbt is not installed in this Airflow worker. Add dbt-fabric under Apache Airflow requirements "
            "in the AF_MIZAN portal, then restart the job. See docs/FABRIC_AIRFLOW.md.") from None
    out = done.stdout or ""
    print(out[-8000:])                                  # the build summary belongs in the task log
    if done.returncode:
        tail = "\n".join([ln for ln in out.splitlines() if " Failure " in ln or "Error" in ln][-20:])
        raise RuntimeError(f"dbt build failed (exit {done.returncode}). {tail or (done.stderr or '')[-2000:]}")
    summary = next((ln for ln in reversed(out.splitlines()) if "PASS=" in ln), "")
    return {"step": DBT_TASK, "summary": summary.strip(), "returncode": done.returncode}


# The runbook each step's alert points at. This mirrors mizan.orchestration.oncall.RUNBOOKS, which the
# Fabric worker cannot import, and tests/test_oncall.py asserts the two agree -- the QR-code bug on
# 2026-11-19 was one rule written down twice and allowed to drift, so this one is pinned by a test.
RUNBOOKS = {"bronze_land": "the-bank-file-did-not-arrive", "silver_build": "a-silver-step-failed",
            "mdm_resolve": "a-silver-step-failed",
            "zatca_chain": "zatca-documents-are-stuck-in-an-unknown-outcome",
            "ai_index": "a-serving-step-failed", "ndmo_catalog": "a-serving-step-failed",
            "dbt_build_gold": "the-circuit-breaker-tripped"}
PAGES = tuple(k for k in RUNBOOKS if k not in ("ai_index", "ndmo_catalog"))


def alert_payload(step: str, detail: str, run_id: str = "") -> dict:
    """What a human needs at 03:00, in the order they need it.

    The AI index and the NDMO catalogue raise a ticket rather than paging: nothing downstream of them
    moves money, and a pager that fires for a stale search index is a pager people learn to ignore.
    """
    severity = "PAGE" if step in PAGES else "TICKET"
    runbook = RUNBOOKS.get(step, "an-unrecognised-failure")
    return {"severity": severity, "step": step, "summary": f"{step} failed", "run_id": run_id,
            "detail": detail[:2000], "runbook": f"docs/RUNBOOKS.md#{runbook}",
            "text": "\n".join([f"[{severity}] MIZAN {step}: failed",
                              f"run {run_id or 'unknown'}",
                              f"Runbook: docs/RUNBOOKS.md#{runbook}",
                              detail[:1000]])}


def on_failure(context) -> None:                # pragma: no cover - Airflow calls this, not a test
    """Airflow's failure hook: print the alert, and POST it if a webhook is configured.

    Printing first and unconditionally is the point. A webhook can be unset, wrong or down, and the
    task log is the one place the message is guaranteed to exist. Nothing here raises: an alerting
    failure must never turn a failed task into a crashed one, or a failed run into a lost one.
    """
    task = context.get("task_instance")
    step = getattr(task, "task_id", "unknown")
    run_id = str(context.get("run_id") or "")
    payload = alert_payload(step, str(context.get("exception") or "no exception recorded"), run_id)
    print(payload["text"])
    url = ""
    try:
        from airflow.models import Variable
        url = Variable.get("mizan_alert_webhook", default_var="") or ""
    except Exception as e:                      # alerting must not raise, ever
        print(f"[alert] could not read mizan_alert_webhook: {e}")
    if not url.startswith("https://"):
        print("[alert] no https webhook configured; the task log above is the alert")
        return
    try:
        request = urllib.request.Request(  # noqa: S310 (https checked)
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            print(f"[alert] delivered, HTTP {response.status}")
    except Exception as e:                      # see above: alerting must not raise
        print(f"[alert] delivery failed ({type(e).__name__}: {e}); the task log above is the alert")


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
        default_args={"on_failure_callback": on_failure},
    ) as dag:
        tasks = {step: PythonOperator(task_id=step, python_callable=run_step, op_kwargs={"step": step},
                                      retries=0)   # a step that failed is re-run by hand, after reading why
                 for step in STEP_ORDER}
        tasks[DBT_TASK] = PythonOperator(task_id=DBT_TASK, python_callable=dbt_build, retries=0)
        for upstream, downstream in edges():
            tasks[upstream] >> tasks[downstream]

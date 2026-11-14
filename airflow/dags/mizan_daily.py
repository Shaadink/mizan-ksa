"""MIZAN-KSA outer batch DAG (spec Section 7: Airflow owns the schedule; Fabric runs the jobs).

MIZAN_FABRIC_MODE=mock   (Docker): Fabric jobs are mocked; freshness gate, residency gate and lineage run for real
                          against the mounted lake (MIZAN_LAKE_ROOT) and post to Marquez.
MIZAN_FABRIC_MODE=fabric (Phase 10): the same tasks call the Fabric REST API with the service principal in .env.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

MODE = os.environ.get("MIZAN_FABRIC_MODE", "mock")
LAKE = Path(os.environ.get("MIZAN_LAKE_ROOT", "/opt/mizan/data/lake"))
REPO = Path(os.environ.get("MIZAN_REPO", "/opt/mizan"))
MARQUEZ = os.environ.get("MIZAN_MARQUEZ_URL", "http://marquez:5000/api/v1/lineage")
FABRIC_JOBS = ("bronze_land", "silver_build", "zatca_chain", "mdm_resolve")
SERVING_JOBS = ("restore_guard", "ai_index", "ndmo_catalog")


def _run_id(ctx) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mizan-ksa/{ctx['dag_run'].run_id}"))


def fabric_job(job: str, **ctx) -> dict:
    from mizan.lineage.openlineage import git_sha, run_event
    from mizan.orchestration.fabric_client import client
    run = client(MODE).run_job(job, {"run_id": _run_id(ctx)})
    if run.status != "Completed":
        raise RuntimeError(f"Fabric job {job} ended {run.status}: {run.failure}")
    io = {"bronze_land": ([], ["brz.commerce_events_raw", "brz.payment_events_raw", "brz.settlement_batches_raw",
                               "brz.erp_gl_raw", "brz.crm_party_raw", "brz.zatca_invoices_raw"]),
          "silver_build": (["brz.payment_events_raw", "brz.settlement_batches_raw", "brz.erp_gl_raw"],
                           ["slv.payment_lifecycle", "slv.settlement_lines", "slv.erp_gl_journal_lines"]),
          "zatca_chain": (["brz.zatca_invoices_raw"], ["ctl.invoice_outbox", "audit.zatca_chain_journal",
                                                         "slv.zatca_invoice_documents"]),
          "mdm_resolve": (["brz.crm_party_raw", "brz.spl_address_raw"], ["slv.golden_party_scd2",
                                                                          "slv.entity_merge_ledger"]),
          }.get(job, ([], []))
    rid = str(uuid.uuid5(uuid.UUID(_run_id(ctx)), job))
    events = [run_event(t, f"fabric.{job}", rid, inputs=io[0], outputs=io[1], sha=git_sha(),
                        parent=("mizan_daily", _run_id(ctx))) for t in ("START", "COMPLETE")]
    _post_quiet(events)
    return {"job": job, "instance": run.instance_id, "status": run.status}


def freshness_gate(**ctx) -> dict:
    from mizan.orchestration.freshness import gate, visible_batches_local
    expected = visible_batches_local(LAKE) if MODE == "mock" else set(json.loads(
        ctx["ti"].xcom_pull(task_ids="fabric_bronze_land")["batches"]))
    return gate(LAKE, expected, retries=5, wait_s=30)


def dbt_build(**ctx) -> dict:
    if MODE == "mock":
        from mizan.orchestration.fabric_client import client
        return {"dbt": client("mock").run_job("dbt_build").status}
    import subprocess
    proj = str(REPO / "dbt")
    cmd = ["dbt", "build", "--project-dir", proj, "--profiles-dir", proj, "--target", "fabric"]
    r = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603 (fixed argv, dbt on PATH)
    if r.returncode:
        raise RuntimeError(r.stdout[-4000:])
    return {"dbt": "success"}


def residency_gate(**ctx) -> dict:
    from mizan.governance.residency_gate import main
    gold = REPO / "tmp" / "mizan_gold.duckdb"
    args = ["--lake", str(LAKE)] + (["--duckdb", str(gold)] if gold.exists() else [])
    if main(args):
        raise RuntimeError("residency / classification gate failed (I-14)")
    return {"gate": "PASS"}


def lineage_and_manifest(**ctx) -> dict:
    from mizan.lineage.openlineage import git_sha, gold_events
    doc_path = REPO / "data" / "out" / "lineage" / "gold_column_lineage.json"
    sent = 0
    if doc_path.exists():
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        sent = _post_quiet(gold_events(doc, _run_id(ctx), parent=("mizan_daily", _run_id(ctx))))
    manifest = {"run_id": _run_id(ctx), "dag_run_id": ctx["dag_run"].run_id, "git_sha": git_sha(), "mode": MODE,
                "finished_at": datetime.utcnow().isoformat() + "Z", "lineage_events_sent": sent}
    out = REPO / "data" / "out" / "run_manifests"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{manifest['run_id']}.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def _post_quiet(events) -> int:
    from mizan.lineage.openlineage import post
    try:
        return post(events, MARQUEZ)
    except OSError as e:                       # lineage must never fail the money pipeline
        print(f"lineage endpoint unavailable: {e}")
        return 0


with DAG(dag_id="mizan_daily", start_date=datetime(2026, 2, 12), schedule="0 3 * * *", catchup=False,
         max_active_runs=1, tags=["mizan", "fabric"],
         doc_md=__doc__) as dag:
    prev = None
    for job in FABRIC_JOBS:
        t = PythonOperator(task_id=f"fabric_{job}", python_callable=fabric_job, op_kwargs={"job": job})
        if prev:
            prev >> t
        prev = t
    fresh = PythonOperator(task_id="freshness_gate", python_callable=freshness_gate)
    guard = PythonOperator(task_id="fabric_restore_guard", python_callable=fabric_job,
                           op_kwargs={"job": "restore_guard"})
    build = PythonOperator(task_id="dbt_build_gold", python_callable=dbt_build)
    ai = PythonOperator(task_id="fabric_ai_index", python_callable=fabric_job, op_kwargs={"job": "ai_index"})
    ndmo = PythonOperator(task_id="fabric_ndmo_catalog", python_callable=fabric_job,
                          op_kwargs={"job": "ndmo_catalog"})
    gate = PythonOperator(task_id="residency_gate", python_callable=residency_gate)
    lin = PythonOperator(task_id="lineage_and_run_manifest", python_callable=lineage_and_manifest)
    prev >> guard >> fresh >> build >> [ai, ndmo] >> gate >> lin

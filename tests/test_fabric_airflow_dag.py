"""The DAG that Fabric's own Airflow job runs (dags/mizan_fabric_daily.py).

Fabric syncs this file from the public repository and imports it in a worker that has no `mizan` package,
no repo and no network back to this machine. There is no way to run it here, so what is tested is everything
that can be: that the module imports with nothing but the standard library, that its REST contract matches
the one Fabric actually answers, that a failed step raises instead of letting the next one read half-written
tables, and that no credential is ever written into the file.

The DAG object itself is not built here -- that needs Airflow and a scheduler. It is guarded in the module so
this import works without them, which is also what makes a syntax error impossible to push unnoticed.
"""

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DAG_FILE = REPO / "dags" / "mizan_fabric_daily.py"


@pytest.fixture(scope="module")
def dag_module():
    spec = importlib.util.spec_from_file_location("mizan_fabric_daily", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mizan_fabric_daily"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["mizan_fabric_daily"]


@pytest.fixture
def settings(monkeypatch):
    for name, value in {"MIZAN_TENANT_ID": "tenant", "MIZAN_CLIENT_ID": "client",
                        "MIZAN_CLIENT_SECRET": "shh", "MIZAN_WORKSPACE_ID": "ws",
                        "MIZAN_LAKEHOUSE_ID": "lh", "MIZAN_NOTEBOOK_ID": "nb"}.items():
        monkeypatch.setenv(name, value)


def test_the_dag_file_imports_nothing_the_fabric_worker_lacks():
    """Fabric's Airflow workers have the standard library and Airflow. A third import is a failed DAG."""
    allowed = {"json", "os", "time", "urllib", "airflow", "pendulum", "__future__"}
    tree = ast.parse(DAG_FILE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= allowed, (
        f"{sorted(imported - allowed)} is not available in Fabric's Airflow worker. Either vendor it into "
        "this file or add it as a private package; see docs/FABRIC_AIRFLOW.md.")


def test_no_credential_is_written_into_the_dag_file():
    """Microsoft's own dbt tutorial puts a client secret in a synced file. This repository must not."""
    text = DAG_FILE.read_text(encoding="utf-8")
    for marker in ("-----BEGIN", "AccountKey=", "SharedAccessSignature", "client_secret=\""):
        assert marker not in text, f"{marker!r} looks like a credential pasted into a file Fabric syncs"
    # The secret is named, never carried: every use must go through the Variable lookup.
    assert text.count("mizan_client_secret") == text.count('setting("mizan_client_secret")') + 1  # + the docstring
    assert "Variable.get" in text


def test_the_pipeline_order_is_the_one_the_lakehouse_requires(dag_module):
    e = dag_module.edges()
    assert ("bronze_land", "silver_build") in e, "Silver reads what Bronze landed"
    assert ("silver_build", "mdm_resolve") in e and ("mdm_resolve", "zatca_chain") in e
    assert {("zatca_chain", "ai_index"), ("zatca_chain", "ndmo_catalog")} <= set(e)
    # The fan-out pair must not be chained to each other, or the run is needlessly serial.
    assert ("ai_index", "ndmo_catalog") not in e and ("ndmo_catalog", "ai_index") not in e
    assert len(dag_module.STEP_ORDER) == 6 and len(e) == 5


def test_a_missing_setting_names_itself_instead_of_failing_at_the_rest_call(dag_module, monkeypatch):
    monkeypatch.delenv("MIZAN_WORKSPACE_ID", raising=False)
    with pytest.raises(RuntimeError, match="mizan_workspace_id"):
        dag_module.setting("mizan_workspace_id")


def test_a_step_submits_then_polls_the_location_until_terminal(dag_module, settings, monkeypatch):
    calls, states = [], iter(["NotStarted", "InProgress", "Completed"])

    def fake_http(method, url, *, token=None, body=None, form=None, timeout=60):
        calls.append((method, url, body, form))
        if form is not None:
            return 200, {}, {"access_token": "tok"}
        if method == "POST":
            return 202, {"Location": f"{dag_module.FABRIC_API}/workspaces/ws/items/nb/jobs/instances/j-7"}, {}
        return 200, {}, {"status": next(states)}

    monkeypatch.setattr(dag_module, "_http", fake_http)
    result = dag_module.run_step("silver_build", poll_seconds=0)
    assert result == {"step": "silver_build", "run_id": "j-7", "status": "Completed", "polls": 3}

    token_call, submit = calls[0], calls[1]
    assert token_call[3]["grant_type"] == "client_credentials" and token_call[3]["client_secret"] == "shh"
    assert submit[1].endswith("/workspaces/ws/items/nb/jobs/instances?jobType=RunNotebook")
    # One notebook runs every step; the parameter is what selects it, and the lakehouse id travels with it.
    assert submit[2]["executionData"]["parameters"] == {
        "step": {"value": "silver_build", "type": "string"},
        "ws_id": {"value": "ws", "type": "string"},
        "lh_id": {"value": "lh", "type": "string"}}


def test_a_failed_step_raises_rather_than_letting_the_next_one_read_half_written_tables(
        dag_module, settings, monkeypatch):
    def fake_http(method, url, *, token=None, body=None, form=None, timeout=60):
        if form is not None:
            return 200, {}, {"access_token": "tok"}
        if method == "POST":
            return 202, {"Location": f"{dag_module.FABRIC_API}/workspaces/ws/items/nb/jobs/instances/j-9"}, {}
        return 200, {}, {"status": "Failed", "failureReason": {"message": "notebook cell 4 raised"}}

    monkeypatch.setattr(dag_module, "_http", fake_http)
    with pytest.raises(RuntimeError, match="notebook cell 4 raised"):
        dag_module.run_step("zatca_chain", poll_seconds=0)


def test_a_refused_submission_says_so_instead_of_polling_a_location_it_never_got(
        dag_module, settings, monkeypatch):
    def fake_http(method, url, *, token=None, body=None, form=None, timeout=60):
        if form is not None:
            return 200, {}, {"access_token": "tok"}
        return 403, {}, {"message": "principal lacks permission on the item"}

    monkeypatch.setattr(dag_module, "_http", fake_http)
    with pytest.raises(RuntimeError, match="403"):
        dag_module.run_step("bronze_land", poll_seconds=0)


def test_a_bad_token_response_never_echoes_the_secret(dag_module, settings, monkeypatch):
    monkeypatch.setattr(dag_module, "_http",
                        lambda *a, **k: (401, {}, {"error_description": "AADSTS7000215: invalid secret"}))
    with pytest.raises(PermissionError) as err:
        dag_module.service_principal_token()
    assert "AADSTS7000215" in str(err.value) and "shh" not in str(err.value)


def test_plain_http_endpoints_are_refused(dag_module):
    with pytest.raises(ValueError, match="HTTPS"):
        dag_module._http("GET", "http://api.fabric.microsoft.com/v1/workspaces")


def test_the_rendered_diagram_matches_the_dag_rather_than_a_drawing_of_it(dag_module, tmp_path):
    """The SVG in docs/artifacts is generated from edges(); a hand-edited one would drift the first time
    the pipeline changed. Re-render and compare, so the committed picture is always the current shape."""
    sys.path.insert(0, str(REPO / "scripts"))
    import render_dag_graph as R

    committed = (REPO / "docs" / "artifacts" / "06_fabric_airflow_dag.svg").read_text(encoding="utf-8")
    assert R.render(dag_module) == committed, (
        "docs/artifacts/06_fabric_airflow_dag.svg is stale -- run scripts/render_dag_graph.py")
    for step in dag_module.STEP_ORDER:
        assert f">{step}<" in committed, f"{step} is missing from the diagram"
    # It must never be mistaken for the Airflow screenshot, which is evidence of a run rather than a shape.
    assert "Not a screenshot" in committed

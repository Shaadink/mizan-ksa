"""Phase 8 (pure Python): Fabric job client (REST contract, polling, failures), freshness gate, OpenLineage events
and Gold column-lineage coverage rules (I-13)."""

import pytest

from mizan.lineage import openlineage as OL
from mizan.orchestration import fabric_client as FC
from mizan.orchestration.freshness import StaleLakehouse, check


def test_freshness_gate():
    assert check({"a", "b"}, {"a", "b", "old"})["status"] == "FRESH"
    with pytest.raises(StaleLakehouse):
        check({"a", "b"}, {"a"})


def test_mock_client_and_injected_failure():
    c = FC.MockFabricClient(fail_jobs={"zatca_chain"})
    assert c.run_job("bronze_land").status == "Completed"
    r = c.run_job("zatca_chain")
    assert r.status == "Failed" and r.failure and c.log == ["bronze_land", "zatca_chain"]
    with pytest.raises(ValueError):
        FC.client("prod")


def test_fabric_client_submits_then_polls_location(monkeypatch):
    calls = []
    states = iter(["NotStarted", "InProgress", "Completed"])

    def fake_http(method, url, *, token=None, body=None, form=None, timeout=60):
        calls.append((method, url, token, body))
        if method == "POST":
            return 202, {"Location": "https://api.fabric.microsoft.com/v1/workspaces/w/items/i/jobs/instances/j-1"}, {}
        return 200, {}, {"status": next(states)}
    monkeypatch.setattr(FC, "_http", fake_http)
    c = FC.FabricClient("w", {"silver_build": "i"}, "tok")
    r = c.run_job("silver_build", {"run_id": "r1"}, poll_seconds=0)
    assert r.status == "Completed" and r.instance_id == "j-1" and r.polls == 3
    method, url, token, body = calls[0]
    assert method == "POST" and url.endswith("/workspaces/w/items/i/jobs/instances?jobType=RunNotebook")
    assert token == "tok" and body["executionData"]["parameters"]["run_id"] == {"value": "r1", "type": "string"}


def test_fabric_client_reports_failure_and_rejects_bad_submit(monkeypatch):
    def failing(method, url, **kw):
        if method == "POST":
            return 202, {"Location": "https://x/jobs/instances/j-2"}, {}
        return 200, {}, {"status": "Failed", "failureReason": {"message": "notebook raised"}}
    monkeypatch.setattr(FC, "_http", failing)
    r = FC.FabricClient("w", {"j": "i"}, "tok").run_job("j", poll_seconds=0)
    assert r.status == "Failed" and r.failure == "notebook raised"
    monkeypatch.setattr(FC, "_http", lambda *a, **k: (403, {}, {"errorCode": "InsufficientPrivileges"}))
    with pytest.raises(RuntimeError):
        FC.FabricClient("w", {"j": "i"}, "tok").run_job("j", poll_seconds=0)


def test_token_failure_is_a_permission_error(monkeypatch):
    monkeypatch.setattr(FC, "_http", lambda *a, **k: (401, {}, {"error_description": "AADSTS7000215"}))
    with pytest.raises(PermissionError):
        FC.sp_token("t", "c", "s")


def test_http_refuses_non_https():
    with pytest.raises(ValueError):
        FC._http("GET", "http://insecure")


MANIFEST = {"nodes": {
    "model.mizan_ksa.fact_x": {"resource_type": "model", "name": "fact_x",
                               "depends_on": {"nodes": ["source.mizan_ksa.slv_lakehouse.payments",
                                                        "seed.mizan_ksa.cal"]}},
    "seed.mizan_ksa.cal": {"resource_type": "seed", "name": "cal", "depends_on": {"nodes": []}}}}
COLS = {"gld.fact_x": ["merchant_id", "total_sar", "calendar_date"], "slv.payments": ["merchant_id", "amount_sar"],
        "gld.cal": ["calendar_date"]}


def test_column_lineage_same_name_plus_overrides():
    lin = OL.column_lineage(MANIFEST, COLS, {"fact_x": {"total_sar": ["slv.payments.amount_sar"]}})
    assert lin == {"fact_x": {"merchant_id": ["slv.payments.merchant_id"],
                              "total_sar": ["slv.payments.amount_sar"],
                              "calendar_date": ["gld.cal.calendar_date"]}}


def test_column_lineage_refuses_gaps_and_bad_inputs():
    with pytest.raises(ValueError, match="without lineage"):
        OL.column_lineage(MANIFEST, COLS, {})
    with pytest.raises(ValueError, match="does not exist"):
        OL.column_lineage(MANIFEST, COLS, {"fact_x": {"total_sar": ["slv.payments.nope"]}})


def test_run_event_shape():
    lin = OL.column_lineage(MANIFEST, COLS, {"fact_x": {"total_sar": ["slv.payments.amount_sar"]}})
    e = OL.run_event("COMPLETE", "dbt.gld.fact_x", "11111111-1111-1111-1111-111111111111",
                     inputs=["slv.payments"], outputs=["gld.fact_x"], lineage=lin, columns=COLS, sha="abc",
                     snapshots={"slv.payments": 7}, parent=("mizan_daily", "22222222-2222-2222-2222-222222222222"))
    assert e["eventType"] == "COMPLETE" and e["run"]["facets"]["mizan_run"]["git_sha"] == "abc"
    assert e["run"]["facets"]["mizan_run"]["snapshot_versions"] == {"slv.payments": 7}
    out = e["outputs"][0]
    assert out["namespace"] == OL.NAMESPACE_WH and out["name"] == "gld.fact_x"
    f = out["facets"]["columnLineage"]["fields"]["total_sar"]["inputFields"][0]
    assert f == {"namespace": OL.NAMESPACE_LH, "name": "slv.payments", "field": "amount_sar"}
    assert e["inputs"][0]["namespace"] == OL.NAMESPACE_LH
    with pytest.raises(ValueError):
        OL.run_event("RUNNING", "j", "r")


# ---------------------------------------------------------------- credential diagnostic


def test_sp_token_status_never_prints_the_secret(monkeypatch):
    """The whole value of this helper is that it can be run and pasted. If it ever echoed the secret it
    would turn a diagnostic into a leak, and the obvious implementation -- printing the Entra error body --
    is one refactor away from doing exactly that."""
    from mizan.orchestration import fabric_client

    secret = "s3cr3t-value-that-must-never-appear"
    # `sp_token_status` imports load_dotenv from crypto INSIDE the call, so patching it on
    # fabric_client does nothing and the real .env loads -- which made this test pass against the
    # developer's own working credentials instead of the state it meant to set up.
    from mizan.privacy import crypto
    monkeypatch.setattr(crypto, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", secret)

    def refuse(*_a, **_k):
        raise PermissionError("token request failed (401): AADSTS7000215 bad secret for app 'client'")

    monkeypatch.setattr(fabric_client, "sp_token", refuse)
    out = fabric_client.sp_token_status()
    assert secret not in out
    assert out.startswith("FAILED:") and "AADSTS7000215" in out


def test_sp_token_status_says_cannot_check_rather_than_ok_when_unconfigured(monkeypatch):
    """A missing credential must never read as a passing check. 'I could not tell' and 'it is fine' are
    different answers, and conflating them is how somebody regenerates a secret that was never the problem."""
    from mizan.orchestration import fabric_client

    # `sp_token_status` imports load_dotenv from crypto INSIDE the call, so patching it on
    # fabric_client does nothing and the real .env loads -- which made this test pass against the
    # developer's own working credentials instead of the state it meant to set up.
    from mizan.privacy import crypto
    monkeypatch.setattr(crypto, "load_dotenv", lambda *a, **k: None)
    for key in ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    out = fabric_client.sp_token_status()
    assert out.startswith("CANNOT CHECK:") and "FABRIC_CLIENT_SECRET" in out


def test_sp_token_status_distinguishes_a_network_failure_from_a_bad_credential(monkeypatch):
    """Entra being unreachable says nothing about the secret. Reporting it as FAILED would send somebody
    to regenerate a credential because their wifi dropped."""
    from mizan.orchestration import fabric_client

    # `sp_token_status` imports load_dotenv from crypto INSIDE the call, so patching it on
    # fabric_client does nothing and the real .env loads -- which made this test pass against the
    # developer's own working credentials instead of the state it meant to set up.
    from mizan.privacy import crypto
    monkeypatch.setattr(crypto, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "x")

    def unreachable(*_a, **_k):
        raise OSError("getaddrinfo failed")

    monkeypatch.setattr(fabric_client, "sp_token", unreachable)
    out = fabric_client.sp_token_status()
    assert out.startswith("CANNOT CHECK:") and "says nothing about the credential" in out

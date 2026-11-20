"""The operational layer: alerts that reach a human, and an SLA somebody is measured against.

What is tested here is the part that is easy to get wrong and invisible when it is: an alert that points at
a runbook heading that does not exist, an alerting failure that takes the pipeline down with it, a severity
that routes a money-path failure to a ticket queue nobody reads until Monday, and an SLA that reports "met"
because nobody checked the timezone.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mizan.orchestration import oncall as OC

REPO = Path(__file__).resolve().parents[1]
RUNBOOKS = REPO / "docs" / "RUNBOOKS.md"


def _headings() -> set[str]:
    """GitHub's anchor rule: lowercase, spaces to hyphens, punctuation dropped."""
    out = set()
    for line in RUNBOOKS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            slug = re.sub(r"[^a-z0-9 -]", "", line[3:].strip().lower()).replace(" ", "-")
            out.add(slug)
    return out


def test_every_alert_points_at_a_runbook_that_exists():
    """A dead link in a 03:00 alert is worse than no link: it costs the time it was meant to save."""
    headings = _headings()
    missing = {step: rb for step, rb in OC.RUNBOOKS.items() if rb not in headings}
    assert not missing, f"docs/RUNBOOKS.md has no heading for {missing}"
    assert OC.DEFAULT_RUNBOOK in headings, "the catch-all runbook must exist too"


def test_every_pipeline_step_has_a_runbook():
    """A step with no entry falls back to the catch-all, which is correct but should be deliberate."""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("mfd", REPO / "dags" / "mizan_fabric_daily.py")
    dag = importlib.util.module_from_spec(spec)
    sys.modules["mfd"] = dag
    spec.loader.exec_module(dag)
    try:
        for step in (*dag.STEP_ORDER, dag.DBT_TASK):
            assert step in OC.RUNBOOKS, f"{step} has no runbook; add one to docs/RUNBOOKS.md"
    finally:
        del sys.modules["mfd"]


def test_money_path_failures_page_and_serving_failures_do_not():
    """Waking someone for a stale search index teaches them to ignore the pager."""
    for step in ("bronze_land", "silver_build", "zatca_chain", "dbt_build_gold"):
        assert OC.step_alert(step, "boom").severity == "PAGE", step
    for step in ("ai_index", "ndmo_catalog"):
        assert OC.step_alert(step, "boom").severity == "TICKET", step


def test_an_unknown_severity_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="unknown severity"):
        OC.Alert(severity="URGENT", step="bronze_land", summary="x")


def test_the_alert_text_fits_a_phone_and_names_what_to_do():
    alert = OC.step_alert("zatca_chain", RuntimeError("Fabric reported Failed"),
                          run_id="j-7", git_sha="abc1234")
    text = alert.as_text()
    assert text.splitlines()[0].startswith("[PAGE] MIZAN zatca_chain:")
    assert "docs/RUNBOOKS.md#zatca-documents-are-stuck-in-an-unknown-outcome" in text
    assert "j-7" in text and "abc1234" in text and "Fabric reported Failed" in text
    assert len(text) < 1400, "an alert nobody can read on a phone is an alert nobody reads"


def test_a_long_traceback_is_truncated_not_dropped():
    alert = OC.step_alert("silver_build", "x" * 9000)
    assert len(alert.as_dict()["detail"]) == 2000 and alert.as_dict()["detail"].startswith("xxx")


# ------------------------------------------------------------------ the close SLA

def test_the_deadline_is_six_in_the_morning_riyadh_the_day_after():
    deadline = OC.close_deadline("2026-03-03")
    assert deadline.isoformat() == "2026-03-04T06:00:00+03:00"


def test_a_close_that_landed_before_the_deadline_is_met_and_raises_nothing():
    finished = datetime(2026, 3, 4, 3, 18, tzinfo=OC.KSA)
    sla = OC.close_sla("2026-03-03", finished)
    assert sla["status"] == "MET" and sla["minutes_early"] == 162
    assert OC.sla_alert(sla) is None, "a met SLA is not news"


def test_a_late_close_is_measured_in_minutes_and_pages():
    finished = datetime(2026, 3, 4, 7, 5, tzinfo=OC.KSA)
    sla = OC.close_sla("2026-03-03", finished)
    assert sla["status"] == "BREACHED" and sla["minutes_late"] == 65
    alert = OC.sla_alert(sla)
    assert alert.severity == "PAGE" and "65 minutes" in alert.summary
    assert alert.runbook == "the-close-will-miss-its-deadline"


def test_a_utc_timestamp_is_converted_rather_than_compared_raw():
    """03:30 UTC is 06:30 Riyadh -- late. Comparing the raw clock would call it three hours early."""
    from datetime import UTC
    finished = datetime(2026, 3, 4, 3, 30, tzinfo=UTC)
    sla = OC.close_sla("2026-03-03", finished)
    assert sla["status"] == "BREACHED" and sla["minutes_late"] == 30


def test_a_run_still_going_reports_the_time_left_so_the_warning_can_come_first():
    now = datetime(2026, 3, 4, 5, 30, tzinfo=OC.KSA)
    sla = OC.close_sla("2026-03-03", None, now=now)
    assert sla["status"] == "PENDING" and sla["minutes_remaining"] == 30
    sla = OC.close_sla("2026-03-03", None, now=now + timedelta(hours=1))
    assert sla["status"] == "BREACHED" and sla["minutes_late"] == 30


# ------------------------------------------------------------------ delivery

def test_alerting_never_raises_when_the_webhook_is_down(monkeypatch):
    """The pipeline must not fail because the thing that reports failures failed."""
    import urllib.request

    def boom(*_a, **_k):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    result = OC.notify(OC.step_alert("bronze_land", "x"), "https://hooks.example.com/abc")
    assert result["delivered"] is False and "OSError" in result["reason"]
    assert result["alert"]["step"] == "bronze_land"   # still returned, so the caller can log it


def test_no_webhook_configured_is_a_state_not_an_error():
    result = OC.notify(OC.step_alert("bronze_land", "x"), None)
    assert result["delivered"] is False and result["reason"] == "NOT_CONFIGURED"


def test_a_plaintext_webhook_is_refused():
    result = OC.notify(OC.step_alert("bronze_land", "x"), "http://hooks.example.com/abc")
    assert result["delivered"] is False and result["reason"] == "INSECURE_URL"


def test_a_delivered_alert_carries_both_text_and_fields(monkeypatch):
    import json
    import urllib.request
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data)
        captured["url"] = request.full_url
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = OC.notify(OC.step_alert("dbt_build_gold", "unique test failed", run_id="r1"),
                       "https://hooks.example.com/abc")
    assert result["delivered"] is True
    # Chat tools render `text`; machines read the fields. Send both rather than choosing.
    assert captured["body"]["text"].startswith("[PAGE] MIZAN dbt_build_gold")
    assert captured["body"]["severity"] == "PAGE"
    assert captured["body"]["runbook"] == "docs/RUNBOOKS.md#the-circuit-breaker-tripped"


def test_the_runbooks_say_what_the_project_does_not_have():
    """A runbook that implies an on-call rota exists would be a lie told at 03:00."""
    text = RUNBOOKS.read_text(encoding="utf-8")
    assert "There is nobody on call" in text
    assert "no paging" in text and "escalation ladder" in text
    assert "Never edit Gold by hand" in text


def _fabric_dag():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("mfd2", REPO / "dags" / "mizan_fabric_daily.py")
    dag = importlib.util.module_from_spec(spec)
    sys.modules["mfd2"] = dag
    spec.loader.exec_module(dag)
    return dag


def test_the_fabric_dag_and_oncall_agree_about_runbooks_and_severity():
    """Two copies of one rule is how the QR-code bug happened. This is the guard against the repeat.

    The Fabric worker cannot import `mizan`, so the DAG carries its own copy of the runbook map and the
    paging rule. A copy is acceptable only while something fails when the copies disagree.
    """
    dag = _fabric_dag()
    try:
        for step, runbook in dag.RUNBOOKS.items():
            assert OC.RUNBOOKS[step] == runbook, f"{step}: DAG says {runbook}, oncall says {OC.RUNBOOKS[step]}"
        for step in dag.RUNBOOKS:
            expected = OC.step_alert(step, "x").severity
            actual = dag.alert_payload(step, "x")["severity"]
            assert actual == expected, f"{step}: DAG says {actual}, oncall says {expected}"
    finally:
        import sys
        del sys.modules["mfd2"]


def test_the_dag_alert_carries_the_same_fields_a_webhook_would_receive():
    dag = _fabric_dag()
    try:
        payload = dag.alert_payload("zatca_chain", "Fabric reported Failed", "manual__2026-11-20")
        assert payload["severity"] == "PAGE"
        assert payload["runbook"] == "docs/RUNBOOKS.md#zatca-documents-are-stuck-in-an-unknown-outcome"
        assert payload["text"].startswith("[PAGE] MIZAN zatca_chain: failed")
        assert "manual__2026-11-20" in payload["text"] and "Fabric reported Failed" in payload["text"]
        assert len(payload["detail"]) <= 2000
    finally:
        import sys
        del sys.modules["mfd2"]


def test_an_unknown_step_still_gets_the_catch_all_runbook_in_both_places():
    dag = _fabric_dag()
    try:
        assert dag.alert_payload("mystery", "x")["runbook"].endswith(OC.DEFAULT_RUNBOOK)
        assert OC.Alert("PAGE", "mystery", "x").runbook == OC.DEFAULT_RUNBOOK
    finally:
        import sys
        del sys.modules["mfd2"]


# ------------------------------------------------------------------ the backfill procedure
# scripts/backfill.py is the answer to "how do I re-run 30 days?". What is tested is its judgement,
# not its plumbing: a re-run that silently changes Gold must fail, and the circuit breaker refusing to
# publish must be reported as a correct outcome rather than as a backfill error.

def _backfill():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("backfill", REPO / "scripts" / "backfill.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill"] = module
    spec.loader.exec_module(module)
    return module


def test_an_unchanged_rebuild_is_summarised_as_unchanged():
    bf = _backfill()
    fp = {"gld.a": {"rows": 2, "hash": "x"}, "gld.b": {"rows": 1, "hash": "y"}}
    out = bf.summarise(fp, dict(fp), [])
    assert out["tables_compared"] == 2 and out["tables_unchanged"] == 2
    assert out["tables_changed"] == [] and out["difference_count"] == 0


def test_a_table_that_did_not_come_back_is_named_not_merely_counted():
    bf = _backfill()
    before = {"gld.a": {"hash": "x"}, "gld.b": {"hash": "y"}}
    after = {"gld.a": {"hash": "x"}, "gld.c": {"hash": "z"}}
    out = bf.summarise(before, after, ["gld.b missing"])
    assert out["tables_lost"] == ["gld.b"] and out["tables_new"] == ["gld.c"]
    assert set(out["tables_changed"]) == {"gld.b", "gld.c"}


def test_a_huge_difference_list_is_capped_but_its_size_is_reported():
    bf = _backfill()
    out = bf.summarise({}, {}, [f"row {i}" for i in range(500)])
    assert len(out["differences"]) == 50 and out["difference_count"] == 500


def test_the_dry_run_is_the_default_and_rebuilds_nothing(monkeypatch, capsys):
    """An operator who types the command without reading it must not start a rebuild.

    It does still fingerprint first, deliberately, so the starting state is on screen before any
    decision is made. What it must never do without --execute is rebuild.
    """
    bf = _backfill()

    class Drill:
        rebuilt = False

        @staticmethod
        def fingerprint(_path):
            return {"gld.a": {"hash": "x"}}

        @staticmethod
        def run_dbt(*_a):
            Drill.rebuilt = True
            return True, ""

    monkeypatch.setattr(bf, "_dr_drill", lambda: Drill)
    monkeypatch.setattr(bf.Path, "exists", lambda _self: True)
    assert bf.main([]) == 0
    assert Drill.rebuilt is False, "a dry run rebuilt Gold"
    assert "DRY RUN" in capsys.readouterr().out


def test_a_tripped_circuit_breaker_is_reported_as_a_correct_outcome_not_a_backfill_error(
        monkeypatch, capsys):
    """Gold not republishing because a test failed is the system working. Say so, and point at the
    runbook, rather than leaving an operator to conclude the backfill tool is broken."""
    bf = _backfill()

    class Drill:
        @staticmethod
        def fingerprint(_path):
            return {"gld.a": {"hash": "x"}}

        @staticmethod
        def run_dbt(*_a):
            return False, "Failure in test unique_gld_fact_x"

    monkeypatch.setattr(bf, "_dr_drill", lambda: Drill)
    monkeypatch.setattr(bf.Path, "exists", lambda _self: True)
    assert bf.main(["--execute"]) == 1
    out = capsys.readouterr().out
    assert "Gold was not republished" in out and "the-circuit-breaker-tripped" in out


def test_an_unexplained_change_on_a_rerun_fails_and_an_expected_one_does_not(monkeypatch, tmp_path):
    """Re-running unchanged source data must reproduce Gold exactly. If it does not, that is a finding."""
    bf = _backfill()
    states = iter([{"gld.a": {"hash": "x"}}, {"gld.a": {"hash": "CHANGED"}},
                   {"gld.a": {"hash": "x"}}, {"gld.a": {"hash": "CHANGED"}}])

    class Drill:
        @staticmethod
        def fingerprint(_path):
            return next(states)

        @staticmethod
        def run_dbt(*_a):
            return True, ""

        @staticmethod
        def compare(_b, _a):
            return ["gld.a hash moved"]

    monkeypatch.setattr(bf, "_dr_drill", lambda: Drill)
    monkeypatch.setattr(bf.Path, "exists", lambda _self: True)
    monkeypatch.setattr(bf, "OUT", tmp_path / "backfill.json")
    assert bf.main(["--execute"]) == 1, "an unexplained change must fail"
    assert bf.main(["--execute", "--expect-changes"]) == 0, "a deliberate correction must pass"

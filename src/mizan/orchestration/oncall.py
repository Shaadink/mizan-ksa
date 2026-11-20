"""The operational layer: what happens when the pipeline breaks at 03:00 and nobody is watching.

A pipeline that runs is not a pipeline that is operated. Operating one means three things exist:

  1. a failure reaches a human, with enough in the message to act on without opening a laptop,
  2. somebody knows by when the close has to be ready, and is told when it will not be,
  3. there is a written procedure for the failures that actually happen (docs/RUNBOOKS.md).

This module is (1) and (2). It is deliberately stdlib-only and deliberately small, because an alerting
path that is itself fragile is worse than none: it fails at exactly the moment it is needed and leaves
the impression that nothing went wrong.

**Alerting never fails the pipeline.** A webhook that is down, misconfigured or slow must not turn a
successful run into a failed one, and must not turn a failed run into a crashed one. `notify` therefore
returns a result and raises nothing. The cost of that choice is that a silent alerting failure is
possible, so `notify` reports what happened and the caller logs it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any

KSA = timezone(timedelta(hours=3))                       # Asia/Riyadh has no DST
SEVERITIES = ("PAGE", "TICKET", "INFO")

# The close has to be ready before the finance team starts. 06:00 Riyadh on the morning after the
# business date, which gives the 03:00 run three hours and still leaves time to act on a failure.
CLOSE_DEADLINE_KSA = time(6, 0)

# Which runbook answers which failure. The alert carries the heading so the person woken at 03:00 reads
# the procedure rather than searching for it. Every value here must exist in docs/RUNBOOKS.md, which
# tests/test_oncall.py asserts -- a runbook link that 404s at 03:00 is worse than no link.
RUNBOOKS = {
    "bronze_land": "the-bank-file-did-not-arrive",
    "silver_build": "a-silver-step-failed",
    "mdm_resolve": "a-silver-step-failed",
    "zatca_chain": "zatca-documents-are-stuck-in-an-unknown-outcome",
    "ai_index": "a-serving-step-failed",
    "ndmo_catalog": "a-serving-step-failed",
    "dbt_build_gold": "the-circuit-breaker-tripped",
    "freshness_gate": "the-bank-file-did-not-arrive",
    "residency_gate": "the-residency-gate-failed",
    "close_sla": "the-close-will-miss-its-deadline",
}
DEFAULT_RUNBOOK = "an-unrecognised-failure"


@dataclass
class Alert:
    """One thing a human has to know about, in the order they need to know it."""
    severity: str
    step: str
    summary: str
    run_id: str = ""
    git_sha: str = ""
    detail: str = ""
    runbook: str = ""
    at: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            # Fail closed on an unknown severity rather than guessing: an alert routed nowhere is the
            # failure mode this whole module exists to prevent.
            raise ValueError(f"unknown severity {self.severity!r}, expected one of {SEVERITIES}")
        self.runbook = self.runbook or RUNBOOKS.get(self.step, DEFAULT_RUNBOOK)
        self.at = self.at or datetime.now(KSA).isoformat(timespec="seconds")

    def as_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "step": self.step, "summary": self.summary,
                "run_id": self.run_id, "git_sha": self.git_sha, "detail": self.detail[:2000],
                "runbook": f"docs/RUNBOOKS.md#{self.runbook}", "at": self.at, "context": self.context}

    def as_text(self) -> str:
        """One screen on a phone. Severity, what broke, what to do, then the detail."""
        head = f"[{self.severity}] MIZAN {self.step}: {self.summary}"
        where = f"run {self.run_id or 'unknown'} | git {self.git_sha or 'unknown'} | {self.at}"
        return "\n".join([head, where, f"Runbook: docs/RUNBOOKS.md#{self.runbook}",
                          *( [self.detail.strip()[:1000]] if self.detail.strip() else [] )])


def step_alert(step: str, exc: BaseException | str, *, run_id: str = "", git_sha: str = "") -> Alert:
    """The alert for a failed pipeline step.

    Everything in the money path pages: a missed close is a finance problem the next morning, and the
    whole point of a 03:00 schedule is that there is time to fix it before anyone needs the numbers.
    The catalogue and the AI index do not page, because nothing downstream of them moves money.
    """
    severity = "TICKET" if step in ("ai_index", "ndmo_catalog") else "PAGE"
    detail = f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc)
    return Alert(severity=severity, step=step, summary=f"{step} failed", run_id=run_id,
                 git_sha=git_sha, detail=detail)


def close_deadline(business_date: str) -> datetime:
    """The moment the close for a business date must be published: 06:00 KSA the following morning."""
    day = datetime.strptime(business_date, "%Y-%m-%d").date() + timedelta(days=1)
    return datetime.combine(day, CLOSE_DEADLINE_KSA, tzinfo=KSA)


def close_sla(business_date: str, finished_at: datetime | None, *, now: datetime | None = None) -> dict:
    """Did the close for `business_date` land before its deadline, and if not, by how much?

    `finished_at` is None while the run is still going, which is the case that matters: the useful alert
    is the one sent *before* the deadline passes, not the post-mortem afterwards. A run still going with
    minutes left is already a breach in the making, and this reports it as PENDING with the minutes left
    so a caller can decide to warn.
    """
    deadline = close_deadline(business_date)
    now = now or datetime.now(KSA)
    if finished_at is None:
        left = int((deadline - now).total_seconds() // 60)
        return {"status": "PENDING" if left > 0 else "BREACHED", "business_date": business_date,
                "deadline_ksa": deadline.isoformat(timespec="minutes"), "minutes_remaining": left,
                "minutes_late": max(0, -left)}
    finished = finished_at.astimezone(KSA)
    late = int((finished - deadline).total_seconds() // 60)
    return {"status": "MET" if late <= 0 else "BREACHED", "business_date": business_date,
            "deadline_ksa": deadline.isoformat(timespec="minutes"),
            "finished_ksa": finished.isoformat(timespec="minutes"),
            "minutes_late": max(0, late), "minutes_early": max(0, -late)}


def sla_alert(sla: dict, *, run_id: str = "", git_sha: str = "") -> Alert | None:
    """An alert only when the close is late or about to be. A met SLA is not news."""
    if sla["status"] == "MET":
        return None
    if sla["status"] == "PENDING":
        return None
    return Alert(severity="PAGE", step="close_sla",
                 summary=f"close for {sla['business_date']} missed {sla['deadline_ksa']} "
                         f"by {sla['minutes_late']} minutes",
                 run_id=run_id, git_sha=git_sha, context=sla)


def notify(alert: Alert, url: str | None, *, timeout: int = 10) -> dict:
    """POST the alert to a webhook. Never raises: see the module docstring.

    `url` is read from configuration by the caller and may legitimately be unset -- on a developer
    machine there is nobody to wake. That returns NOT_CONFIGURED rather than failing, so the same code
    runs everywhere, and the caller prints the alert either way.
    """
    if not url:
        return {"delivered": False, "reason": "NOT_CONFIGURED", "alert": alert.as_dict()}
    if not url.startswith("https://"):
        # An alert can carry the name of a failing step and a run id. That is not secret, but it is
        # internal, and plaintext delivery of operational telemetry is not something to do by accident.
        return {"delivered": False, "reason": "INSECURE_URL", "alert": alert.as_dict()}
    body = json.dumps({"text": alert.as_text(), **alert.as_dict()}).encode()
    request = urllib.request.Request(  # noqa: S310 (https enforced above)
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return {"delivered": 200 <= response.status < 300, "status": response.status,
                    "alert": alert.as_dict()}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"delivered": False, "reason": f"{type(e).__name__}: {e}", "alert": alert.as_dict()}

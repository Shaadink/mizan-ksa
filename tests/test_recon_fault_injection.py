"""Measure the reconciliation's detection power instead of asserting it.

THE CRITICISM THIS ANSWERS. Five external reviewers made the same point, and it is the strongest objection
anyone has raised against this project: the same author wrote the generator and the reconciler, so they share
the rounding and fee rules, and SAR 0.00 variance therefore holds *by construction*. The only evidence of
detection to date is the two-row demo overlay -- two planted defects, both found, which proves almost nothing
about the other failure modes. A reconciliation that has never been shown to fail is not a control.

So this does not re-prove that clean data balances. It damages clean data on purpose, one perturbation at a
time, and reports what fraction of each class the daily-grain variance actually catches.

WHAT IT FINDS, stated here because the result is the point and not a footnote: single-sided perturbations are
caught every time, and **offsetting same-day errors are invisible**. A +5.00 SAR error on one capture and a
-5.00 SAR error on another capture for the same merchant on the same day net to zero inside the GROUP BY and
the day still reads SAR 0.00. That is not a bug in the SQL; it is the arithmetic consequence of reconciling at
merchant-day grain, and it is exactly what a line-level matching leg (payment_event_id to settlement line)
would catch and this model cannot. The test asserts that blind spot rather than hiding it, so it cannot be
quietly "fixed" by weakening a perturbation.

The reference implementation below recomputes the same two variances in Decimal rather than calling dbt, so
the test runs in under a second with no warehouse. It mirrors fact_merchant_settlement_recon.sql; if that
model's arithmetic changes, this must change with it -- and
`test_the_clean_slice_reconciles_before_anything_is_broken` is what catches the drift, because a reference that
no longer matches the model will not balance the untouched slice and every recall number below becomes void.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

LAKE = REPO / "data" / "lake" / "LH_MIZAN" / "slv"
SEED = 20261112          # the project's seed: perturbations must be reproducible like everything else
PERTURBATIONS = 50
ZERO = Decimal("0.00")


# ----------------------------------------------------------------------------- loading

@pytest.fixture(scope="module")
def legs() -> dict:
    """One slice of real Silver: a handful of merchants, so the harness stays fast and still uses real shapes."""
    duckdb = pytest.importorskip("duckdb")
    if not (LAKE / "settlement_lines").exists():
        pytest.skip("local lake not built (run the Bronze/Silver phase first)")
    from mizan.common.delta_snapshot import delta_rel

    con = duckdb.connect()
    pay = con.execute(f"""
        SELECT merchant_id, business_date_ksa, event_type, CAST(amount_sar AS VARCHAR) AS amount_sar,
               payment_event_id
        FROM {delta_rel(LAKE / 'payment_lifecycle')}
        WHERE merchant_id IN (SELECT DISTINCT merchant_id
                              FROM {delta_rel(LAKE / 'payment_lifecycle')} ORDER BY merchant_id LIMIT 6)
    """).fetchall()
    settle = con.execute(f"""
        SELECT merchant_id, settlement_for_date_ksa, settlement_status,
               CAST(net_settled_sar AS VARCHAR)      AS net_settled_sar,
               CAST(acquirer_mdr_fee_sar AS VARCHAR) AS mdr,
               CAST(acquirer_vat_sar AS VARCHAR)     AS vat,
               payment_event_id, CAST(gross_amount_sar AS VARCHAR) AS gross_amount_sar
        FROM {delta_rel(LAKE / 'settlement_lines')}
        WHERE merchant_id IN (SELECT DISTINCT merchant_id
                              FROM {delta_rel(LAKE / 'payment_lifecycle')} ORDER BY merchant_id LIMIT 6)
    """).fetchall()
    gl = con.execute(f"""
        SELECT merchant_id, posting_date_ksa, debit_credit, CAST(amount_sar AS VARCHAR) AS amount_sar
        FROM {delta_rel(LAKE / 'erp_gl_journal_lines')}
        WHERE gl_account_role = 'CARD_CLEARING'
          AND merchant_id IN (SELECT DISTINCT merchant_id
                              FROM {delta_rel(LAKE / 'payment_lifecycle')} ORDER BY merchant_id LIMIT 6)
    """).fetchall()
    con.close()

    if not (pay and settle and gl):
        pytest.skip("lake slice is empty")
    return {
        "captures": [{"mid": r[0], "day": str(r[1]), "event_type": r[2], "amount": Decimal(r[3]),
                      "event_id": r[4]} for r in pay],
        "settlements": [{"mid": r[0], "day": str(r[1]), "status": r[2], "net": Decimal(r[3]),
                         "fees": Decimal(r[4]) + Decimal(r[5]), "event_id": r[6],
                         "gross": Decimal(r[7])} for r in settle],
        "gl": [{"mid": r[0], "day": str(r[1]), "dc": r[2], "amount": Decimal(r[3])} for r in gl],
    }


def line_level_breaks(legs: dict) -> set[str]:
    """dbt/tests/assert_every_settled_line_matches_its_payment.sql in Decimal.

    One bank line per payment event is a stated contract, so the amount the bank settled must equal the
    amount the till captured, line by line, with nothing summed. That is why this sees what the merchant-day
    model arithmetically cannot.
    """
    settled = {r["event_id"]: r for r in legs["settlements"] if r["status"] != "QUARANTINED"}
    return {p["event_id"] for p in legs["captures"]
            if p["event_id"] in settled and p["amount"] != settled[p["event_id"]]["gross"]}


# ----------------------------------------------------------------------------- reference recon

def recon(legs: dict) -> dict[tuple[str, str], dict]:
    """fact_merchant_settlement_recon.sql in Decimal. Same UNION spine, same two variances."""
    cap: dict = defaultdict(lambda: {"gross": ZERO, "back": ZERO})
    for r in legs["captures"]:
        k = (r["mid"], r["day"])
        if r["event_type"] == "CAPTURE":
            cap[k]["gross"] += r["amount"]
        elif r["event_type"] in ("REFUND", "CHARGEBACK"):
            cap[k]["back"] += r["amount"]

    settle: dict = defaultdict(lambda: {"fees": ZERO, "paid": ZERO, "transit": ZERO, "quar": ZERO})
    for r in legs["settlements"]:
        k = (r["mid"], r["day"])
        settle[k]["fees"] += r["fees"]
        bucket = {"PAID_BANK": "paid", "IN_TRANSIT": "transit", "QUARANTINED": "quar"}.get(r["status"])
        if bucket:
            settle[k][bucket] += r["net"]

    gl: dict = defaultdict(lambda: ZERO)
    for r in legs["gl"]:
        # ACDOCA uses the German convention: S = Soll (debit), H = Haben (credit). ADR-007.
        gl[(r["mid"], r["day"])] += r["amount"] if r["dc"] == "S" else -r["amount"]

    out = {}
    for k in set(cap) | set(settle) | set(gl):            # the UNION spine: nothing is dropped
        c, s = cap.get(k, {"gross": ZERO, "back": ZERO}), settle.get(k, {})
        gross, back = c["gross"], c["back"]
        fees = s.get("fees", ZERO)
        paid, transit, quar = s.get("paid", ZERO), s.get("transit", ZERO), s.get("quar", ZERO)
        expected_net = gross - back - fees
        out[k] = {
            "bank_variance": expected_net - (paid + transit + quar),
            "gl_variance": (gross - back) - gl.get(k, ZERO),
        }
    return out


def breaks(result: dict) -> set[tuple[str, str]]:
    """The circuit breaker's view: any merchant-day where either variance is not exactly zero."""
    return {k for k, v in result.items() if v["bank_variance"] != ZERO or v["gl_variance"] != ZERO}


# ----------------------------------------------------------------------------- perturbations

def _copy(legs: dict) -> dict:
    return {k: [dict(r) for r in v] for k, v in legs.items()}


def halala_drift_on_a_capture(legs, rng):
    rows = [r for r in legs["captures"] if r["event_type"] == "CAPTURE"]
    r = rng.choice(rows)
    r["amount"] += Decimal("0.01")
    return (r["mid"], r["day"])


def halala_drift_on_a_fee(legs, rng):
    r = rng.choice(legs["settlements"])
    r["fees"] += Decimal("0.01")
    return (r["mid"], r["day"])


def dropped_settlement_line(legs, rng):
    r = rng.choice([x for x in legs["settlements"] if x["net"] != ZERO])
    legs["settlements"].remove(r)
    return (r["mid"], r["day"])


def duplicated_settlement_line(legs, rng):
    r = rng.choice([x for x in legs["settlements"] if x["net"] != ZERO])
    legs["settlements"].append(dict(r))
    return (r["mid"], r["day"])


def orphan_bank_line(legs, rng):
    """A bank line for a merchant-day with no capture at all: the row a LEFT JOIN would silently drop."""
    r = rng.choice(legs["settlements"])
    legs["settlements"].append({"mid": r["mid"], "day": "2099-01-01", "status": "PAID_BANK",
                                "net": Decimal("250.00"), "fees": Decimal("3.75")})
    return (r["mid"], "2099-01-01")


def gl_posting_drift(legs, rng):
    r = rng.choice(legs["gl"])
    r["amount"] += Decimal("0.01")
    return (r["mid"], r["day"])


SINGLE_SIDED = [halala_drift_on_a_capture, halala_drift_on_a_fee, dropped_settlement_line,
                duplicated_settlement_line, orphan_bank_line, gl_posting_drift]


# ----------------------------------------------------------------------------- the tests

def test_the_clean_slice_reconciles_before_anything_is_broken(legs):
    """Baseline. If this slice already breaks, every recall number below is meaningless."""
    assert breaks(recon(legs)) == set(), "the clean slice does not reconcile: the harness proves nothing"


def test_detection_recall_is_total_for_single_sided_faults(legs):
    """50 perturbations, one at a time, each on a fresh copy. Every one must surface as a break."""
    rng = random.Random(SEED)
    missed, by_class = [], defaultdict(lambda: [0, 0])
    for i in range(PERTURBATIONS):
        inject = SINGLE_SIDED[i % len(SINGLE_SIDED)]
        damaged = _copy(legs)
        hurt = inject(damaged, rng)
        caught = hurt in breaks(recon(damaged))
        by_class[inject.__name__][0] += 1
        by_class[inject.__name__][1] += int(caught)
        if not caught:
            missed.append((inject.__name__, hurt))

    report = "\n".join(f"  {name:<32} {hit}/{n}" for name, (n, hit) in sorted(by_class.items()))
    assert not missed, f"undetected perturbations -- the breaker has a blind spot:\n{report}\n{missed}"
    total = sum(n for n, _ in by_class.values())
    assert total == PERTURBATIONS
    print(f"\ndetection recall 1.000 over {total} single-sided perturbations:\n{report}")


def test_offsetting_same_day_errors_net_to_zero_at_daily_grain_and_are_caught_line_by_line(legs):
    """The blind spot, and the leg that closes it.

    +5.00 on one capture and -5.00 on another, same merchant, same day. The GROUP BY nets them to zero and
    the merchant-day row still reads SAR 0.00. **That half has not changed and cannot** -- no sum over a day
    can see two errors that cancel inside it, and asserting otherwise would be asserting against arithmetic.

    What changed on 2026-11-21 is that the build no longer relies on that sum alone. A line-level leg joins
    payment_event_id to its settlement line, where nothing is summed and the two errors cannot hide behind
    each other. Five reviewers raised this as the one criticism of "variance 0.00" that could not be argued
    away; this is the answer, and the test states both halves rather than only the flattering one.
    """
    rng = random.Random(SEED)
    damaged = _copy(legs)
    pool = [r for r in damaged["captures"] if r["event_type"] == "CAPTURE"]
    first = rng.choice(pool)
    same_day = [r for r in pool if (r["mid"], r["day"]) == (first["mid"], first["day"]) and r is not first]
    if not same_day:
        pytest.skip("no merchant-day in the slice carries two captures")
    second = rng.choice(same_day)

    assert not line_level_breaks(damaged), "the slice was already broken before anything was damaged"

    first["amount"] += Decimal("5.00")
    second["amount"] -= Decimal("5.00")

    assert (first["mid"], first["day"]) not in breaks(recon(damaged)), (
        "the merchant-day sum reported an offsetting pair, which it arithmetically cannot do -- the harness "
        "has stopped mirroring the model")
    assert line_level_breaks(damaged) == {first["event_id"], second["event_id"]}, (
        "the line-level leg missed an offsetting pair, which is the entire reason it exists")


def test_a_single_sided_five_riyal_error_on_the_same_day_is_caught(legs):
    """The control for the test above: one side alone is caught, so the blind spot is the offset, not the day."""
    rng = random.Random(SEED)
    damaged = _copy(legs)
    r = rng.choice([x for x in damaged["captures"] if x["event_type"] == "CAPTURE"])
    r["amount"] += Decimal("5.00")
    assert (r["mid"], r["day"]) in breaks(recon(damaged))


def test_no_float_enters_the_harness(legs):
    """Money stays Decimal here too, or the measurement would drift the way the thing it measures must not."""
    for leg in legs.values():
        for row in leg:
            for v in row.values():
                assert not isinstance(v, float), row

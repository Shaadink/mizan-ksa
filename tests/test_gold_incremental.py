"""ADR-015: the three incremental Gold facts, tested the only way incremental models can honestly be tested.

An incremental model is a cache, and every cache has the same failure mode: it is right on the day you
build it and wrong three weeks later, silently, for one key nobody looked at. A test that runs the model
once proves nothing at all -- the first run of an incremental model is just a full build.

So every test here runs the pipeline TWICE, with data arriving in between, and compares the incremental
result against what a full rebuild of the same Silver would have produced. That comparison is the whole
suite. If the two ever disagree, the incremental model is wrong, and it does not matter how plausible its
SQL looked.

The Silver fixtures are built by hand rather than generated, because the interesting cases are all about
ORDER OF ARRIVAL -- a bank file for Tuesday that lands on Friday, a payment event that turns up after the
bank line that settles it -- and the generator produces a tidy world where none of that happens.

`source_ingested_at` is set explicitly in every row for the same reason: it is the watermark, and a test
that let the clock set it could not tell "the model handled a late arrival" apart from "the test was
slow".
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("dbt")
pytest.importorskip("pyspark")
pytestmark = pytest.mark.spark

from test_gold_dbt import dbt_build, query  # noqa: E402  (after the importorskip guards; tests/ is on sys.path)

REPO = Path(__file__).resolve().parents[1]

# The three models under test, and the only dbt selection these tests build. Building the whole project
# would drag in the party, calendar and NDMO models, which need six more Silver tables and have nothing to
# do with incrementality.
#
# Named WITHOUT a `+` suffix on purpose: `fact_merchant_settlement_recon+` would also select
# mart_ndmo_scorecard, which reads it. dbt's default indirect selection already pulls in every test whose
# parents are here -- including assert_payment_methods_reconcile_to_recon, which is the strongest check in
# this file, because it compares the two incremental models against each other after every mutation.
MODELS = ("fact_merchant_settlement_recon", "fact_payment_method_daily", "fact_zatca_clearance_ledger")
SELECT = ("--select", *MODELS)

T0 = dt.datetime(2026, 2, 10, 3, 0, 0)      # first landing
T1 = dt.datetime(2026, 2, 11, 3, 0, 0)      # the late arrival, a day later
DAY = dt.date(2026, 2, 9)                   # the business day everything settles for
LATER = dt.date(2026, 2, 10)


def _money(x: str) -> Decimal:
    return Decimal(x)


# ----------------------------------------------------------------------------- Silver fixtures


def payment(pid: str, merchant: str, scheme: str, amount: str, *, day: dt.date = DAY,
            event: str = "CAPTURE", at: dt.datetime = T0) -> dict:
    return {"payment_event_id": pid, "order_id": f"O-{pid}", "invoice_uuid": None, "credit_note_uuid": None,
            "merchant_id": merchant, "store_id": "S1", "register_id": "R1", "event_type": event,
            "payment_scheme": scheme, "amount_sar": _money(amount),
            "event_ts": dt.datetime.combine(day, dt.time(12, 0)), "business_date_ksa": day,
            "source_batch_id": "B1", "source_ingested_at": at}


def settlement(pid: str, merchant: str, *, gross: str, fee: str, vat: str, net: str,
               status: str = "PAID_BANK", estimate: bool = False, day: dt.date = DAY,
               at: dt.datetime = T0, event: str = "CAPTURE") -> dict:
    return {"payment_event_id": pid, "merchant_id": merchant, "settlement_batch_id": "SB1",
            "settlement_for_date_ksa": day, "event_type": event, "gross_amount_sar": _money(gross),
            "acquirer_mdr_fee_sar": _money(fee), "acquirer_vat_sar": _money(vat),
            "net_settled_sar": _money(net), "settlement_status": status, "is_estimate": estimate,
            "source_ingested_at": at}


def gl_line(merchant: str, *, amount: str, dc: str = "S", day: dt.date = DAY, at: dt.datetime = T0,
            role: str = "CARD_CLEARING") -> dict:
    return {"merchant_id": merchant, "store_id": "S1", "posting_date_ksa": day, "gl_account": "113100",
            "gl_account_role": role, "debit_credit": dc, "amount_sar": _money(amount),
            "company_code": "1000", "ledger": "0L", "fiscal_year": "2026", "document_number": "D1",
            "line_item": "1", "profit_center": "PC1", "is_correction": False, "source_batch_id": "B1",
            "source_ingested_at": at}


def zatca_doc(uuid: str, *, state: str = "CLEARED", icv: int = 1, at: dt.datetime = T0) -> dict:
    return {"invoice_uuid": uuid, "request_id": f"R-{uuid}", "order_id": f"O-{uuid}", "egs_id": "EGS1",
            "icv": icv, "pih": "x", "invoice_hash": "y", "qr_tlv_b64": "z", "invoice_flow": "REPORTING",
            "document_type": "INVOICE", "state": state, "corrects_invoice_uuid": None, "gl_key": uuid,
            "total_incl_vat_sar": _money("115.00"), "issue_date_ksa": DAY, "attempts": 1,
            "source_ingested_at": at}


_SCHEMAS = {
    "payment_lifecycle": ("payment_event_id string, order_id string, invoice_uuid string, "
                          "credit_note_uuid string, merchant_id string, store_id string, register_id string, "
                          "event_type string, payment_scheme string, amount_sar decimal(18,2), "
                          "event_ts timestamp, business_date_ksa date, source_batch_id string, "
                          "source_ingested_at timestamp"),
    "settlement_lines": ("payment_event_id string, merchant_id string, settlement_batch_id string, "
                         "settlement_for_date_ksa date, event_type string, gross_amount_sar decimal(18,2), "
                         "acquirer_mdr_fee_sar decimal(18,2), acquirer_vat_sar decimal(18,2), "
                         "net_settled_sar decimal(18,2), settlement_status string, is_estimate boolean, "
                         "source_ingested_at timestamp"),
    "erp_gl_journal_lines": ("merchant_id string, store_id string, posting_date_ksa date, gl_account string, "
                             "gl_account_role string, debit_credit string, amount_sar decimal(18,2), "
                             "company_code string, ledger string, fiscal_year string, document_number string, "
                             "line_item string, profit_center string, is_correction boolean, "
                             "source_batch_id string, source_ingested_at timestamp"),
    "zatca_invoice_documents": ("invoice_uuid string, request_id string, order_id string, egs_id string, "
                                "icv int, pih string, invoice_hash string, qr_tlv_b64 string, "
                                "invoice_flow string, document_type string, state string, "
                                "corrects_invoice_uuid string, gl_key string, "
                                "total_incl_vat_sar decimal(18,2), issue_date_ksa date, attempts int, "
                                "source_ingested_at timestamp"),
}


class Silver:
    """A hand-built Silver lake that rows can be appended to between dbt runs."""

    def __init__(self, spark, root: Path):
        from mizan.spark.lake import Lake
        from mizan.spark.session import TableLocator
        self.spark, self.root = spark, root
        self.lake = Lake(spark, TableLocator("local", root))
        self.rows: dict[str, list[dict]] = {t: [] for t in _SCHEMAS}

    def add(self, table: str, *rows: dict) -> Silver:
        self.rows[table].extend(rows)
        return self

    def land(self) -> Silver:
        """Rewrite Silver from everything added so far -- which is exactly what the real build does.

        slv is a full recompute from an append-only Bronze (src/mizan/spark/silver.py), so "a late file
        arrived" means Silver is rebuilt and now contains more rows, not that rows were appended to it.
        Getting this wrong in the fixture would make the test easier than reality.
        """
        for table, schema in _SCHEMAS.items():
            df = self.spark.createDataFrame(self.rows[table] or [], schema=schema)
            self.lake.write(df, "slv", table, "overwrite", overwrite_schema=True)
        return self

    def replace(self, table: str, rows: list[dict]) -> Silver:
        self.rows[table] = rows
        return self


@pytest.fixture
def silver(spark, tmp_path):
    return Silver(spark, tmp_path / "lake")


# ----------------------------------------------------------------------------- build helpers


BREAKER = "assert_zero_unexplained_halala_variance"


def build(silver: Silver, tmp: Path, *, full_refresh: bool = False, allow: tuple[str, ...] = ()):
    """Build the three models and assert exactly which dbt tests failed -- usually none.

    `allow` exists for the orphan scenarios, and it is an assertion rather than a licence: a bank line
    with no payment behind it genuinely IS an unexplained variance, so the halala circuit breaker is
    SUPPOSED to trip while the orphan is outstanding, and supposed to stop once its payment arrives.
    Naming the expected failure makes the before-and-after part of the test instead of something the
    test has to be told to ignore.
    """
    duck = tmp / "gold.duckdb"
    extra = (*SELECT, "--full-refresh") if full_refresh else SELECT
    res, statuses = dbt_build(silver.root, duck, tmp, extra=extra)
    failed = {n for n, s in statuses.items() if s not in ("success", "pass")}
    assert failed == set(allow), f"unexpected dbt failures {failed - set(allow)}\n{res.output[-4000:]}"
    return duck


def rows_of(duck: Path, model: str) -> list[tuple]:
    sql = f"SELECT {projection(model)} FROM gld.{model} ORDER BY {ORDER[model]}"
    return query(duck, sql)


# The business columns of each model, in order: everything except last_source_arrival_at, which is
# wall-clock bookkeeping and differs between two builds of identical data by design.
BUSINESS = {
    "fact_merchant_settlement_recon": (
        "merchant_id", "business_date_ksa", "gross_captures_sar", "refunds_and_disputes_sar",
        "acquirer_fees_sar", "expected_net_payable_sar", "bank_paid_sar", "in_transit_sar",
        "quarantined_sar", "gl_card_clearing_sar", "unexplained_bank_variance_sar",
        "unexplained_gl_variance_sar", "unclassified_events"),
    "fact_payment_method_daily": (
        "merchant_id", "business_date_ksa", "payment_scheme", "payment_method", "capture_count",
        "gross_captures_sar", "refunds_and_disputes_sar", "acquirer_fees_sar", "fees_estimated_sar",
        "bank_paid_sar", "in_transit_sar", "quarantined_sar"),
    "fact_zatca_clearance_ledger": ("invoice_uuid", "state", "icv", "total_incl_vat_sar"),
}
ORDER = {"fact_merchant_settlement_recon": "1, 2", "fact_payment_method_daily": "1, 2, 3",
         "fact_zatca_clearance_ledger": "1"}
# Dates are compared as text so a DuckDB date and a Python date cannot disagree about equality.
DATE_COLUMNS = frozenset({"business_date_ksa", "issue_date_ksa"})


def projection(model: str) -> str:
    return ", ".join(f"CAST({c} AS VARCHAR)" if c in DATE_COLUMNS else c for c in BUSINESS[model])


def row_dict(model: str, row: tuple) -> dict:
    return dict(zip(BUSINESS[model], row, strict=True))


def snapshot(duck: Path) -> dict[str, list[tuple]]:
    return {m: rows_of(duck, m) for m in MODELS}


def incremental_vs_full(silver: Silver, tmp_path_factory, first_batch, second_batch,
                        first_allows: tuple[str, ...] = ()) -> dict:
    """Land, build, land more, build again -- then rebuild the same Silver from nothing and diff.

    Returns the agreed snapshot so a test can assert specific values on top. Any disagreement between the
    two is reported per model, because "the tables differ" is not a useful failure message at 2am.

    `first_allows` names dbt tests expected to fail on the FIRST build only. The second build and the
    full rebuild must both be clean, which is itself the assertion that the late arrival fixed things.
    """
    first_batch(silver)
    silver.land()
    inc_dir = tmp_path_factory.mktemp("inc")
    duck = build(silver, inc_dir, allow=first_allows)   # run 1: creates the tables
    second_batch(silver)
    silver.land()
    build(silver, inc_dir)                              # run 2: incremental, same database
    incremental = snapshot(duck)

    full_dir = tmp_path_factory.mktemp("full")
    full = snapshot(build(silver, full_dir, full_refresh=True))

    for model in MODELS:
        assert incremental[model] == full[model], (
            f"{model}: the incremental build disagrees with a full rebuild of the same Silver.\n"
            f"  incremental: {incremental[model]}\n  full       : {full[model]}")
    return incremental


# ----------------------------------------------------------------------------- the cases


def test_a_quiet_second_run_changes_nothing(silver, tmp_path_factory):
    """The base case, and the one most likely to be broken by a bad watermark.

    Nothing arrives between the two runs. If the cut-off were wrong in the generous direction the second
    run would rebuild everything (harmless but pointless); if it were wrong in the other direction the
    run could delete days and not put them back. Either way the comparison catches it.
    """
    def first(s):
        s.add("payment_lifecycle", payment("P1", "M1", "MADA", "100.00"))
        s.add("settlement_lines", settlement("P1", "M1", gross="100.00", fee="1.00", vat="0.15", net="98.85"))
        s.add("erp_gl_journal_lines", gl_line("M1", amount="100.00"))
        s.add("zatca_invoice_documents", zatca_doc("U1"))

    out = incremental_vs_full(silver, tmp_path_factory, first, lambda s: None)
    assert len(out["fact_merchant_settlement_recon"]) == 1


def test_a_late_bank_file_rebuilds_the_whole_day_instead_of_appending(silver, tmp_path_factory):
    """The headline case. Tuesday's bank file arrives on Friday.

    On run 1 the payment has no bank line, so it carries an IN_TRANSIT expectation row. On run 2 the real
    bank line has arrived and the expectation row is gone from Silver. The day must come back with ONE
    row holding the bank figure -- not two rows, and not the in-transit estimate still sitting there.
    """
    def first(s):
        s.add("payment_lifecycle", payment("P1", "M1", "MADA", "100.00"))
        s.add("settlement_lines", settlement("P1", "M1", gross="100.00", fee="1.00", vat="0.15",
                                             net="98.85", status="IN_TRANSIT", estimate=True))
        s.add("erp_gl_journal_lines", gl_line("M1", amount="100.00"))

    def late(s):
        # Silver is recomputed: the expectation row is REPLACED by the bank's own line, a day later.
        s.replace("settlement_lines", [settlement("P1", "M1", gross="100.00", fee="1.00", vat="0.15",
                                                  net="98.85", status="PAID_BANK", at=T1)])

    out = incremental_vs_full(silver, tmp_path_factory, first, late)
    recon = out["fact_merchant_settlement_recon"]
    assert len(recon) == 1, f"the day was appended to rather than rebuilt: {recon}"
    row = row_dict("fact_merchant_settlement_recon", recon[0])
    assert row["bank_paid_sar"] == Decimal("98.85")
    assert row["in_transit_sar"] == Decimal("0.00"), "the superseded in-transit estimate survived the rebuild"
    assert row["unexplained_bank_variance_sar"] == Decimal("0.00")


def test_late_payment_rescues_an_orphaned_bank_line(silver, tmp_path_factory):
    """The case that is invisible without the fourth 'changed' leg -- see ADR-015.

    A bank line arrives for a payment event that has not. It is QUARANTINED as an orphan. Later the
    payment lands. The SAME bank line now settles a known payment and becomes PAID_BANK -- but the line's
    own arrival time never moved, because it is the bank file's, and that file is old.

    A watermark that looked only at each table's own arrivals would never revisit this day, and the
    quarantined figure would stand forever. Nothing would raise. That is the whole point of the test.
    """
    def first(s):
        # M1 has a normal day. M2 has only an orphan bank line with no payment behind it.
        s.add("payment_lifecycle", payment("P1", "M1", "MADA", "100.00"))
        s.add("settlement_lines",
              settlement("P1", "M1", gross="100.00", fee="1.00", vat="0.15", net="98.85"),
              settlement("P9", "M2", gross="50.00", fee="0.50", vat="0.07", net="49.43",
                         status="QUARANTINED"))
        s.add("erp_gl_journal_lines", gl_line("M1", amount="100.00"))

    def late(s):
        # The missing payment lands a day later. Silver rebuilds and the orphan becomes a matched line --
        # at its ORIGINAL arrival time, which is the trap.
        s.add("payment_lifecycle", payment("P9", "M2", "VISA", "50.00", at=T1))
        s.replace("settlement_lines", [
            settlement("P1", "M1", gross="100.00", fee="1.00", vat="0.15", net="98.85"),
            settlement("P9", "M2", gross="50.00", fee="0.50", vat="0.07", net="49.43",
                       status="PAID_BANK")])          # note: still at=T0, the old bank file
        s.add("erp_gl_journal_lines", gl_line("M2", amount="50.00", at=T1))

    # Run 1 MUST trip the circuit breaker: M2 has 50.00 of bank money and no payment to explain it.
    # Run 2 must be clean, because the payment arrived and the day was revisited.
    out = incremental_vs_full(silver, tmp_path_factory, first, late, first_allows=(BREAKER,))
    by_merchant = {r[0]: r for r in out["fact_merchant_settlement_recon"]}
    assert "M2" in by_merchant
    m2 = row_dict("fact_merchant_settlement_recon", by_merchant["M2"])
    assert m2["quarantined_sar"] == Decimal("0.00"), (
        "the orphan stayed quarantined: the incremental build never revisited the day its payment arrived")
    assert m2["bank_paid_sar"] == Decimal("49.43")


def test_a_vanishing_scheme_row_is_removed_not_left_behind(silver, tmp_path_factory):
    """Why fact_payment_method_daily's unique_key is the DAY and not the grain (ADR-015 section 5).

    An orphan bank line is reported under the synthetic scheme UNMATCHED_BANK_LINE. When its payment
    arrives, the row must move to the real scheme and the UNMATCHED_BANK_LINE row must cease to exist.
    Keyed at the grain there would be nothing to overwrite it with and it would survive -- doubling the
    day's fees, which assert_payment_methods_reconcile_to_recon would then catch, but only after the
    wrong number had been published.
    """
    def first(s):
        s.add("settlement_lines", settlement("P9", "M2", gross="50.00", fee="0.50", vat="0.07",
                                             net="49.43", status="QUARANTINED"))

    def late(s):
        s.add("payment_lifecycle", payment("P9", "M2", "VISA", "50.00", at=T1))
        s.replace("settlement_lines", [settlement("P9", "M2", gross="50.00", fee="0.50", vat="0.07",
                                                  net="49.43", status="PAID_BANK")])
        # The ledger posts when the payment is recognised, so the GL line arrives with it. Without this
        # the day has a 50.00 GL variance and the circuit breaker is right to keep failing -- which is
        # how this fixture was caught being incomplete.
        s.add("erp_gl_journal_lines", gl_line("M2", amount="50.00", at=T1))

    out = incremental_vs_full(silver, tmp_path_factory, first, late, first_allows=(BREAKER,))
    schemes = {r[2] for r in out["fact_payment_method_daily"]}
    assert "UNMATCHED_BANK_LINE" not in schemes, (
        f"a scheme row that should no longer exist survived the rebuild: {out['fact_payment_method_daily']}")
    assert schemes == {"VISA"}


def test_a_new_day_does_not_disturb_the_days_already_built(silver, tmp_path_factory):
    """The saving has to be real: an untouched day must keep its row, untouched, not be rebuilt wrongly."""
    def first(s):
        s.add("payment_lifecycle", payment("P1", "M1", "MADA", "100.00"))
        s.add("settlement_lines", settlement("P1", "M1", gross="100.00", fee="1.00", vat="0.15", net="98.85"))
        s.add("erp_gl_journal_lines", gl_line("M1", amount="100.00"))

    def tomorrow(s):
        s.add("payment_lifecycle", payment("P2", "M1", "MADA", "200.00", day=LATER, at=T1))
        s.add("settlement_lines", settlement("P2", "M1", gross="200.00", fee="2.00", vat="0.30",
                                             net="197.70", day=LATER, at=T1))
        s.add("erp_gl_journal_lines", gl_line("M1", amount="200.00", day=LATER, at=T1))

    out = incremental_vs_full(silver, tmp_path_factory, first, tomorrow)
    days = sorted(r[1] for r in out["fact_merchant_settlement_recon"])
    assert days == ["2026-02-09", "2026-02-10"]


def test_a_zatca_document_that_reaches_a_verdict_later_enters_the_ledger(silver, tmp_path_factory):
    """The ledger holds only documents with a definitive outcome, so a document ARRIVES in it late.

    U2 is still SUBMITTING on run 1 and must not be in the ledger. It clears afterwards, with a bumped
    updated_at (the invariant ADR-015 names), and must then appear exactly once.
    """
    def first(s):
        s.add("zatca_invoice_documents", zatca_doc("U1", icv=1), zatca_doc("U2", state="SUBMITTING", icv=2))

    def verdict(s):
        s.replace("zatca_invoice_documents", [zatca_doc("U1", icv=1),
                                              zatca_doc("U2", state="CLEARED", icv=2, at=T1)])

    def first_only(s):
        first(s)

    silver_rows = incremental_vs_full(silver, tmp_path_factory, first_only, verdict)
    ledger = silver_rows["fact_zatca_clearance_ledger"]
    assert [r[0] for r in ledger] == ["U1", "U2"]
    assert [r[1] for r in ledger] == ["CLEARED", "CLEARED"]


def test_a_rejection_stays_in_the_ledger_and_is_not_overwritten(silver, tmp_path_factory):
    """A 400 keeps its ICV in the chain (CLAUDE.md). The correction is a NEW document, not an edit."""
    def first(s):
        s.add("zatca_invoice_documents", zatca_doc("U1", state="CONFIRMED_REJECTION", icv=1))

    def correction(s):
        s.add("zatca_invoice_documents", zatca_doc("U2", state="CLEARED", icv=2, at=T1))

    ledger = incremental_vs_full(silver, tmp_path_factory, first, correction)["fact_zatca_clearance_ledger"]
    assert [(r[0], r[1], r[2]) for r in ledger] == [("U1", "CONFIRMED_REJECTION", 1), ("U2", "CLEARED", 2)]


# ----------------------------------------------------------------------------- the configuration itself


def test_only_the_three_intended_models_are_incremental():
    """A guard against drift in both directions.

    Making dim_party_golden incremental would be a real bug -- retired profiles would pile up looking
    current -- and it is the kind of change that looks like a tidy-up. Equally, if one of the three
    quietly went back to a table the saving would vanish with nothing failing. ADR-015 holds the reasons.
    """
    gold = REPO / "dbt" / "models" / "gold"
    incremental = {p.stem for p in gold.glob("*.sql")
                   if "materialized = 'incremental'" in p.read_text(encoding="utf-8")}
    assert incremental == set(MODELS)
    for p in gold.glob("*.sql"):
        if p.stem not in MODELS:
            assert "STAYS A FULL TABLE" in p.read_text(encoding="utf-8"), (
                f"{p.name} is a table but does not say why; ADR-015 requires the reason in the file")


def test_the_watermark_cut_off_is_inclusive():
    """`>` instead of `>=` loses every row that shares a timestamp with the recorded maximum, and Bronze
    stamps a whole landing batch with one timestamp. It would be a one-character, silent, data-losing
    change, so it is pinned here rather than left to review."""
    for name in MODELS:
        sql = (REPO / "dbt" / "models" / "gold" / f"{name}.sql").read_text(encoding="utf-8")
        assert "source_ingested_at >= " in sql
        assert "source_ingested_at > " not in sql, f"{name} uses an exclusive cut-off"


def test_both_reconciliation_models_carry_the_late_payment_leg():
    """The fourth 'changed' leg from ADR-015. Without it an orphaned bank line never gets revisited, and
    no test of normal operation would notice. test_late_payment_rescues_an_orphaned_bank_line proves the
    behaviour; this proves the mechanism is present in both models that need it."""
    for name in ("fact_merchant_settlement_recon", "fact_payment_method_daily"):
        sql = (REPO / "dbt" / "models" / "gold" / f"{name}.sql").read_text(encoding="utf-8")
        assert "p.payment_event_id = s.payment_event_id" in sql, f"{name} is missing the late-payment leg"


def test_only_the_watermark_is_excused_from_the_dr_fingerprint():
    """Excluding a column from the DR drill weakens it, so the list stays at exactly one name."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dr_drill", REPO / "scripts" / "dr_drill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.EXCLUDED_COLUMNS == ("last_source_arrival_at",)

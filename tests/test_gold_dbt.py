"""Phase 4: Gold in dbt on the local DuckDB target (same models as the dbt-fabric target for WH_MIZAN).

Proves on generated data:
  * main build: every model and test passes, including the halala circuit breaker (I-05, I-06);
  * demo build (orphan settlement line + 0.01 float-drift GL line overlaid): the circuit breaker fails on
    EXACTLY the two planted MID-days and nothing else.
"""

import json
import os
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("dbt")
pytest.importorskip("pyspark")
pytestmark = pytest.mark.spark

DBT_DIR = Path(__file__).resolve().parents[1] / "dbt"


class BuildResult:
    def __init__(self, success: bool, output: str):
        self.success, self.output = success, output


def dbt_build(lake_root: Path, duck: Path, tmp: Path, project: Path = DBT_DIR, extra: tuple = ()):
    """Run `dbt build` in a child process: dbt-duckdb keeps its connection open for the life of the process,
    which would block the test's own read-only connection to the same file."""
    env = {**os.environ, "MIZAN_LAKE_ROOT": Path(lake_root).as_posix(), "MIZAN_DUCKDB_PATH": duck.as_posix(),
           "MIZAN_DBT_TARGET": "duckdb"}
    code = ("import sys; from dbt.cli.main import dbtRunner; "
            "r = dbtRunner().invoke(sys.argv[1:]); sys.exit(0 if r.success else 1)")
    args = ["build", "--project-dir", str(project), "--profiles-dir", str(project),
            "--target-path", str(tmp / "target"), "--log-path", str(tmp / "logs"), "--quiet", *extra]
    proc = subprocess.run([sys.executable, "-c", code, *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    results = json.loads((tmp / "target" / "run_results.json").read_text(encoding="utf-8"))["results"]
    statuses = {r["unique_id"].split(".")[2]: r["status"] for r in results}
    return BuildResult(proc.returncode == 0, proc.stdout + proc.stderr), statuses


def query(duck: Path, sql: str):
    import duckdb
    con = duckdb.connect(duck.as_posix(), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


@pytest.fixture(scope="session")
def gold_main(lake_run, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dbt_main")
    duck = tmp / "gold.duckdb"
    res, statuses = dbt_build(lake_run["root"], duck, tmp)
    return {"res": res, "statuses": statuses, "duck": duck}


@pytest.fixture(scope="session")
def gold_demo(lake_run, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dbt_demo")
    duck = tmp / "gold.duckdb"
    res, statuses = dbt_build(lake_run["demo_root"], duck, tmp)
    return {"res": res, "statuses": statuses, "duck": duck}


BREAKER = "assert_zero_unexplained_halala_variance"
BREAK_SQL = """SELECT merchant_id, CAST(business_date_ksa AS VARCHAR), unexplained_bank_variance_sar,
                      unexplained_gl_variance_sar, unclassified_events
               FROM gld.fact_merchant_settlement_recon
               WHERE unexplained_bank_variance_sar <> 0 OR unexplained_gl_variance_sar <> 0
                  OR unclassified_events > 0 ORDER BY 1, 2"""


def test_main_build_is_green(gold_main):
    assert gold_main["res"].success, {k: v for k, v in gold_main["statuses"].items() if v not in ("pass", "success")}
    assert gold_main["statuses"][BREAKER] == "pass"
    assert len(gold_main["statuses"]) >= 30


def test_main_recon_closes_to_zero_halala(gold_main):
    assert query(gold_main["duck"], BREAK_SQL) == []
    (rows, keys, captured, transit), = query(gold_main["duck"], """
        SELECT COUNT(*), COUNT(DISTINCT merchant_id || CAST(business_date_ksa AS VARCHAR)),
               SUM(gross_captures_sar), SUM(in_transit_sar) FROM gld.fact_merchant_settlement_recon""")
    assert rows == keys and rows > 2_000
    assert captured > Decimal("1000000") and transit > 0


def test_recon_identity_holds_row_by_row(gold_main):
    bad = query(gold_main["duck"], """
        SELECT COUNT(*) FROM gld.fact_merchant_settlement_recon
        WHERE expected_net_payable_sar <> bank_paid_sar + in_transit_sar + quarantined_sar
           OR gross_captures_sar - refunds_and_disputes_sar <> gl_card_clearing_sar""")
    assert bad == [(0,)]


def test_money_columns_are_decimal_18_2(gold_main):
    cols = query(gold_main["duck"], """
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'gld' AND table_name IN ('fact_merchant_settlement_recon', 'fact_zatca_clearance_ledger')
          AND column_name LIKE '%_sar'""")
    assert cols and all(t == "DECIMAL(18,2)" for _, t in cols), cols


def test_demo_build_fails_only_on_the_planted_breaks(gold_demo, manifest):
    assert not gold_demo["res"].success
    failing = {k for k, v in gold_demo["statuses"].items() if v in ("fail", "error")}
    assert failing == {BREAKER}                     # every other model and test still passes
    skipped = {k for k, v in gold_demo["statuses"].items() if v == "skipped"}
    assert skipped and all("mart_ndmo_scorecard" in k for k in skipped)   # the breaker stops downstream marts
    d05 = next(d for d in manifest["defects"] if d["id"] == "D05")["location"]
    d06 = next(d for d in manifest["defects"] if d["id"] == "D06")["location"]
    rows = query(gold_demo["duck"], BREAK_SQL)
    keys = {(r[0], r[1]) for r in rows}
    gl_date = f"{d06['posting_date'][:4]}-{d06['posting_date'][4:6]}-{d06['posting_date'][6:]}"
    assert keys == {(d05["merchant_id"], d05["settlement_for_date"]), (d06["merchant_id"], gl_date)}
    by_key = {(r[0], r[1]): r for r in rows}
    orphan = by_key[(d05["merchant_id"], d05["settlement_for_date"])]
    assert orphan[2] < 0 and orphan[3] == 0          # bank money with no capture behind it
    drift = by_key[(d06["merchant_id"], gl_date)]
    assert drift[3] == Decimal("0.01") and drift[2] == 0


def test_fact_zatca_clearance_ledger(gold_main):
    (n, rejected, corrections), = query(gold_main["duck"], """
        SELECT COUNT(*), SUM(CASE WHEN state = 'CONFIRMED_REJECTION' THEN 1 ELSE 0 END),
               SUM(CASE WHEN corrects_invoice_uuid IS NOT NULL THEN 1 ELSE 0 END)
        FROM gld.fact_zatca_clearance_ledger""")
    assert (n, rejected, corrections) == (25_000, 0, 1)   # 25,001 docs minus the retained rejection


def test_dim_date_saudi_weekend(gold_main):
    rows = dict(query(gold_main["duck"], """
        SELECT CAST(calendar_date AS VARCHAR), is_saudi_weekend FROM gld.dim_date_saudi
        WHERE calendar_date BETWEEN DATE '2026-02-12' AND DATE '2026-02-15'"""))
    assert rows == {"2026-02-12": 0, "2026-02-13": 1, "2026-02-14": 1, "2026-02-15": 0}   # Thu, Fri, Sat, Sun


# ---------------------------------------------------------------- Phase 5: Hijri calendar + golden parties

def test_dim_date_saudi_umm_al_qura(gold_main):
    rows = {r[0]: r[1:] for r in query(gold_main["duck"], """
        SELECT CAST(calendar_date AS VARCHAR), hijri_year, hijri_month, hijri_day, hijri_month_name, ramadan_day,
               is_override_adjusted
        FROM gld.dim_date_saudi WHERE calendar_date IN (DATE '2025-03-01', DATE '2026-02-17', DATE '2026-02-18',
                                                       DATE '2026-03-19', DATE '2026-03-20')""")}
    assert rows["2025-03-01"][:4] == (1446, 9, 1, "RAMADAN")
    assert rows["2026-02-17"][:3] == (1447, 8, 29)
    assert rows["2026-02-18"] == (1447, 9, 1, "RAMADAN", 1, 0)
    assert rows["2026-03-19"][:3] == (1447, 9, 30)
    assert rows["2026-03-20"][:4] == (1447, 10, 1, "SHAWWAL")
    (ramadan_days,), = query(gold_main["duck"], "SELECT COUNT(*) FROM gld.dim_date_saudi WHERE hijri_year = 1447 "
                                                "AND is_ramadan = 1")
    assert ramadan_days == 30


def test_hijri_announcement_override_renumbers_days(lake_run, tmp_path_factory):
    """Test-only override (not a real announcement): Ramadan 1447 announced one day later."""
    tmp = tmp_path_factory.mktemp("dbt_override")
    proj = tmp / "dbt"
    shutil.copytree(DBT_DIR, proj, ignore=shutil.ignore_patterns("target", "logs"))
    seed = proj / "seeds/hijri_announcement_overrides.csv"
    seed.write_bytes(seed.read_bytes() + b"1447,9,2026-02-19,TEST-FIXTURE-NOT-REAL,ANN_TEST_1\n")
    duck = tmp / "gold.duckdb"
    res, _ = dbt_build(lake_run["root"], duck, tmp, proj, ("--select", "+dim_date_saudi"))
    assert res.success, res.output[-2000:]
    rows = {r[0]: r[1:] for r in query(duck, """
        SELECT CAST(calendar_date AS VARCHAR), hijri_month, hijri_day, is_override_adjusted, calendar_version
        FROM gld.dim_date_saudi WHERE calendar_date BETWEEN DATE '2026-02-18' AND DATE '2026-03-20'
        ORDER BY 1""")}
    assert rows["2026-02-18"] == (8, 30, 1, "UAQ_DOTNET_V1+ANNOUNCEMENT")    # Shaban grows to 30 days
    assert rows["2026-02-19"][:3] == (9, 1, 1)
    assert rows["2026-03-19"][:2] == (9, 29)                              # Ramadan shrinks to 29 days
    assert rows["2026-03-20"] == (10, 1, 0, "UAQ_DOTNET_V1")              # Shawwal untouched


def test_dim_party_golden(gold_main, lake_run):
    (n, five, anchored, none_anchor), = query(gold_main["duck"], """
        SELECT COUNT(*), MAX(member_count), SUM(has_verified_anchor),
               SUM(CASE WHEN anchor_id_type = 'NONE' THEN 1 ELSE 0 END) FROM gld.dim_party_golden""")
    assert n == lake_run["first"]["mdm"]["goldens"] and five == 5
    assert anchored + none_anchor == n and none_anchor == lake_run["first"]["mdm"]["new_goldens_without_anchor"]
    pii_like = query(gold_main["duck"], """
        SELECT column_name FROM information_schema.columns WHERE table_schema = 'gld'
          AND table_name = 'dim_party_golden' AND (column_name LIKE '%name%' OR column_name LIKE '%hmac%'
               OR column_name LIKE '%enc' OR column_name LIKE '%mobile%' OR column_name LIKE '%token%')""")
    assert pii_like == []


# ---------------------------------------------------------------- Phase 6: NDMO scorecard + residency gate

def test_mart_ndmo_scorecard(gold_main):
    q = {r[0]: r[1:] for r in query(gold_main["duck"], """
        SELECT dimension, score_pct, status FROM gld.mart_ndmo_scorecard WHERE metric_family = 'DATA_QUALITY'""")}
    assert set(q) == {"COMPLETENESS", "UNIQUENESS", "VALIDITY", "CONSISTENCY", "TIMELINESS", "ACCURACY"}
    assert all(status == "PASS" for _, status in q.values()), q
    assert q["UNIQUENESS"][0] == Decimal("100.00") and q["CONSISTENCY"][0] == Decimal("100.00")
    split = query(gold_main["duck"], """
        SELECT subject_table, table_classification FROM gld.mart_ndmo_scorecard
        WHERE metric_family = 'CLASSIFICATION' AND status = 'SPLIT_RECOMMENDED' ORDER BY 1""")
    assert ("brz.crm_party_raw", "SECRET") in split


def test_residency_gate_passes_on_real_lake_and_gold(gold_main, lake_run, capsys):
    from mizan.governance.residency_gate import main
    assert main(["--lake", str(lake_run["root"]), "--duckdb", str(gold_main["duck"])]) == 0
    out = capsys.readouterr().out
    assert "0 violations" in out


# ---------------------------------------------------------------- Phase 9: agent answers money questions from Gold

def test_agent_money_answers_come_from_gold_sql(gold_main):
    from mizan.ai.governed import User, answer
    from mizan.spark.ai_land import duckdb_runner
    run = duckdb_runner(gold_main["duck"])
    cfo = User("cfo", frozenset({"CFO_OFFICE"}), "CONFIDENTIAL")
    a = answer("What is the total unexplained variance?", cfo, [], set(), run)
    assert a.route == "SQL" and a.rows == [(Decimal("0.00"), Decimal("0.00"), 0)]
    z = answer("How many invoices were cleared or reported, and the total amount?", cfo, [], set(), run)
    states = {r[0]: r[1] for r in z.rows}
    assert z.template == "ZATCA_TOTALS" and sum(states.values()) == 25_000
    junior = User("junior", frozenset({"ALL_STAFF"}), "PUBLIC")
    assert answer("What is the total unexplained variance?", junior, [], set(), run).refusal == "NOT_ENTITLED"


# ---------------------------------------------------------------- Phase 8: Gold column lineage, 100% (I-13)

def test_gold_column_lineage_is_complete(gold_main, lake_run, tmp_path):
    from mizan.lineage.openlineage import build, gold_events
    manifest = gold_main["duck"].parent / "target" / "manifest.json"
    doc = build(manifest, gold_main["duck"], lake_run["root"], tmp_path / "lineage.json")
    models = {"fact_merchant_settlement_recon", "fact_zatca_clearance_ledger", "dim_date_saudi", "dim_party_golden",
              "mart_ndmo_scorecard"}
    assert set(doc["column_lineage"]) == models
    for m in models:
        assert set(doc["column_lineage"][m]) == set(doc["columns"][f"gld.{m}"])        # every column covered
        assert all(doc["column_lineage"][m].values())
    recon = doc["column_lineage"]["fact_merchant_settlement_recon"]
    assert "slv.settlement_lines.acquirer_mdr_fee_sar" in recon["acquirer_fees_sar"]
    ev = gold_events(doc, "33333333-3333-3333-3333-333333333333")
    assert len(ev) == 2 * len(models) and all(e["run"]["facets"]["mizan_run"]["git_sha"] for e in ev)

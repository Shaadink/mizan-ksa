"""Phase 7, Module 7: 16-bucket salting + WALK_IN isolation (I-11: salted == unsalted, rows AND SAR checksum)."""

import pytest

pytest.importorskip("pyspark")
pytestmark = pytest.mark.spark


def test_salted_join_equals_plain_join_on_skewed_synthetic_data(spark):
    from pyspark.sql import functions as F

    from mizan.spark import skew as S
    facts, dim = S.skewed_facts(spark, 200_000), S.merchant_dim(spark)
    shares = {r[0]: r[1] for r in facts.groupBy(F.coalesce("merchant_id", F.lit("<NULL>"))).count().collect()}
    assert 0.63 < shares[S.MEGA_MID] / 200_000 < 0.67                       # the 65% mega-MID is really there
    assert shares["WALK_IN"] > 0 and shares["<NULL>"] > 0
    plain = S.plain_join(facts, dim, "merchant_id")
    salted = S.salted_join(facts, dim, "merchant_id")
    assert S.checksum(salted) == S.checksum(plain)
    cols = ["event_id", "merchant_id", "amount_sar", "channel", "city"]
    assert salted.select(*cols).exceptAll(plain.select(*cols)).count() == 0   # identical rows, not just totals
    assert salted.filter("merchant_id = 'WALK_IN' OR merchant_id IS NULL").filter("channel IS NOT NULL").count() == 0


def test_mega_mid_spreads_over_all_16_buckets(spark):
    from pyspark.sql import functions as F

    from mizan.spark import skew as S
    facts = S.skewed_facts(spark, 100_000).filter(F.col("merchant_id") == S.MEGA_MID)
    b = facts.groupBy(F.pmod(F.xxhash64("event_id"), F.lit(16)).alias("b")).count().collect()
    counts = sorted(r[1] for r in b)
    assert len(counts) == 16 and counts[-1] / counts[0] < 1.2                 # near-even spread


def test_salting_is_deterministic(spark):
    from mizan.spark import skew as S
    a = S.checksum(S.salted_join(S.skewed_facts(spark, 50_000), S.merchant_dim(spark), "merchant_id"))
    b = S.checksum(S.salted_join(S.skewed_facts(spark, 50_000), S.merchant_dim(spark), "merchant_id"))
    assert a == b


def test_salted_join_on_real_payment_lifecycle(lake):
    from pyspark.sql import functions as F

    from mizan.spark import skew as S
    pay = lake.read("slv", "payment_lifecycle").select("payment_event_id", "merchant_id", "amount_sar")
    top = pay.groupBy("merchant_id").count().orderBy(F.desc("count")).first()
    assert top["merchant_id"] == S.MEGA_MID and top["count"] == 11_688        # D12: the planted skew
    dim = pay.select("merchant_id").distinct().withColumn("channel", F.when(
        F.col("merchant_id") == S.MEGA_MID, "ECOM").otherwise("POS"))
    salted = S.salted_join(pay, dim, "merchant_id", salt_col="payment_event_id")
    assert S.checksum(salted) == S.checksum(S.plain_join(pay, dim, "merchant_id"))


def test_compaction_reduces_file_count(spark, tmp_path):
    from mizan.spark import skew as S
    r = S.compaction(spark, S.skewed_facts(spark, 20_000), tmp_path)
    assert r["files_before"] == 400 and r["files_after"] < 10


def test_record_benchmarks_into_audit(spark, tmp_path):
    import json
    from pathlib import Path

    from mizan.spark import skew as S
    from mizan.spark.lake import Lake, cleanup_staging
    from mizan.spark.session import TableLocator
    lk = Lake(spark, TableLocator("local", tmp_path))
    res = json.loads((Path(__file__).resolve().parents[1] / "docs/artifacts/05_skew_benchmark_20m.json")
                     .read_text(encoding="utf-8"))
    assert S.record_benchmarks(lk, res, "LOCAL_DOCKER_SPARK_3.5") == 4
    rows = {r["run_type"]: r for r in lk.read("audit", "benchmarks").collect()}
    assert rows["AQE_OFF"]["output_rows"] == rows["SALTED_16"]["output_rows"] == 20_000_000
    assert rows["AQE_OFF"]["sar_checksum"] == rows["SALTED_16"]["sar_checksum"]
    assert rows["COMPACTION"]["files_after"] < rows["COMPACTION"]["files_before"]
    cleanup_staging(spark)

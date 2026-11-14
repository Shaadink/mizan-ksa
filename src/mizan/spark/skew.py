"""Module 7: mega-MID skew. 16-bucket deterministic salting with dimension replication + WALK_IN/NULL isolation,
benchmarked against Spark AQE skew-join (I-11: salted output == unsalted baseline, rows AND SAR checksum).

    python -m mizan.spark.skew --rows 20000000 --out data/bench        # 3 runs: AQE off, AQE on, salted
Runs locally or in the Docker Spark image (docker/spark). Task-time statistics come from the Spark REST API, and
the Spark UI stays up at the end (--hold) so Artifact 5 screenshots can be captured.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

BUCKETS = 16
WALK_IN = "WALK_IN"
MEGA_MID = "MID900001"


def isolate_walk_in(df: DataFrame, key: str) -> tuple[DataFrame, DataFrame]:
    """NULL and WALK_IN keys never match a dimension row; keep them out of the join so they cannot pile onto one
    task, and add them back unchanged afterwards (row count and SAR preserved)."""
    walk = F.col(key).isNull() | (F.col(key) == WALK_IN)
    return df.filter(~walk), df.filter(walk)


def salted_join(facts: DataFrame, dim: DataFrame, key: str, *, salt_col: str = "event_id",
                buckets: int = BUCKETS) -> DataFrame:
    """facts LEFT JOIN dim on key, with each fact row given a deterministic salt (hash of its own id mod buckets)
    and each dimension row replicated once per salt. Same output as the plain join, spread over 16x more tasks."""
    keyed, walk = isolate_walk_in(facts, key)
    keyed = keyed.withColumn("_salt", F.pmod(F.xxhash64(F.col(salt_col)), F.lit(buckets)).cast("int"))
    dim_rep = dim.withColumn("_salt", F.explode(F.sequence(F.lit(0), F.lit(buckets - 1))))
    joined = keyed.join(dim_rep, [key, "_salt"], "left").drop("_salt")
    dim_cols = [c for c in dim.columns if c != key]
    walk = walk.select(*walk.columns, *[F.lit(None).cast(dim.schema[c].dataType).alias(c) for c in dim_cols])
    return joined.unionByName(walk)


def plain_join(facts: DataFrame, dim: DataFrame, key: str) -> DataFrame:
    return facts.join(dim, [key], "left")


def checksum(df: DataFrame, amount_col: str = "amount_sar") -> tuple[int, str]:
    r = df.agg(F.count("*").alias("n"), F.sum(amount_col).alias("s")).first()
    return int(r["n"]), str(r["s"])


# ----------------------------------------------------------------------------- synthetic skewed workload

def skewed_facts(spark: SparkSession, rows: int, *, merchants: int = 400, mega_share: float = 0.65,
                 walk_in_share: float = 0.05) -> DataFrame:
    """Deterministic (hash-based, no RNG state): 65% of rows on MID900001, 5% WALK_IN/NULL, rest spread."""
    u = (F.pmod(F.xxhash64(F.col("id"), F.lit("u")), F.lit(1_000_000)) / F.lit(1_000_000.0))
    other = F.concat(F.lit("MID"), F.lpad((F.pmod(F.xxhash64(F.col("id"), F.lit("m")), F.lit(merchants)) + 100001)
                                          .cast("string"), 6, "0"))
    mid = (F.when(u < mega_share, F.lit(MEGA_MID))
           .when(u < mega_share + walk_in_share / 2, F.lit(WALK_IN))
           .when(u < mega_share + walk_in_share, F.lit(None).cast("string"))
           .otherwise(other))
    cents = F.pmod(F.xxhash64(F.col("id"), F.lit("a")), F.lit(500_000)) + 100
    return (spark.range(rows).select(F.concat(F.lit("PE-"), F.col("id").cast("string")).alias("event_id"),
                                     mid.alias("merchant_id"),
                                     (cents.cast("decimal(18,0)") / 100).cast("decimal(18,2)").alias("amount_sar")))


def merchant_dim(spark: SparkSession, merchants: int = 400) -> DataFrame:
    """MID900001 (e-commerce) + `merchants` POS MIDs, built natively (no Python rows shipped to executors)."""
    i = F.col("id")
    mid = F.when(i == 0, F.lit(MEGA_MID)).otherwise(F.concat(F.lit("MID"), F.lpad((i + 100000).cast("string"), 6, "0")))
    cities = F.array(F.lit("Riyadh"), F.lit("Jeddah"), F.lit("Dammam"))
    city = F.element_at(cities, (F.pmod(i, F.lit(3)) + 1).cast("int"))
    return spark.range(merchants + 1).select(mid.alias("merchant_id"),
                                             F.when(i == 0, F.lit("ECOM")).otherwise(F.lit("POS")).alias("channel"),
                                             city.alias("city"))


# ----------------------------------------------------------------------------- benchmark

MODES = {
    "AQE_OFF": {"spark.sql.adaptive.enabled": "false"},
    "AQE_SKEW_JOIN": {"spark.sql.adaptive.enabled": "true", "spark.sql.adaptive.skewJoin.enabled": "true",
                      "spark.sql.adaptive.coalescePartitions.enabled": "true"},
    "SALTED_16": {"spark.sql.adaptive.enabled": "false"},
}


def _get_json(url: str, timeout: int = 30):
    if not url.startswith(("http://", "https://")):
        raise ValueError(url)
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (scheme checked above; local Spark UI)
        return json.load(r)


def _stage_task_stats(spark: SparkSession, job_group: str) -> dict:
    """Max / median task duration of the most skewed stage of this run, from the Spark REST API (UI must be on)."""
    ui = spark.sparkContext.uiWebUrl
    if not ui:
        return {}
    app = spark.sparkContext.applicationId
    try:
        jobs = _get_json(f"{ui}/api/v1/applications/{app}/jobs?status=succeeded")
        stage_ids = {s for j in jobs if j.get("jobGroup") == job_group for s in j["stageIds"]}
        worst = {}
        for sid in stage_ids:
            for st in _get_json(f"{ui}/api/v1/applications/{app}/stages/{sid}"):
                tasks = _get_json(
                    f"{ui}/api/v1/applications/{app}/stages/{sid}/{st['attemptId']}/taskList?length=10000")
                d = [t["duration"] for t in tasks if t.get("duration") is not None]
                if len(d) < 2:
                    continue
                ratio = round(max(d) / max(statistics.median(d), 1), 1)    # straggler factor of this stage
                if ratio > worst.get("skew_ratio", -1):
                    worst = {"stage_id": sid, "tasks": len(d), "skew_ratio": ratio, "max_task_ms": max(d),
                             "median_task_ms": int(statistics.median(d)),
                             "spill_bytes": sum(t.get("taskMetrics", {}).get("diskBytesSpilled", 0) for t in tasks)}
        return worst
    except Exception as e:                       # the benchmark result never depends on the UI being reachable
        return {"ui_error": type(e).__name__}


def run_benchmark(spark: SparkSession, rows: int, out: Path | None = None, partitions: int = 64) -> list[dict]:
    spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")    # force a shuffle join: the skew must show
    spark.conf.set("spark.sql.shuffle.partitions", str(partitions))
    facts, dim = skewed_facts(spark, rows), merchant_dim(spark)
    results = []
    for mode, conf in MODES.items():
        for k, v in conf.items():
            spark.conf.set(k, v)
        spark.sparkContext.setJobGroup(mode, f"skew benchmark {mode}")
        t0 = time.time()
        df = salted_join(facts, dim, "merchant_id") if mode == "SALTED_16" else plain_join(facts, dim, "merchant_id")
        n, s = checksum(df)
        results.append({"run_type": mode, "rows": rows, "duration_s": round(time.time() - t0, 2),
                        "output_rows": n, "sar_checksum": s, **_stage_task_stats(spark, mode)})
    spark.sparkContext.setJobGroup("COMPACTION", "small files then OPTIMIZE")
    if out is not None:
        results.append(compaction(spark, facts, out))
    return results


def compaction(spark: SparkSession, facts: DataFrame, out: Path) -> dict:
    """Write deliberately fragmented Delta files, then OPTIMIZE (bin-packing; VORDER is applied on Fabric)."""
    from delta.tables import DeltaTable
    path = (Path(out) / "skew_facts_delta").as_posix()
    facts.repartition(400).write.format("delta").mode("overwrite").save(path)
    files_before = DeltaTable.forPath(spark, path).detail().first()["numFiles"]
    DeltaTable.forPath(spark, path).optimize().executeCompaction()
    files_after = DeltaTable.forPath(spark, path).detail().first()["numFiles"]
    return {"run_type": "COMPACTION", "files_before": files_before, "files_after": files_after}


BENCH_COLS = ["run_type", "rows", "duration_s", "output_rows", "sar_checksum", "skew_ratio", "max_task_ms",
              "median_task_ms", "tasks", "spill_bytes", "files_before", "files_after", "substrate", "recorded_at"]


def record_benchmarks(lake, results: list[dict], substrate: str) -> int:
    """Append benchmark rows to audit.benchmarks (the JSON from a Docker run, or a Fabric run)."""
    from mizan.spark.lake import rows_to_df
    from mizan.spark.mdm_land import now_ksa
    rows = [{**{k: r.get(k) for k in BENCH_COLS}, "substrate": substrate, "recorded_at": now_ksa()} for r in results]
    lake.write(rows_to_df(lake.spark, BENCH_COLS, rows, {
        "rows": "long", "duration_s": "double", "output_rows": "long", "skew_ratio": "double", "max_task_ms": "long",
        "median_task_ms": "long", "tasks": "int", "spill_bytes": "long", "files_before": "int", "files_after": "int"}),
        "audit", "benchmarks", "append")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=2_000_000)
    ap.add_argument("--out", type=Path, default=Path("data/bench"))
    ap.add_argument("--partitions", type=int, default=64)
    ap.add_argument("--hold", type=int, default=0, help="seconds to keep the Spark UI up for screenshots")
    a = ap.parse_args()
    from mizan.spark.session import get_spark
    spark = get_spark("local", shuffle_partitions=a.partitions, ui=True)
    res = run_benchmark(spark, a.rows, a.out, a.partitions)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "benchmark_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))
    base = next(r for r in res if r["run_type"] == "AQE_OFF")
    for r in res:
        if "output_rows" in r:
            assert (r["output_rows"], r["sar_checksum"]) == (base["output_rows"], base["sar_checksum"]), r
    if a.hold:
        print(f"Spark UI at {spark.sparkContext.uiWebUrl} for {a.hold}s", flush=True)
        time.sleep(a.hold)


if __name__ == "__main__":
    main()

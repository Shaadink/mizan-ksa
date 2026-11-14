"""Thin helpers over Delta for LH_MIZAN tables (local paths or Fabric Lakehouse)."""

from __future__ import annotations

import csv
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mizan.spark.session import TableLocator, staging_root, staging_spark_path


def rows_to_df(spark, columns: list[str], rows: list[dict], casts: dict[str, str] | None = None):
    """Build a DataFrame from Python rows WITHOUT spawning Python workers (fragile + slow on Windows):
    write a UTF-8 staging CSV, read it natively, then cast. Binary values must be passed base64-encoded and
    declared as 'binary_b64' in casts. The DataFrame reads the staging file lazily (no cache, so no memory
    build-up); call cleanup_staging() once the run has written everything."""
    from pyspark.sql import functions as F
    from pyspark.sql import types as T
    base = staging_root()
    base.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(dir=base))
    f_path = stage / "rows.csv"
    with f_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    schema = T.StructType([T.StructField(c, T.StringType()) for c in columns])
    df = (spark.read.option("header", "true").option("multiLine", "true").option("escape", '"')
          .schema(schema).csv(staging_spark_path(f_path)))
    casts = casts or {}
    cols = []
    for c in columns:
        t = casts.get(c)
        if t == "binary_b64":
            cols.append(F.unbase64(F.col(c)).alias(c))
        elif t:
            cols.append(F.col(c).cast(t).alias(c))
        else:
            cols.append(F.col(c))
    return df.select(*cols)


def cleanup_staging(spark=None) -> None:
    """Remove staging files and drop cached data (end of a landing step / pipeline run)."""
    if spark is not None:
        spark.catalog.clearCache()
    shutil.rmtree(staging_root(), ignore_errors=True)


@dataclass
class Lake:
    spark: object
    loc: TableLocator

    def path(self, schema: str, table: str) -> str:
        return self.loc.path(schema, table).replace("\\", "/")

    def exists(self, schema: str, table: str) -> bool:
        from delta.tables import DeltaTable
        return DeltaTable.isDeltaTable(self.spark, self.path(schema, table))

    def read(self, schema: str, table: str):
        return self.spark.read.format("delta").load(self.path(schema, table))

    def write(self, df, schema: str, table: str, mode: str = "append", *, props: dict | None = None,
              constraints: dict | None = None, overwrite_schema: bool = False,
              merge_schema: bool = False) -> None:
        w = df.write.format("delta").mode(mode)
        if overwrite_schema:
            w = w.option("overwriteSchema", "true")
        if merge_schema:
            w = w.option("mergeSchema", "true")
        w.save(self.path(schema, table))
        if props:
            kv = ", ".join(f"'{k}' = '{v}'" for k, v in props.items())
            self.sql(schema, table, f"SET TBLPROPERTIES ({kv})")
        for name, expr in (constraints or {}).items():
            existing = self.spark.sql(f"DESCRIBE DETAIL delta.`{self.path(schema, table)}`").first()
            if f"delta.constraints.{name.lower()}" not in (existing["properties"] or {}):
                self.sql(schema, table, f"ADD CONSTRAINT {name} CHECK ({expr})")

    def sql(self, schema: str, table: str, alter_clause: str):
        return self.spark.sql(f"ALTER TABLE delta.`{self.path(schema, table)}` {alter_clause}")

    def list_tables(self, schema: str) -> list[str]:
        """Delta tables under one schema (Hadoop FS API: same code on local disk and OneLake)."""
        jvm, conf = self.spark._jvm, self.spark._jsc.hadoopConfiguration()
        base = jvm.org.apache.hadoop.fs.Path(self.path(schema, "_probe").rsplit("/", 1)[0])
        fs = base.getFileSystem(conf)
        if not fs.exists(base):
            return []
        names = [st.getPath().getName() for st in fs.listStatus(base) if st.isDirectory()]
        return sorted(n for n in names if self.exists(schema, n))

    def ref(self, schema: str, table: str) -> str:
        """SQL reference usable in spark.sql() for this table."""
        return f"delta.`{self.path(schema, table)}`"

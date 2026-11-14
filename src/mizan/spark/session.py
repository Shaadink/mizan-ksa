"""One Spark session factory for local and Fabric (spec: one codebase, Phase 3).

  get_spark("local")  - local[*] Spark 3.5 + Delta 3.2 (Fabric Runtime 1.3 parity). Uses the portable JDK and
                        winutils in .tools/ when present; sets env vars for THIS process only.
  get_spark("fabric") - inside a Fabric notebook the session already exists; reuse it, never reconfigure the
                        catalog. Schemas are addressed as LH_MIZAN.<schema>.<table>.
Both pin spark.sql.session.timeZone = Asia/Riyadh (build rule 1).

TableLocator hides the only real difference: where a table lives (local Delta path vs Lakehouse name).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from mizan import LAKEHOUSE, LAKEHOUSE_SCHEMAS, TIMEZONE

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / ".tools"


def _local_env() -> None:
    jdks = sorted(TOOLS.glob("jdk-17*"))
    if os.name == "nt" and jdks and "JAVA_HOME" not in os.environ:
        os.environ["JAVA_HOME"] = str(jdks[-1])
    hadoop = TOOLS / "hadoop"
    if os.name == "nt" and (hadoop / "bin" / "winutils.exe").exists():   # Windows only (not in Docker)
        os.environ.setdefault("HADOOP_HOME", str(hadoop))
        os.environ["PATH"] = str(hadoop / "bin") + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)


def get_spark(mode: str = "local", *, app: str = "mizan-ksa", shuffle_partitions: int = 8, ui: bool = False):
    from pyspark.sql import SparkSession

    mode = mode.strip().lower()
    if mode == "fabric":
        spark = SparkSession.builder.getOrCreate()
    elif mode == "local":
        _local_env()
        from delta import configure_spark_with_delta_pip

        builder = (SparkSession.builder.master("local[*]").appName(app)
                   .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
                   .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
                   .config("spark.jars.ivy", str(TOOLS / "ivy"))
                   # pin the driver to loopback: virtual adapters (WSL2/Docker) otherwise break hostname resolution
                   .config("spark.driver.host", "127.0.0.1")
                   .config("spark.driver.bindAddress", os.environ.get("MIZAN_SPARK_BIND", "127.0.0.1"))
                   .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
                   .config("spark.ui.enabled", "true" if ui else "false")
                   .config("spark.ui.showConsoleProgress", "false")
                   .config("spark.driver.memory", os.environ.get("MIZAN_DRIVER_MEMORY", "3g"))
                   .config("spark.sql.warehouse.dir", str(REPO / "tmp" / "spark-warehouse"))
                   .config("spark.databricks.delta.retentionDurationCheck.enabled", "false"))
        spark = configure_spark_with_delta_pip(builder).getOrCreate()
        spark.sparkContext.setLogLevel("ERROR")
    else:
        raise ValueError(f"unknown spark mode {mode!r}")
    spark.conf.set("spark.sql.session.timeZone", TIMEZONE)
    return spark


@dataclass(frozen=True)
class TableLocator:
    """Resolve schema.table to a Delta location (local) or a Lakehouse table name (Fabric)."""
    mode: str
    root: Path | None = None

    def __post_init__(self):
        if self.mode not in ("local", "fabric"):
            raise ValueError(self.mode)
        if self.mode == "local" and self.root is None:
            raise ValueError("local mode needs a root directory")
        if self.root is not None:
            object.__setattr__(self, "root", Path(self.root).resolve())  # Delta SQL needs absolute paths

    def _check(self, schema: str) -> None:
        if schema not in LAKEHOUSE_SCHEMAS:
            raise ValueError(f"{schema!r} is not an LH_MIZAN schema {LAKEHOUSE_SCHEMAS}")

    def path(self, schema: str, table: str) -> str:
        self._check(schema)
        if self.mode == "fabric":
            return f"Tables/{schema}/{table}"
        return (self.root / LAKEHOUSE / schema / table).as_posix()

    def name(self, schema: str, table: str) -> str:
        self._check(schema)
        return f"{LAKEHOUSE}.{schema}.{table}"

    def read(self, spark, schema: str, table: str):
        return spark.read.format("delta").load(self.path(schema, table))

    def exists(self, spark, schema: str, table: str) -> bool:
        from delta.tables import DeltaTable
        return DeltaTable.isDeltaTable(spark, self.path(schema, table))

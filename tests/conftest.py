import csv
import json
from pathlib import Path

import pytest

from mizan.generator import GenConfig, generate


@pytest.fixture(scope="session")
def gen_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("gen_a")
    generate(out, GenConfig())
    return out


@pytest.fixture(scope="session")
def manifest(gen_dir) -> dict:
    return json.loads((gen_dir / "defect_manifest.json").read_text(encoding="utf-8"))


def read_csv(path: Path, encoding: str = "utf-8") -> list[dict]:
    with path.open(encoding=encoding, newline="") as f:
        return list(csv.DictReader(f))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------- shared Spark lake (Phases 3-4)

@pytest.fixture(scope="session")
def spark():
    pytest.importorskip("pyspark")
    from mizan.spark.session import get_spark
    return get_spark("local", shuffle_partitions=4)


@pytest.fixture(scope="session")
def test_keys():
    import secrets

    from mizan.privacy import crypto
    return crypto.Keys(secrets.token_bytes(32), secrets.token_bytes(32))


@pytest.fixture(scope="session")
def lake_run(spark, gen_dir, test_keys, tmp_path_factory):
    """One full pipeline run (+ a full replay for I-12), and a demo copy with the overlay applied."""
    import shutil

    from mizan.spark import contracts as C
    from mizan.spark.bronze import land_files
    from mizan.spark.lake import Lake
    from mizan.spark.pipeline import run_pipeline
    from mizan.spark.session import TableLocator
    from mizan.spark.silver import build_erp_gl_journal_lines, build_settlement_lines
    root = tmp_path_factory.mktemp("lake")
    first = run_pipeline(gen_dir, root, spark=spark, keys=test_keys)
    lake = Lake(spark, TableLocator("local", root))
    snapshot = {t: lake.read(*t.split(".")).count()
                for t in ("brz.settlement_batches_raw", "brz.payment_events_raw", "brz.crm_party_raw",
                          "slv.settlement_lines", "slv.payment_lifecycle", "ctl.invoice_outbox",
                          "quarantine.schema_rejections")}
    demo_root = tmp_path_factory.mktemp("lake_demo")
    shutil.copytree(root, demo_root, dirs_exist_ok=True)
    demo = Lake(spark, TableLocator("local", demo_root))
    land_files(demo, test_keys, C.SETTLEMENT, [gen_dir / "demo/settlement_demo_orphan.csv"], gen_dir)
    gl_stats = land_files(demo, test_keys, C.ERP_GL, [gen_dir / "demo/erp_gl_demo_float_bug.csv"], gen_dir)[0]
    build_settlement_lines(demo, gen_dir)
    build_erp_gl_journal_lines(demo, gen_dir)
    from mizan.spark.lake import cleanup_staging
    cleanup_staging(spark)
    replay = run_pipeline(gen_dir, root, spark=spark, keys=test_keys)      # I-12: replay everything
    return {"root": root, "demo_root": demo_root, "first": first, "replay": replay, "snapshot": snapshot,
            "lake": lake, "demo_lake": demo, "demo_gl_stats": gl_stats}


@pytest.fixture(scope="session")
def lake(lake_run):
    return lake_run["lake"]

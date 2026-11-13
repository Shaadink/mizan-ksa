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

"""Stage 2: the owner-approved store reference seed is an unchanged copy of the generator's reference file."""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SEED = REPO / "dbt" / "seeds" / "merchant_store_reference.csv"


def test_seed_shape_and_ecommerce_mapping():
    rows = [ln.split(",") for ln in SEED.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == ["merchant_id", "store_id", "channel", "egs_id", "city", "register_count"]
    body = rows[1:]
    assert len(body) == 121 and len({r[0] for r in body}) == 121
    ecom = [r for r in body if r[2] == "ECOM"]
    assert ecom == [["MID900001", "ECOM", "ECOM", "EGS-05", "Riyadh", ecom[0][5]]]
    assert {r[4] for r in body} == {"Riyadh", "Jeddah", "Dammam", "Makkah", "Madinah"}


def test_seed_matches_the_generator_reference():
    src = REPO / "data" / "generated" / "reference" / "merchants.csv"
    if not src.exists():
        pytest.skip("generated data not present")
    assert SEED.read_bytes() == src.read_bytes()

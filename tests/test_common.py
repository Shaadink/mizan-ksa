import random
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mizan.common.money import fmt_sar, parse_sar, q2
from mizan.common.saudi_ids import (
    checksum_ok,
    mint_saudi_id,
    mint_unified_700,
    mint_vat_number,
    to_arabic_indic,
)

SRC = Path(__file__).resolve().parents[1] / "src"


def test_q2_refuses_float():
    with pytest.raises(TypeError):
        q2(0.1 + 0.2)


def test_q2_half_up():
    assert q2(Decimal("2.345")) == Decimal("2.35")
    assert q2(Decimal("2.344")) == Decimal("2.34")


def test_fmt_and_parse_round_trip():
    assert fmt_sar(Decimal("5")) == "5.00"
    assert parse_sar("1234.50") == Decimal("1234.50")
    for bad in ["1.5", "1e3", "abc", "1.234", ""]:
        with pytest.raises(ValueError):
            parse_sar(bad)


@given(st.integers(min_value=0, max_value=2**32))
def test_minted_ids_always_pass_checksum(seed):
    rng = random.Random(seed)
    for prefix in ("1", "2"):
        v = mint_saudi_id(rng, prefix)
        assert v[0] == prefix and checksum_ok(v)


def test_checksum_rejects_single_digit_error():
    v = mint_saudi_id(random.Random(1), "1")
    bad = v[:9] + str((int(v[9]) + 1) % 10)
    assert not checksum_ok(bad)


def test_vat_and_700_formats():
    rng = random.Random(3)
    vat = mint_vat_number(rng)
    assert len(vat) == 15 and vat[0] == "3" and vat[-1] == "3" and vat.isdigit()
    u = mint_unified_700(rng)
    assert len(u) == 10 and u[0] == "7"


def test_arabic_indic_digits():
    assert to_arabic_indic("1029") == "\u0661\u0660\u0662\u0669"


def test_no_raw_non_ascii_in_source():
    """CLAUDE.md: Arabic literals in code must be \\u escapes."""
    roots = [SRC, SRC.parent / "tests", SRC.parent / "scripts"]
    offenders = [str(p) for root in roots for p in root.rglob("*.py")
                 if any(ord(c) > 127 for c in p.read_text(encoding="utf-8"))]
    assert offenders == []

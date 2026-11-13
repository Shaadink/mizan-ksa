"""Halala-exact money helpers. Decimal only: a float anywhere in money is a bug (spec Module 3, I-06)."""

import re
from decimal import ROUND_HALF_UP, Decimal

HALALA = Decimal("0.01")
ZERO = Decimal("0.00")
_SAR_RE = re.compile(r"^-?[0-9]{1,16}\.[0-9]{2}$")


def q2(value: Decimal) -> Decimal:
    """Round to the halala, half-up. Refuses floats so binary drift can never enter."""
    if not isinstance(value, Decimal):
        raise TypeError(f"money must be Decimal, got {type(value).__name__}")
    return value.quantize(HALALA, rounding=ROUND_HALF_UP)


def fmt_sar(value: Decimal) -> str:
    """Canonical text form, always 2 decimals: Decimal('5') -> '5.00'."""
    return f"{q2(value):.2f}"


def parse_sar(text: str) -> Decimal:
    """Strict parse of a 2-decimal SAR string (fits DECIMAL(18,2))."""
    if not isinstance(text, str) or not _SAR_RE.fullmatch(text.strip()):
        raise ValueError(f"not a 2-decimal SAR amount: {text!r}")
    return Decimal(text.strip())

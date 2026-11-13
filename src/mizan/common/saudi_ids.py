"""Synthetic Saudi identifier minting (generator side).

The checksum is the spec's Module 4 algorithm: digits at even 0-based positions are doubled and
digit-summed, odd positions added as-is, total % 10 == 0. Validation lives in mizan.mdm (Phase 5);
this module only produces values that satisfy it.
"""

import random

ARABIC_INDIC_DIGITS = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
_TO_ARABIC_INDIC = str.maketrans("0123456789", ARABIC_INDIC_DIGITS)


def _luhn_partial(digits: str) -> int:
    return sum(((2 * int(c)) // 10 + (2 * int(c)) % 10) if i % 2 == 0 else int(c)
               for i, c in enumerate(digits))


def checksum_ok(id10: str) -> bool:
    return len(id10) == 10 and id10.isdigit() and _luhn_partial(id10) % 10 == 0


def mint_saudi_id(rng: random.Random, prefix: str) -> str:
    """prefix '1' = National ID (citizen), '2' = Iqama (resident)."""
    if prefix not in ("1", "2"):
        raise ValueError(f"prefix must be '1' or '2', got {prefix!r}")
    body = prefix + "".join(str(rng.randrange(10)) for _ in range(8))
    # index 9 is odd -> added as-is, so the check digit closes the total to a multiple of 10
    check = (10 - _luhn_partial(body) % 10) % 10
    out = body + str(check)
    assert checksum_ok(out)
    return out


def mint_vat_number(rng: random.Random) -> str:
    """15 digits, starts and ends with 3."""
    return "3" + "".join(str(rng.randrange(10)) for _ in range(13)) + "3"


def mint_unified_700(rng: random.Random) -> str:
    """700 Unified Number: format only (no public checksum is claimed)."""
    return "7" + "".join(str(rng.randrange(10)) for _ in range(9))


def to_arabic_indic(ascii_digits: str) -> str:
    return ascii_digits.translate(_TO_ARABIC_INDIC)

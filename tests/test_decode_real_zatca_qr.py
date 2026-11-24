"""The real-receipt QR decoder must not print a real business's identifiers by default.

`scripts/decode_real_zatca_qr.py` exists to run MIZAN's TLV decoder against a QR from a real Saudi
receipt, because the decoder had only ever been tested against invoices this project generated itself.
The payload names a real business -- tag 1 its registered name, tag 2 its VAT registration number -- so
the default output redacts both. That default is the thing worth pinning: the output of this script is
exactly the kind of thing that gets pasted into a README or a video frame.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

SELLER = "دار الميزان"   # an Arabic seller name
VATNO = "300055987200003"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "decode_real_zatca_qr", REPO / "scripts" / "decode_real_zatca_qr.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def payload():
    from mizan.clearance.tlv_qr_and_state_machine import build_qr_tlv_base64
    return build_qr_tlv_base64({
        1: SELLER, 2: VATNO, 3: "2026-11-24T20:19:40Z", 4: "55.00", 5: "7.17",
        6: "QdCmwkD8VB8msgMww6UbUqbbfD0zB5H6XeaBPrvlPMw=", 7: "MEUCIQD" + "A" * 80,
        8: bytes(range(33)), 9: bytes(range(64)),
    })


def test_identifiers_are_redacted_by_default(mod, payload, capsys) -> None:
    assert mod.report(payload, show_identifiers=False) == 0
    out = capsys.readouterr().out
    assert SELLER not in out, "the seller's name was printed; this output gets pasted into public places"
    assert VATNO not in out, "the VAT registration number was printed"
    assert "[redacted" in out


def test_identifiers_can_be_shown_deliberately(mod, payload, capsys) -> None:
    """The escape hatch must work, or someone will reach for a worse one."""
    assert mod.report(payload, show_identifiers=True) == 0
    out = capsys.readouterr().out
    assert SELLER in out
    assert VATNO in out


def test_a_short_value_is_still_reported_in_utf8_bytes(mod, payload, capsys) -> None:
    """The whole point of running this against a real receipt is the Arabic byte-length case.

    TLV length is the UTF-8 BYTE length, never the character count. An 11-character Arabic name is 21
    bytes, and a decoder that used character counts would mis-slice every field after it.
    """
    mod.report(payload, show_identifiers=False)
    out = capsys.readouterr().out
    assert "21 bytes" in out, "tag 1's length should be reported in UTF-8 bytes, not characters"
    assert "21 UTF-8 bytes for 11 characters" in out


def test_a_truncated_payload_is_reported_not_silently_accepted(mod, payload) -> None:
    import base64
    raw = base64.b64decode(payload)
    short = base64.b64encode(raw[: len(raw) // 2]).decode()
    with pytest.raises(Exception):  # noqa: B017 (any refusal is correct; silence is not)
        mod.report(short, show_identifiers=False)

"""The DPIA has to stay as honest as HONESTY.md, and it is the document most likely to drift optimistic.

A privacy assessment is written once, read by somebody senior, and then quietly outlived by the code. These
tests pin the three claims that would matter most if they stopped being true: that the DPIA still names the
residency finding, still says the agent API ships without caller authentication, and still says nobody has
reviewed it. If any of those is ever fixed, the fix is to change the code *and* this test together --
deliberately, not by editing a sentence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DPIA = REPO / "docs" / "compliance" / "DPIA.md"
HONESTY = REPO / "HONESTY.md"
FUNCTION = REPO / "apps" / "ask-agent" / "function_app.py"


@pytest.fixture(scope="module")
def dpia() -> str:
    return DPIA.read_text(encoding="utf-8")


def test_the_dpia_says_it_has_not_been_legally_reviewed(dpia):
    """The single most important sentence in it. A DPIA that reads as authoritative when nobody
    qualified has seen it is worse than no DPIA, because somebody may rely on it."""
    assert "self-assessed, not legally reviewed" in dpia
    assert "Reviewed by** | nobody" in dpia


def test_the_dpia_carries_the_residency_finding_that_honesty_carries(dpia):
    """Declared KSA, running in UAE North. If the DPIA ever stops saying so, it is selling something."""
    assert "UAE North" in dpia and "region: KSA" in dpia
    assert "blocking" in dpia, "the DPIA must say this blocks real personal data, not merely note it"
    assert "UAE North" in HONESTY.read_text(encoding="utf-8")


def test_the_dpia_and_the_function_agree_that_caller_auth_ships_off(dpia):
    """Two places describe the same switch. They must not disagree about which way it is set."""
    function = FUNCTION.read_text(encoding="utf-8")
    assert 'REQUIRE_AUTH = os.environ.get("REQUIRE_ENTRA_AUTH", "") == "1"' in function, (
        "verification must default to OFF; an opt-out would make the DPIA wrong")
    assert "shipped off" in dpia or "shipping it disabled" in dpia or "ships with token verification disabled" in dpia
    assert "It must be switched on before any" in dpia


def test_the_dpia_does_not_claim_rights_the_system_does_not_implement(dpia):
    """Four of six subject rights are absent. Claiming otherwise is the classic DPIA failure."""
    assert "Not implemented" in dpia
    assert "Four of six are absent" in dpia


def test_the_dpia_states_that_only_synthetic_data_has_been_processed(dpia):
    assert "synthetic throughout" in dpia
    assert "No real person's data has ever been processed" in dpia


def test_the_erasure_section_names_vacuum_and_the_restore_guard(dpia):
    """Crypto-shredding without VACUUM is theatre, and a DPIA that omits it is describing theatre."""
    assert "VACUUM" in dpia and "RETAIN 0 HOURS" in dpia.replace("zero-hour", "RETAIN 0 HOURS")
    assert "Restore Guard" in dpia and "must fail" in dpia


def test_the_residual_risks_are_ranked_and_open(dpia):
    """A risk register where everything is closed is a risk register nobody filled in."""
    table = dpia.split("## 9. Residual risks", 1)[1].split("## 10.", 1)[0]
    assert table.count("| Open") >= 5, "at least the known-open risks must still read as open"
    assert "**High**" in table

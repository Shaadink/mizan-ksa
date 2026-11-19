"""The dispute monitor's value is the count floor, so the floor is what gets tested.

A ratio on small volumes is noise: a merchant with 43 captures and 3 disputes reads 6.98% and means nothing.
The card-scheme programmes therefore judge a ratio AND a minimum dispute count, and so does the model. Drop the
floor and the model keeps returning rows while quietly becoming the naive version that flags most of the
portfolio -- it would not fail, it would just stop being useful. These tests fail instead.

The dbt test (dbt/tests/assert_dispute_floor_suppresses_small_merchants.sql) covers the built table; these cover
the exported figures the Command Center shows, which is where a reader meets the claim.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "command_center" / "data.json"


@pytest.fixture(scope="module")
def disputes() -> dict:
    if not DATA.exists():
        pytest.skip("command_center/data.json not built")
    d = json.loads(DATA.read_text(encoding="utf-8")).get("disputes")
    if not d:
        pytest.skip("disputes section not exported (Gold not built)")
    return d


def test_the_floor_changes_the_answer(disputes):
    """If the ratio and the floor agree, the panel is making a point it cannot support."""
    assert disputes["ratio_only"] > disputes["in_programme"], (
        "the count floor suppressed nothing: the panel's whole claim is that it does")


def test_the_naive_check_would_flag_most_of_the_portfolio(disputes):
    """The specific claim on screen: a ratio alone is not a control. Pin it to the data."""
    assert disputes["ratio_only"] / disputes["merchants"] > 0.5


def test_every_flagged_merchant_clears_both_thresholds(disputes):
    ratio = Decimal(disputes["thresholds"]["ratio_pct"])
    floor = disputes["thresholds"]["min_disputes"]
    assert disputes["flagged"], "nothing flagged: the monitor has no finding to show"
    for m in disputes["flagged"]:
        assert Decimal(m["ratio_pct"]) >= ratio, m
        assert m["disputes"] >= floor, m


def test_suppressed_examples_really_are_suppressed(disputes):
    """They must breach the ratio (else they prove nothing) and miss the floor (else they would be flagged)."""
    ratio = Decimal(disputes["thresholds"]["ratio_pct"])
    floor = disputes["thresholds"]["min_disputes"]
    assert disputes["suppressed_examples"]
    for m in disputes["suppressed_examples"]:
        assert Decimal(m["ratio_pct"]) >= ratio, m
        assert m["disputes"] < floor, m


def test_ratios_are_decimal_strings_not_floats(disputes):
    """Money and ratios are exported as strings; a float here would round differently on another machine."""
    for m in disputes["flagged"] + disputes["suppressed_examples"]:
        assert isinstance(m["ratio_pct"], str), m
    for m in disputes["flagged"]:
        assert isinstance(m["disputes_sar"], str), m


def test_the_window_is_declared_and_is_not_a_calendar_month(disputes):
    """The real programmes are monthly; this dataset is not. The panel must say so rather than imply a month."""
    assert disputes["window_days"] == 20
    assert len(disputes["window"]) == 2 and disputes["window"][0] < disputes["window"][1]
    assert "not a calendar month" in disputes["note"]


def test_the_note_does_not_claim_the_thresholds_are_authoritative(disputes):
    """They come from secondary sources and they move. The page must not imply a rulebook citation."""
    assert "secondary sources" in disputes["note"] and "not the scheme rulebooks" in disputes["note"]

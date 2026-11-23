"""The documents a reader opens first must agree with Gold. This fails the build when they drift.

Why this exists: the project's rule is that every figure is generated, never typed, and the rule had been
applied to the Command Center but not to README.md or docs/ONE_PAGER.md. Both carried "76 / 76" Gold columns
in their headline table while the real number was 91 -- and ONE_PAGER.md contradicted itself thirty-four lines
later. External reviewers found it. A hand-maintained number in a front page is a number that will be wrong
eventually, so the check is automated rather than promised.

Scope, deliberately narrow: the headline claims a stranger reads in the first ten seconds. Prose elsewhere can
discuss a figure in context (including the superseded Fabric run, which is cited on purpose) without tripping
this. The canonical values come from scripts/facts.py, which reads Gold.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from facts import facts  # noqa: E402

FRONT_PAGES = ("README.md", "docs/ONE_PAGER.md")


@pytest.fixture(scope="module")
def f() -> dict:
    return facts()


def _text(rel: str) -> str:
    p = REPO / rel
    if not p.exists():
        pytest.skip(f"{rel} not present")
    return p.read_text(encoding="utf-8")


def _grouped(n: int) -> str:
    return f"{n:,}"


@pytest.mark.parametrize("rel", FRONT_PAGES)
def test_gold_columns_traced_is_current(rel, f):
    """The exact failure that shipped: a stale "76 / 76" in the headline table while Gold had 91."""
    text = _text(rel)
    n = f["gold_columns_traced"]
    assert re.search(rf"\b{n}\s*/\s*{n}\b", text), f"{rel} does not state the current {n}/{n} Gold columns"
    stale = [m for m in re.findall(r"\b(\d{2,3})\s*/\s*\1\b", text) if int(m) != n and int(m) in (64, 76)]
    assert not stale, f"{rel} still carries a superseded Gold column count: {sorted(set(stale))}"


@pytest.mark.parametrize("rel", FRONT_PAGES)
def test_adr_range_matches_the_adr_directory(rel, f):
    """ADR-014 was added and both front pages still pointed at ADR-013."""
    text = _text(rel)
    claimed = re.findall(r"ADR-001\s*(?:to|\u2026|\.\.\.|-)\s*(?:ADR-)?0*(\d{1,3})", text)
    assert claimed, f"{rel} does not state an ADR range"
    for c in claimed:
        assert int(c) == f["adr_count"], (
            f"{rel} claims ADR-001..{c} but docs/adr/ holds {f['adr_count']} ADRs")


@pytest.mark.parametrize("rel", FRONT_PAGES)
def test_merchant_day_split_is_stated_and_adds_up(rel, f):
    """"2,121 assessed" invites "out of what?". The front page must answer it, and the answer must reconcile."""
    text = _text(rel)
    assessed, active = _grouped(f["assessed_mid_days"]), _grouped(f["active_mid_days"])
    assert assessed in text, f"{rel} does not state the assessed merchant-days ({assessed})"
    assert active in text or str(f["active_mid_days"]) in text, (
        f"{rel} states {assessed} assessed without the {active} denominator it is drawn from")
    assert f["assessed_mid_days"] + f["in_transit_mid_days"] == f["active_mid_days"]


@pytest.mark.parametrize("rel", FRONT_PAGES)
def test_the_superseded_fabric_figure_never_stands_unlabelled(rel, f):
    """It is legitimate to cite the earlier Fabric run. It is not legitimate to show it as the current number."""
    text = _text(rel)
    prior = f["prior_fabric_gross_sar"]
    pretty = f"{int(float(prior)):,}" + prior[-3:]
    for line in text.splitlines():
        if pretty not in line and prior not in line:
            continue
        lowered = line.lower()
        assert any(w in lowered for w in ("prior", "earlier", "predates", "superseded", "pending", "honesty")), (
            f"{rel} shows the superseded Fabric figure {pretty} with nothing on the line marking it stale:"
            f"\n  {line.strip()}")


def test_in_transit_money_matches_gold(f):
    """The number the whole thesis rests on: the money we refuse to call reconciled."""
    transit = f["in_transit_sar"]
    pretty = f"{int(float(transit)):,}" + transit[-3:]
    for rel in FRONT_PAGES:
        text = _text(rel)
        assert pretty in text or transit in text, f"{rel} does not state the in-transit SAR ({pretty})"


def test_variances_are_zero_or_the_headline_is_false(f):
    """If this ever fails, the front page is lying and the build must stop before anyone reads it."""
    assert f["bank_variance_sar"] == "0.00"
    assert f["gl_variance_sar"] == "0.00"
    assert f["unclassified_events"] == 0


def test_claimed_python_test_count_matches_the_suite() -> None:
    """Every front page states a Python test count. Collect the suite and check they are telling the truth.

    This number drifted twice. The LinkedIn draft said 302 when the suite collected 444, and once that was
    corrected the docs said 444 while the suite had grown to 460 -- exactly the sixteen tests added that
    week. Both times the number was wrong on the README a recruiter reads, and both times only a human
    noticed. A count that is asserted nowhere is a count that rots.

    Collection, not execution: `--collect-only` imports the test modules and counts, so this costs about a
    second and cannot recurse, because collecting never runs a test body.
    """
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=600)
    match = re.search(r"(\d+)\s+tests? collected", out.stdout)
    assert match, f"could not read a collected count from pytest:\n{out.stdout[-2000:]}"
    collected = int(match.group(1))

    claimed_in: dict[str, set[int]] = {}
    for rel in ("README.md", "docs/ONE_PAGER.md", "docs/PROJECT_IN_PLAIN_ENGLISH.md",
                "docs/linkedin/LINKEDIN_POST.md", "docs/linkedin/MASTER_BRIEF.md",
                "docs/linkedin/VIDEO_PLAN.md"):
        text = _text(rel)
        # Four phrasings are in use across the front pages, and the first version of this test only knew
        # two of them -- so ONE_PAGER and PROJECT_IN_PLAIN_ENGLISH would have rotted silently while the
        # test stayed green. A guard that checks some of the places is worse than no guard, because it
        # reads as coverage.
        found = {int(n) for n in re.findall(r"(\d{3,4})\s*(?:\*\*)?\s*Python tests", text)}
        found |= {int(n) for n in re.findall(r"\|\s*Python tests\s*\|\s*(\d{3,4})", text)}
        found |= {int(n) for n in re.findall(r"(\d{3,4})\s*(?:\*\*)?\s*Python\s*[,+]", text)}
        found |= {int(n) for n in re.findall(r"(\d{3,4})\s*(?:\*\*)?\s*automated tests", text)}
        if found:
            claimed_in[rel] = found

    assert claimed_in, "no front page states a Python test count any more -- the claim was dropped, not fixed"
    wrong = {rel: sorted(v) for rel, v in claimed_in.items() if v != {collected}}
    assert not wrong, (
        f"the suite collects {collected} Python tests, but these pages claim otherwise: {wrong}. "
        f"Update the pages (not this test) -- the number is on the README recruiters read.")

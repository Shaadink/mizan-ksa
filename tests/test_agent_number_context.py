"""Prove the agent rejects a real number attached to the wrong metric.

HONESTY row 15 admitted the number check was lexical: it proved a number appeared in some tool result, and
could not prove the number was used in the right sentence. Every external reviewer named this, and the failure
they described is specific and cheap to demonstrate -- "SAR 1,125,209.07 reconciled" passes a lexical check
while asserting the opposite of the truth, because that figure is the money still in transit and explicitly
NOT reconciled. The entire thesis of the project is that distinction.

`verify_number_context` closes it by reading tool results as labelled facts and checking each number against
the words around it. These tests pin the behaviour that matters: the swap must fail, the correct statement must
pass, and the check must not become so eager that it rejects honest prose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "ask-agent"))

agent = pytest.importorskip("agent_core")

# One realistic tool result. The two values are the ones a reader must never see swapped.
TOOL = [{"role": "tool", "tool_call_id": "c1", "content": json.dumps({
    "bank_paid_sar": "19503614.17",
    "in_transit_sar": "1125209.07",
    "gross_captures_sar": "22391236.23",
    "unexplained_bank_variance_sar": "0.00",
    "assessed_mid_days": 2121,
})}]


def test_the_swap_is_rejected():
    """The exact misstatement the lexical check could not see."""
    answer = "The bank reconciled SAR 1,125,209.07 with no variance."
    assert agent.verify_numbers(answer, TOOL) == [], "precondition: the number IS in a tool result"
    bad = agent.verify_number_context(answer, TOOL)
    assert bad, "a real number presented as a metric it is not was accepted"
    assert "1,125,209.07" in bad[0]


def test_the_other_direction_is_rejected_too():
    """Bank-paid money described as still in transit is the same error mirrored."""
    answer = "SAR 19,503,614.17 has not arrived yet and is still in transit."
    assert agent.verify_numbers(answer, TOOL) == []
    assert agent.verify_number_context(answer, TOOL)


def test_the_correct_statement_passes():
    """The check must not simply reject everything: the true sentence has to survive it."""
    answer = ("The bank paid SAR 19,503,614.17 and SAR 1,125,209.07 is still in transit, "
              "so the unexplained variance is SAR 0.00.")
    assert agent.verify_numbers(answer, TOOL) == []
    assert agent.verify_number_context(answer, TOOL) == []


def test_a_number_with_no_metric_named_nearby_is_left_alone():
    """Scope discipline: this check catches misattribution, it does not police prose style."""
    answer = "There are 2121 of them."
    assert agent.verify_number_context(answer, TOOL) == []


def test_a_fabricated_number_is_still_caught_by_the_lexical_check():
    """The two checks cover different failures; neither replaces the other."""
    answer = "The bank paid SAR 19,503,614.18."
    assert agent.verify_numbers(answer, TOOL) == ["19,503,614.18"]


def test_labelled_facts_survive_nesting():
    """A tool that nests its payload must not be able to hide a label from the binder."""
    nested = [{"role": "tool", "tool_call_id": "c2", "content": json.dumps(
        {"rows": [{"metrics": {"in_transit_sar": "1125209.07"}}]})}]
    facts = agent.labelled_tool_facts(nested)
    from decimal import Decimal
    assert Decimal("1125209.07") in facts["in_transit"]


def test_no_labelled_facts_means_the_check_stands_down():
    """With nothing to bind against, the lexical check is the only honest guarantee -- do not invent one."""
    plain = [{"role": "tool", "tool_call_id": "c3", "content": "19503614.17"}]
    assert agent.verify_number_context("The bank reconciled SAR 19,503,614.17.", plain) == []

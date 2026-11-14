"""Phase 9, Module 8 (pure Python): chunk ACL inheritance, pre-retrieval entitlement filter, tombstone
suppression, money questions only via read-only Gold SQL, refusals audited without the question text."""

from decimal import Decimal
from pathlib import Path

import pytest

from mizan.ai import governed as A

POLICIES = Path(__file__).resolve().parents[1] / "docs" / "policies"
JUNIOR = A.User("junior.analyst", frozenset({"CUSTOMER_CARE"}), "PUBLIC")
FINANCE = A.User("finance.lead", frozenset({"FINANCE"}), "CONFIDENTIAL")
DPO = A.User("dpo", frozenset({"DPO"}), "CONFIDENTIAL")


@pytest.fixture(scope="module")
def chunks():
    out = []
    for p in sorted(POLICIES.glob("*.md")):
        out += A.chunk_policy(p.read_text(encoding="utf-8"))
    return out


def test_chunks_inherit_tier_and_acl_and_markers_only_raise(chunks):
    by_doc = {}
    for c in chunks:
        by_doc.setdefault(c.doc_id, []).append(c)
    assert {c.classification for c in by_doc["POL-REFUND-001"]} == {"PUBLIC"}
    assert {c.acl_groups for c in by_doc["POL-FIN-MDR-002"]} == {("CFO_OFFICE", "FINANCE")}
    runbook = {c.section: c.classification for c in by_doc["POL-PDPL-003"]}
    assert runbook["Restore guard"] == "SECRET" and runbook["Intake"] == "CONFIDENTIAL"
    assert {c.lang for c in chunks} == {"EN", "AR"}


def test_unknown_classification_fails_closed():
    with pytest.raises(ValueError):
        A.chunk_policy("---\ndoc_id: X\ntitle: t\nclassification: INTERNAL\nacl_groups: ALL_STAFF\n---\n# a\nb")


def test_junior_is_refused_confidential_material(chunks):
    a = A.answer("What is our negotiation position on the MDR with the acquirer?", JUNIOR, chunks, set())
    assert a.route == "REFUSED" and a.refusal == "NOT_ENTITLED" and a.chunks == []
    assert "65" not in a.text                                     # nothing of the restricted chunk leaks


def test_finance_gets_the_same_answer_from_entitled_chunks(chunks):
    a = A.answer("What is our negotiation position on the MDR with the acquirer?", FINANCE, chunks, set())
    assert a.route == "RAG" and all(c.startswith("POL-FIN-MDR-002") for c in a.chunks[:1])


def test_filter_happens_before_ranking(chunks):
    a = A.answer("How do we execute the erasure and keep legal hold evidence?", DPO, chunks, set())
    assert a.route == "RAG" and "POL-PDPL-003#3" not in a.chunks    # SECRET section never ranked for the DPO
    b = A.answer("restore guard escalation contacts after a backup restore", DPO, chunks, set())
    assert b.route == "REFUSED" and b.refusal == "NOT_ENTITLED"     # only the SECRET section could answer


def test_arabic_question_retrieves_arabic_policy(chunks):
    q = ("\u0645\u0627 \u0647\u064A \u0645\u062F\u0629 \u0625\u0631\u062C\u0627\u0639 "
         "\u0627\u0644\u0645\u0646\u062A\u062C\u0627\u062A")
    a = A.answer(q, JUNIOR, chunks, set())
    assert a.route == "RAG" and a.chunks[0] == "POL-REFUND-001#3"


def test_tombstoned_subject_chunks_are_suppressed():
    note = A.Chunk("CASE-1#1", "CASE-1", "Return case", "notes", "EN", "return request refund for damaged lantern",
                   "PUBLIC", ("ALL_STAFF",), subject_token_id="sub_erased")
    assert A.answer("refund damaged lantern", JUNIOR, [note], set()).route == "RAG"
    a = A.answer("refund damaged lantern", JUNIOR, [note], {"sub_erased"})
    assert a.route == "REFUSED" and a.refusal == "NO_MATCH"        # suppressed, and not even hinted at


def test_money_questions_go_to_gold_sql_never_to_text(chunks):
    seen = []

    def run_sql(sql):
        seen.append(sql)
        return [(Decimal("0.00"), Decimal("0.00"), 0)]
    a = A.answer("What is the total unexplained variance?", FINANCE, chunks, set(), run_sql)
    assert a.route == "SQL" and a.tables == ["fact_merchant_settlement_recon"] and a.template == "RECON_VARIANCE"
    assert seen and a.rows == [(Decimal("0.00"), Decimal("0.00"), 0)]
    j = A.answer("What is the total unexplained variance?", JUNIOR, chunks, set(), run_sql)
    assert j.route == "REFUSED" and j.refusal == "NOT_ENTITLED" and len(seen) == 1
    t = A.answer("What is the total of the MDR mentioned in the policy text?", FINANCE, chunks, set(), run_sql)
    assert t.route == "REFUSED" and t.refusal == "TEXT_MATH_FORBIDDEN"


@pytest.mark.parametrize("sql", [
    "DELETE FROM gld.fact_merchant_settlement_recon",
    "SELECT * FROM gld.fact_merchant_settlement_recon; DROP TABLE x",
    "SELECT * FROM slv.settlement_lines",
    "SELECT * FROM security.pii_vault_metadata",
    "SELECT * FROM gld.dim_party_golden",
    "SELECT * INTO gld.copy FROM gld.fact_merchant_settlement_recon",
    "SELECT 1 -- FROM gld.fact_merchant_settlement_recon",
    "WITH x AS (SELECT * FROM brz.crm_party_raw) SELECT * FROM x",
])
def test_sql_guard_rejects(sql):
    with pytest.raises(ValueError):
        A.validate_readonly_sql(sql, A.GOLD_ACL)


def test_sql_guard_accepts_templates_and_ctes():
    for _, _, sql in A.SQL_TEMPLATES:
        assert A.validate_readonly_sql(sql, A.GOLD_ACL)
    assert A.validate_readonly_sql("WITH x AS (SELECT * FROM gld.dim_date_saudi) SELECT * FROM x",
                                   A.GOLD_ACL) == ["dim_date_saudi"]


def test_audit_row_never_stores_question_text(chunks):
    q = "What is our negotiation position on the MDR?"
    row = A.audit_row(q, JUNIOR, A.answer(q, JUNIOR, chunks, set()), "2026-11-14T00:00:00+03:00")
    assert q not in row.values() and len(row["question_sha256"]) == 64 and row["route"] == "REFUSED"

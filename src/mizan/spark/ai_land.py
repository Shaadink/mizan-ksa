"""Module 8 in the lakehouse: ai.policy_chunks (policies + per-customer case notes) and ai.agent_audit_log.

Policy chunks inherit tier + ACL from their document. Case notes come from RETURN_REQUESTED events and carry the
subject token, so an erased subject's chunks are dropped at index time AND filtered at question time (a restored
index cannot serve them either). No cleartext PII: case notes are built from non-PII event columns only.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pyspark.sql import functions as F

from mizan.ai import governed as A
from mizan.spark.lake import Lake, rows_to_df
from mizan.spark.mdm_land import now_ksa

REPO = Path(__file__).resolve().parents[3]
POLICIES = REPO / "docs" / "policies"
CHUNK_COLS = ["chunk_id", "chunk_kind", "doc_id", "title", "section", "lang", "text", "classification", "acl_groups",
              "subject_token_id", "doc_version"]
AUDIT_COLS = ["asked_at", "user_name", "user_clearance", "question_sha256", "route", "refusal_reason", "chunk_ids",
              "tables", "sql_template"]


def tombstones(lake: Lake) -> set[str]:
    if not lake.exists("ctl", "deletion_tombstones"):
        return set()
    return {r[0] for r in lake.read("ctl", "deletion_tombstones").select("subject_token_id").collect()}


def case_note_chunks(lake: Lake, dead: set[str]) -> list[A.Chunk]:
    ev = lake.read("brz", "commerce_events_raw").filter(
        (F.col("event_type") == "RETURN_REQUESTED") & F.col("subject_token_id").isNotNull())
    out = []
    for r in ev.select("return_id", "order_id", "channel", "amount_sar", "subject_token_id").orderBy(
            "return_id").collect():
        if r["subject_token_id"] in dead:
            continue
        text = (f"Return case {r['return_id']} for order {r['order_id']} ({r['channel']}): the customer requested a "
                f"refund; refund amount recorded on the event is SAR {r['amount_sar']}.")
        out.append(A.Chunk(f"CASE-{r['return_id']}#1", f"CASE-{r['return_id']}", f"Return case {r['return_id']}",
                           "case note", "EN", text, "CONFIDENTIAL", ("CUSTOMER_CARE",), r["subject_token_id"], "v1"))
    return out


def build_index(lake: Lake, policies_dir: Path | None = None) -> dict:
    dead = tombstones(lake)
    chunks: list[A.Chunk] = []
    for p in sorted((policies_dir or POLICIES).glob("*.md")):
        chunks += A.chunk_policy(p.read_text(encoding="utf-8"))
    n_policy = len(chunks)
    chunks += case_note_chunks(lake, dead)
    rows = [{"chunk_id": c.chunk_id, "chunk_kind": "CASE_NOTE" if c.subject_token_id else "POLICY",
             "doc_id": c.doc_id, "title": c.title, "section": c.section, "lang": c.lang, "text": c.text,
             "classification": c.classification, "acl_groups": ",".join(c.acl_groups),
             "subject_token_id": c.subject_token_id, "doc_version": c.doc_version} for c in chunks]
    lake.write(rows_to_df(lake.spark, CHUNK_COLS, rows), "ai", "policy_chunks", "overwrite", overwrite_schema=True,
               constraints={"tier_enum": "classification IN ('PUBLIC', 'CONFIDENTIAL', 'SECRET', 'TOP_SECRET')"})
    return {"policy_chunks": n_policy, "case_note_chunks": len(chunks) - n_policy, "tombstoned_skipped": len(dead)}


def load_chunks(lake: Lake) -> list[A.Chunk]:
    return [A.Chunk(r["chunk_id"], r["doc_id"], r["title"], r["section"], r["lang"], r["text"], r["classification"],
                    tuple(g for g in (r["acl_groups"] or "").split(",") if g), r["subject_token_id"],
                    r["doc_version"] or "")
            for r in lake.read("ai", "policy_chunks").collect()]


def ask(lake: Lake, question: str, user: A.User, run_sql: Callable[[str], list[tuple]] | None = None) -> A.Answer:
    """Answer with the tombstone set read at question time, and append one audit row."""
    a = A.answer(question, user, load_chunks(lake), tombstones(lake), run_sql)
    lake.write(rows_to_df(lake.spark, AUDIT_COLS, [A.audit_row(question, user, a, now_ksa())]),
               "ai", "agent_audit_log", "append", constraints={
                   "route_enum": "route IN ('RAG', 'SQL', 'REFUSED')"})
    return a


def duckdb_runner(path: Path) -> Callable[[str], list[tuple]]:
    """Read-only SQL runner over the local Gold DuckDB (WH_MIZAN through the Fabric Data Agent in Phase 10)."""
    def run(sql: str) -> list[tuple]:
        import duckdb
        con = duckdb.connect(Path(path).as_posix(), read_only=True)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()
    return run

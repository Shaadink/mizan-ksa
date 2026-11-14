"""Module 8: governed AI over policies and Gold marts (local deterministic stand-in for the Fabric Data Agent).

Guardrails, in the order they apply:
  1. Chunks INHERIT their document's NDMO tier and ACL groups; a section marked [SECRET]/[TOP_SECRET] can only
     raise the tier, never lower it.
  2. Entitlement filtering happens BEFORE retrieval scoring: a chunk the user may not see is never ranked.
     Chunks about an erased subject (ctl.deletion_tombstones) are suppressed the same way.
  3. Financial totals are never computed from text: money questions route to a read-only SQL template over
     allow-listed Gold marts, checked by validate_readonly_sql, and only for entitled users.
  4. Every call is written to the audit log (question stored as a hash, never as text).
There is no language model here: retrieval is lexical TF-IDF and SQL comes from fixed templates.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from mizan.governance.catalog import RANK, TIERS
from mizan.mdm.arabic_norm_and_privacy import build_arabic_search_key

ROUTES = ("RAG", "SQL", "REFUSED")
REFUSALS = ("NOT_ENTITLED", "NO_MATCH", "NO_SQL_TEMPLATE", "TEXT_MATH_FORBIDDEN")
_ARABIC = re.compile(r"[\u0600-\u06FF]")
_MARKER = re.compile(r"\[(TOP_SECRET|SECRET|CONFIDENTIAL|PUBLIC)\]")


@dataclass(frozen=True)
class User:
    name: str
    groups: frozenset[str]
    clearance: str

    def __post_init__(self):
        if self.clearance not in TIERS:
            raise ValueError(f"unknown clearance {self.clearance!r}")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    lang: str
    text: str
    classification: str
    acl_groups: tuple[str, ...]
    subject_token_id: str | None = None
    doc_version: str = ""


# ----------------------------------------------------------------------------- chunker

def parse_policy(md: str) -> tuple[dict, str]:
    if not md.startswith("---"):
        raise ValueError("policy needs a front-matter header")
    _, head, body = md.split("---", 2)
    meta = {}
    for line in head.strip().splitlines():
        k, v = (x.strip() for x in line.split(":", 1))
        meta[k] = v
    for k in ("doc_id", "title", "classification", "acl_groups"):
        if k not in meta:
            raise ValueError(f"policy front matter misses {k}")
    if meta["classification"] not in TIERS:
        raise ValueError(f"unknown classification {meta['classification']!r}")      # fail closed
    return meta, body


def chunk_policy(md: str, max_chars: int = 600) -> list[Chunk]:
    meta, body = parse_policy(md)
    version = hashlib.sha256(md.encode("utf-8")).hexdigest()[:12]
    acl = tuple(sorted(g.strip() for g in meta["acl_groups"].split(",") if g.strip()))
    out: list[Chunk] = []
    for sec in re.split(r"(?m)^# ", body):
        sec = sec.strip()
        if not sec:
            continue
        heading, _, text = sec.partition("\n")
        text = " ".join(text.split())
        tier = meta["classification"]
        m = _MARKER.search(heading)
        if m and RANK[m.group(1)] > RANK[tier]:
            tier = m.group(1)                                         # inherit, and only ever raise
        for i in range(0, max(len(text), 1), max_chars):
            piece = text[i:i + max_chars]
            if not piece:
                continue
            lang = "AR" if len(_ARABIC.findall(piece)) > len(piece) * 0.3 else "EN"
            out.append(Chunk(f"{meta['doc_id']}#{len(out) + 1}", meta["doc_id"], meta["title"],
                             _MARKER.sub("", heading).strip(), lang, piece, tier, acl, None, version))
    return out


# ----------------------------------------------------------------------------- entitlement + retrieval

def entitled(chunk: Chunk, user: User, tombstones: set[str]) -> bool:
    if chunk.subject_token_id and chunk.subject_token_id in tombstones:
        return False
    if RANK[user.clearance] < RANK[chunk.classification]:
        return False
    return "ALL_STAFF" in chunk.acl_groups or bool(set(chunk.acl_groups) & user.groups)


_STOP = frozenset("the and for with what our are was were how who why when where which this that from into our "
                  "your their its does did can could should would will about after before any all per not but "
                  "has have had been being than then them they there these those is of to in on at by an or".split())
MIN_SCORE = 0.08


def _terms(text: str) -> list[str]:
    return [t for t in build_arabic_search_key(text).split() if len(t) > 2 and t not in _STOP]


def rank(chunks: list[Chunk], question: str, k: int = 3) -> list[tuple[float, Chunk]]:
    docs = [Counter(_terms(c.title + " " + c.section + " " + c.text)) for c in chunks]
    df = Counter(t for d in docs for t in d)
    n = len(docs)
    q = Counter(_terms(question))

    def vec(c: Counter) -> dict[str, float]:
        return {t: (1 + math.log(f)) * math.log((n + 1) / (df.get(t, 0) + 1) + 1) for t, f in c.items()}

    qv = vec(q)
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
    scored = []
    for c, d in zip(chunks, docs, strict=True):
        dv = vec(d)
        dot = sum(qv[t] * dv[t] for t in qv if t in dv)
        if dot > 0 and dot / (qn * (math.sqrt(sum(v * v for v in dv.values())) or 1.0)) >= MIN_SCORE:
            scored.append((dot / (qn * (math.sqrt(sum(v * v for v in dv.values())) or 1.0)), c))
    return sorted(scored, key=lambda x: (-x[0], x[1].chunk_id))[:k]


# ----------------------------------------------------------------------------- read-only SQL over Gold

GOLD_ACL: dict[str, tuple[str, frozenset[str]]] = {
    "fact_merchant_settlement_recon": ("CONFIDENTIAL", frozenset({"FINANCE", "CFO_OFFICE"})),
    "fact_zatca_clearance_ledger": ("CONFIDENTIAL", frozenset({"TAX_TEAM", "FINANCE", "CFO_OFFICE"})),
    "mart_ndmo_scorecard": ("CONFIDENTIAL", frozenset({"CDO_OFFICE", "CFO_OFFICE"})),
    "dim_date_saudi": ("PUBLIC", frozenset({"ALL_STAFF"})),
}
_FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|exec|execute|into|"
                        r"copy|attach|detach|pragma|install|load|call|set)\b", re.I)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w\.]*)", re.I)


def validate_readonly_sql(sql: str, allowed: Iterable[str]) -> list[str]:
    """A single SELECT over allow-listed gld tables, or ValueError. Returns the tables referenced."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s or "--" in s or "/*" in s:
        raise ValueError("one statement, no comments")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise ValueError("only SELECT is allowed")
    if _FORBIDDEN.search(s):
        raise ValueError("write or session keyword in a read-only query")
    allowed = set(allowed)
    ctes = {m.lower() for m in re.findall(r"(?i)(?:with|,)\s*([A-Za-z_]\w*)\s+as\s*\(", s)}
    tables = []
    for ref in _TABLE_REF.findall(s):
        if ref.lower() in ctes:
            continue
        schema, _, name = ref.rpartition(".")
        if schema.lower() != "gld" or name not in allowed:
            raise ValueError(f"table {ref} is not an allow-listed Gold mart")
        tables.append(name)
    if not tables:
        raise ValueError("query reads no Gold mart")
    return sorted(set(tables))


SQL_TEMPLATES: tuple[tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"variance|unexplained|halala|\u0641\u0631\u0642", re.I), "RECON_VARIANCE",
     "SELECT SUM(unexplained_bank_variance_sar) AS bank_variance_sar, SUM(unexplained_gl_variance_sar) AS "
     "gl_variance_sar, SUM(unclassified_events) AS unclassified_events FROM gld.fact_merchant_settlement_recon"),
    (re.compile(r"settle|bank|in.transit|paid|\u062A\u0633\u0648\u064A\u0629", re.I), "SETTLEMENT_TOTALS",
     "SELECT SUM(bank_paid_sar) AS bank_paid_sar, SUM(in_transit_sar) AS in_transit_sar, SUM(quarantined_sar) AS "
     "quarantined_sar FROM gld.fact_merchant_settlement_recon"),
    (re.compile(r"invoice|zatca|cleared|reported|\u0641\u0627\u062A\u0648\u0631", re.I), "ZATCA_TOTALS",
     "SELECT state, COUNT(*) AS documents, SUM(total_incl_vat_sar) AS total_incl_vat_sar FROM "
     "gld.fact_zatca_clearance_ledger GROUP BY state ORDER BY state"),
)
_MONEY_Q = re.compile(r"\b(total|sum|how much|amount|revenue|variance|figure)\b|"
                      r"\u0643\u0645|\u0645\u062C\u0645\u0648\u0639|\u0625\u062C\u0645\u0627\u0644\u064A", re.I)


@dataclass
class Answer:
    route: str
    text: str
    refusal: str | None = None
    chunks: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    template: str | None = None


def answer(question: str, user: User, chunks: list[Chunk], tombstones: set[str],
           run_sql: Callable[[str], list[tuple]] | None = None) -> Answer:
    if _MONEY_Q.search(question):
        for rx, name, sql in SQL_TEMPLATES:
            if not rx.search(question):
                continue
            tables = validate_readonly_sql(sql, GOLD_ACL)
            for t in tables:
                tier, groups = GOLD_ACL[t]
                if RANK[user.clearance] < RANK[tier] or not ("ALL_STAFF" in groups or groups & user.groups):
                    return Answer("REFUSED", "You are not entitled to the data needed to answer this question.",
                                  "NOT_ENTITLED", tables=tables, template=name)
            if run_sql is None:
                raise RuntimeError("no SQL runner configured")
            rows = run_sql(sql)
            return Answer("SQL", f"From gld.{', gld.'.join(tables)} (template {name}): {rows}", None,
                          tables=tables, rows=rows, template=name)
        return Answer("REFUSED", "Financial figures come only from Gold marts, and no approved query matches. "
                      "Totals are never computed from document text.", "TEXT_MATH_FORBIDDEN")
    visible = [c for c in chunks if entitled(c, user, tombstones)]            # filter FIRST, then rank
    hits = rank(visible, question)
    if hits:
        return Answer("RAG", " ".join(c.text for _, c in hits), None, chunks=[c.chunk_id for _, c in hits])
    hidden = [c for c in chunks if not entitled(c, user, tombstones)
              and not (c.subject_token_id and c.subject_token_id in tombstones)]
    if rank(hidden, question, k=1):
        return Answer("REFUSED", "You are not entitled to the material needed to answer this question.",
                      "NOT_ENTITLED")
    return Answer("REFUSED", "No approved source answers this question.", "NO_MATCH")


def audit_row(question: str, user: User, a: Answer, ts: str) -> dict:
    return {"asked_at": ts, "user_name": user.name, "user_clearance": user.clearance,
            "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(), "route": a.route,
            "refusal_reason": a.refusal, "chunk_ids": ",".join(a.chunks), "tables": ",".join(a.tables),
            "sql_template": a.template}

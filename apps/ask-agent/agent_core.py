"""Ask MIZAN agent: the governed part of the loop (no Azure imports, so it is unit-tested locally).

The model may only *ask* for tools from TOOLS. The tools run in the user's browser under the user's own Fabric
permissions (live DAX through the Fabric App connector), so this service never sees a Fabric token or raw rows.
Before an answer leaves this service, every number in it must appear in a tool result (verify_numbers); otherwise
the model gets one chance to correct itself, then the browser falls back to the guided answers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

# Same tiers and groups as mizan.ai.governed.GOLD_ACL (test enforces parity); the payment-method split inherits
# the reconciliation's entitlement, as in the Command Center.
TIERS = ("PUBLIC", "CONFIDENTIAL", "SECRET", "TOP_SECRET")
GOLD_ACL: dict[str, tuple[str, frozenset[str]]] = {
    "fact_merchant_settlement_recon": ("CONFIDENTIAL", frozenset({"FINANCE", "CFO_OFFICE"})),
    "fact_zatca_clearance_ledger": ("CONFIDENTIAL", frozenset({"TAX_TEAM", "FINANCE", "CFO_OFFICE"})),
    "mart_ndmo_scorecard": ("CONFIDENTIAL", frozenset({"CDO_OFFICE", "CFO_OFFICE"})),
    "dim_date_saudi": ("PUBLIC", frozenset({"ALL_STAFF"})),
    "fact_payment_method_daily": ("CONFIDENTIAL", frozenset({"FINANCE", "CFO_OFFICE"})),
}
ROLES: dict[str, tuple[str, frozenset[str]]] = {
    "FINANCE": ("CONFIDENTIAL", frozenset({"FINANCE"})),
    "TAX": ("CONFIDENTIAL", frozenset({"TAX_TEAM"})),
    "CDO": ("CONFIDENTIAL", frozenset({"CDO_OFFICE"})),
    "STAFF": ("PUBLIC", frozenset({"ALL_STAFF"})),
}

_FILTERS = {
    "type": "object",
    "description": "Optional filters; omit a key to keep the page's current filter, pass \"\" to clear it.",
    "properties": {
        "from": {"type": "string", "description": "First business date, YYYY-MM-DD"},
        "to": {"type": "string", "description": "Last business date, YYYY-MM-DD"},
        "mid": {"type": "string", "description": "Merchant ID like MID100046"},
        "city": {"type": "string", "enum": ["", "Riyadh", "Jeddah", "Dammam", "Makkah", "Madinah"]},
        "status": {"type": "string", "enum": ["", "ASSESSED", "NOT_ASSESSED"],
                   "description": "Bank-file status of a merchant-day"},
        "method": {"type": "string", "enum": ["", "MADA", "CARD", "BNPL", "SADAD", "UNMATCHED_BANK_LINE"]},
        "egs": {"type": "string", "description": "E-invoicing device like EGS-03"},
        "flow": {"type": "string", "enum": ["", "REPORTING", "CLEARANCE"]},
        "state": {"type": "string", "enum": ["", "CLEARED", "REPORTED", "ACCEPTED_WITH_WARNINGS",
                                             "CONFIRMED_REJECTION"]},
    },
    "additionalProperties": False,
}

GLOSSARY_TERMS = ["MIZAN", "ZATCA", "INVOICE_CHAIN", "EGS", "MADA", "SADAD", "BNPL", "MDR", "SETTLEMENT",
                  "RECONCILIATION", "NOT_ASSESSED", "GENERAL_LEDGER", "PDPL", "NDMO", "GOLD_LAYER",
                  "MICROSOFT_FABRIC", "ASK_MIZAN", "HALALA"]

# name -> (Gold tables it reads, description). Arguments are only filters; the model never writes a query.
TOOL_SPECS: dict[str, tuple[tuple[str, ...], str]] = {
    "explain_term": ((), "Plain-language explanation of a MIZAN concept or Saudi term (what MIZAN is, ZATCA, "
                         "e-invoice chain, EGS, mada, SADAD, BNPL, MDR, settlement, reconciliation, not assessed, "
                         "general ledger, PDPL, NDMO, Gold layer, Microsoft Fabric, Ask MIZAN, halala). Reads no data; "
                         "open to every role."),
    "get_reconciliation": (("fact_merchant_settlement_recon",),
                           "Settlement reconciliation totals: gross captures, refunds, bank fees, expected net, bank "
                           "paid, in transit, quarantined, GL card clearing, unexplained bank and GL variance, broken "
                           "keys, assessed and not-assessed merchant-days (bank file not arrived)."),
    "get_daily": (("fact_merchant_settlement_recon",),
                  "One row per business day: gross, refunds, fees, bank paid, in transit, GL, expected net, "
                  "unexplained difference and merchant-days awaiting the bank file."),
    "get_top_merchants": (("fact_merchant_settlement_recon",),
                          "Merchants ranked by gross captures for the filters, with their share of SAR."),
    "get_zatca": (("fact_zatca_clearance_ledger",),
                  "E-invoice outcomes by state and flow, totals incl. VAT, per-EGS documents, retries, corrections."),
    "get_payment_methods": (("fact_payment_method_daily",),
                            "Per payment method: captures, the bank's fees (MDR + VAT from the settlement file), fee "
                            "rate in bps, refunds, bank paid, in transit, estimated fees."),
    "get_data_quality": (("mart_ndmo_scorecard",),
                         "NDMO data-quality checks: score, threshold and status per dimension and table."),
    "get_calendar": (("dim_date_saudi",),
                     "Gregorian and Umm al-Qura Hijri dates in the window, Ramadan days and weekends."),
}


def entitled(role: str, table: str) -> bool:
    clearance, groups = ROLES[role]
    tier, allowed = GOLD_ACL[table]
    return TIERS.index(clearance) >= TIERS.index(tier) and ("ALL_STAFF" in allowed or bool(allowed & groups))


def tools_for(role: str) -> list[dict]:
    """Only the tools whose Gold tables the role may read are offered to the model."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")                       # fail closed
    out = []
    for name, (tables, desc) in TOOL_SPECS.items():
        if all(entitled(role, t) for t in tables):
            params = {"type": "object", "properties": {"filters": _FILTERS}, "additionalProperties": False}
            if name == "explain_term":
                params = {"type": "object", "properties": {"term": {"type": "string", "enum": GLOSSARY_TERMS}},
                          "required": ["term"], "additionalProperties": False}
            if name == "get_top_merchants":
                params["properties"]["n"] = {"type": "integer", "minimum": 1, "maximum": 10}
            out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": params}})
    return out


PII = re.compile(r"national.?id|\bnid\b|iqama|passport|phone|mobile|e-?mail|\biban\b|address|customer name|"
                 r"full name|date of birth|\u0647\u0648\u064A\u0629|\u062C\u0648\u0627\u0644|"
                 r"\u0627\u0642\u0627\u0645\u0629", re.I)
WRITE = re.compile(r"\b(delete|drop|update|insert|truncate|alter|grant|change the|fix the)\b", re.I)


def precheck(question: str) -> str | None:
    """Refusal code for requests that are stopped before the model sees them."""
    if PII.search(question):
        return "PERSONAL_DATA"
    if WRITE.search(question):
        return "READ_ONLY"
    return None


def system_prompt(role: str, page_filters: dict) -> str:
    clearance, groups = ROLES[role]
    available = [t["function"]["name"] for t in tools_for(role)]
    active = {k: v for k, v in (page_filters or {}).items() if v}
    return (
        "You are Ask MIZAN, a read-only analyst for a Saudi payments and e-invoicing data platform (synthetic data). "
        f"The user's role is {role} (clearance {clearance}, groups {', '.join(sorted(groups))}). "
        f"The page's current filters are {json.dumps(active) if active else 'none'}.\n"
        "Rules:\n"
        "1. Answer only from tool results. Call tools first; chain several calls when a question needs it "
        "(for example: find the day, then look at that day).\n"
        "2. Every number you write must appear exactly in a tool result. Copy money as SAR with two decimals and "
        "thousands separators (for example SAR 1,234,567.89). Never add, subtract, round, convert or estimate. "
        "If a figure is "
        "not in a tool result, say you cannot give it.\n"
        "3. A merchant-day whose bank file has not arrived is NOT ASSESSED: never call it balanced or missing money.\n"
        "4. Never reveal or ask for personal data. You cannot change data.\n"
        f"5. Your tools for this role: {', '.join(available) or 'none'}. A topic outside them (for example "
        "payment-method fees, invoices, data quality) is not available for this role: say exactly that, and do not "
        "offer related figures. If no tool can answer, say so briefly and suggest what your tools cover.\n"
        "6. For what MIZAN is, or what a term means (ZATCA, mada, PDPL, settlement...), call explain_term and answer "
        "from it. MIZAN is a portfolio reference platform with synthetic data, never a real company with customers. "
        "Questions unrelated to MIZAN, Saudi payments or e-invoicing: politely decline in one sentence.\n"
        "7. Topics and the role they need: settlement, sales, bank, variance and payment-method fees need Finance; "
        "e-invoices need Tax or Finance; data quality needs Data office; the calendar and glossary are open to all. "
        "If the user's role lacks a topic, say in one sentence which role it needs, and stop. Check this FIRST, "
        "before anything else, whatever the language of the question. Never answer a topic with a tool meant for "
        "another topic.\n"
        "Never ask the user for a date range or other details: the page filters already define the period. If you "
        "have a tool for the topic, call it right away.\n"
        "8. Reply in English, unless the user's message actually contains Arabic script - then reply in Arabic. "
        "A short or ambiguous message (for example a greeting) is English: do not switch to Arabic for it. "
        "At most 5 short sentences. Keep digits, IDs and dates in Western form (0-9)."
    )


# ----------------------------------------------------------------------------- number verification

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _dec(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set[Decimal]:
    out = set()
    for t in _NUM.findall(text):
        d = _dec(t.rstrip(".,"))
        if d is not None:
            out.add(d)
    return out


def tool_numbers(messages: list[dict]) -> set[Decimal]:
    """Every number that appears anywhere in the tool results of this conversation (values, dates, IDs)."""
    nums: set[Decimal] = set()
    for m in messages:
        if m.get("role") == "tool":
            nums |= numbers_in(str(m.get("content", "")))
    return nums


def verify_numbers(answer: str, messages: list[dict]) -> list[str]:
    """Number tokens in the answer that no tool result contains (empty list = verified)."""
    allowed = tool_numbers(messages)
    bad = []
    for t in _NUM.findall(answer):
        d = _dec(t.rstrip(".,"))
        if d is None or d in allowed:
            continue
        bad.append(t.rstrip(".,"))
    return bad


# ----------------------------------------------------------------------------- one step of the loop

MAX_MESSAGES = 24
MAX_TOOL_CONTENT = 12000


def sanitize(messages: list) -> list[dict]:
    """Keep only the message shapes the loop produces; cap sizes."""
    if not isinstance(messages, list) or not messages or len(messages) > MAX_MESSAGES:
        raise ValueError("messages must be a non-empty list of at most 24 items")
    out = []
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else None
        if role == "user":
            out.append({"role": "user", "content": str(m.get("content", ""))[:400]})
        elif role == "assistant":
            calls = [{"id": str(c["id"])[:64], "type": "function",
                      "function": {"name": str(c["function"]["name"]),
                                   "arguments": str(c["function"]["arguments"])[:2000]}}
                     for c in (m.get("tool_calls") or []) if c.get("function", {}).get("name") in TOOL_SPECS]
            msg = {"role": "assistant", "content": str(m.get("content") or "")[:4000] or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": str(m.get("tool_call_id", ""))[:64],
                        "content": str(m.get("content", ""))[:MAX_TOOL_CONTENT]})
        else:
            raise ValueError(f"unexpected message role {role!r}")
    if out[0]["role"] != "user":
        raise ValueError("the conversation must start with the user's question")
    return out


Chat = Callable[[list[dict], list[dict]], dict]     # (messages, tools) -> {"content": str|None, "tool_calls": [...]}


def step(role: str, page_filters: dict, messages: list, chat: Chat) -> dict:
    """One model turn: either tool calls for the browser to run, or a verified answer, or a decline."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    msgs = sanitize(messages)
    code = precheck(msgs[0]["content"])
    if code:
        return {"type": "declined", "code": code}
    tools = tools_for(role)
    convo = [{"role": "system", "content": system_prompt(role, page_filters)}] + msgs
    reply = chat(convo, tools)
    calls = reply.get("tool_calls") or []
    if calls:
        offered = {t["function"]["name"] for t in tools}
        ok = [c for c in calls if c["function"]["name"] in offered]
        if not ok:
            return {"type": "declined", "code": "NOT_ENTITLED"}
        return {"type": "tool_calls", "message": {"role": "assistant", "content": reply.get("content"),
                                                    "tool_calls": ok}}
    text = (reply.get("content") or "").strip()
    bad = verify_numbers(text, msgs)
    if bad:                                                              # one chance to correct itself
        convo += [{"role": "assistant", "content": text},
                  {"role": "user", "content": "These numbers are not in any tool result: " + ", ".join(bad) +
                   ". Rewrite the answer using only numbers copied exactly from the tool results."}]
        text = (chat(convo, []).get("content") or "").strip()
        bad = verify_numbers(text, msgs)
        if bad:
            return {"type": "unverified", "unverified": bad}
    return {"type": "answer", "text": text}

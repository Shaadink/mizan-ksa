"""Azure Function (Flex Consumption, Python 3.12): POST /api/ask -> one governed step of the Ask MIZAN agent.

Identity, not keys: the Function's managed identity holds "Cognitive Services OpenAI User" on the Azure OpenAI
resource, whose API keys are disabled. Abuse limits: the app origin only, a per-caller rate limit, a daily cap per
instance, small request and token sizes. The Fabric login of the caller cannot be verified here (separate directory),
which is stated in HONESTY.md; the budget alert caps the cost of any misuse.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque

import azure.functions as func
from agent_core import ROLES, step
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")
PER_MINUTE = 20          # model turns per caller per minute (one question is 2-4 turns)
PER_DAY = 600            # model turns per instance per day
_calls: dict[str, deque] = defaultdict(deque)
_day = {"date": "", "n": 0}
_client: AzureOpenAI | None = None


def _openai() -> AzureOpenAI:
    global _client
    if _client is None:
        token = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        _client = AzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], azure_ad_token_provider=token,
                              api_version="2024-10-21")
    return _client


def _chat(messages: list[dict], tools: list[dict]) -> dict:
    kw = {"tools": tools, "tool_choice": "auto", "parallel_tool_calls": True} if tools else {}
    r = _openai().chat.completions.create(model=os.environ["AZURE_OPENAI_DEPLOYMENT"], messages=messages,
                                          temperature=0, max_tokens=500, **kw)
    m = r.choices[0].message
    calls = [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
             for c in (m.tool_calls or [])]
    return {"content": m.content, "tool_calls": calls}


def _limited(caller: str) -> bool:
    now = time.time()
    q = _calls[caller]
    while q and now - q[0] > 60:
        q.popleft()
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    if _day["date"] != today:
        _day.update(date=today, n=0)
    if len(q) >= PER_MINUTE or _day["n"] >= PER_DAY:
        return True
    q.append(now)
    _day["n"] += 1
    return False


def _json(body: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body), status_code=status, mimetype="application/json")


@app.route(route="ask", methods=["POST"])
def ask(req: func.HttpRequest) -> func.HttpResponse:
    if ORIGIN and req.headers.get("Origin") != ORIGIN:
        return _json({"type": "error", "code": "ORIGIN"}, 403)
    caller = (req.headers.get("X-Forwarded-For") or "unknown").split(",")[0].strip()
    if _limited(caller):
        return _json({"type": "error", "code": "RATE_LIMIT"}, 429)
    try:
        if len(req.get_body()) > 60000:
            raise ValueError("request too large")
        body = req.get_json()
        role = body.get("role")
        if role not in ROLES:
            raise ValueError("unknown role")
        result = step(role, body.get("filters") or {}, body.get("messages"), _chat)
        return _json(result)
    except ValueError as e:
        return _json({"type": "error", "code": "BAD_REQUEST", "message": str(e)[:200]}, 400)
    except Exception:
        logging.exception("ask failed")
        return _json({"type": "error", "code": "UPSTREAM"}, 502)

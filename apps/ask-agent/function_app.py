"""Azure Function (Flex Consumption, Python 3.12): POST /api/ask -> one governed step of the Ask MIZAN agent.

Identity, not keys: the Function's managed identity holds "Cognitive Services OpenAI User" on the Azure OpenAI
resource, whose API keys are disabled. Abuse limits: a per-caller rate limit, a daily cap per instance, small
request and token sizes.

CALLER IDENTITY. Set REQUIRE_ENTRA_AUTH=1 with ENTRA_TENANT_ID and ENTRA_AUDIENCE and every request must carry
a valid Entra access token, verified in entra_auth.py -- signature, issuer, audience, directory and expiry --
with rate limiting keyed on the verified object id rather than a forwardable IP. It ships OFF, because ADR-013
records that the app cannot yet obtain a token this Function would accept: Fabric and the Function sit in
different directories and cross-tenant guest access fails here with Entra error 530035. With it off the Origin
header is the only check, and an Origin header is set by browsers and forged trivially by anything else, so it
deters casual abuse and prevents nothing. That is why nothing of value passes through: no Fabric token, no Gold
row and no personal data, and the budget alert caps the cost of misuse at USD 5. See HONESTY.md row 15.
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
REQUIRE_AUTH = os.environ.get("REQUIRE_ENTRA_AUTH", "") == "1"
ENTRA_TENANT = os.environ.get("ENTRA_TENANT_ID", "")
ENTRA_AUDIENCE = os.environ.get("ENTRA_AUDIENCE", "")
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


def _caller(req: func.HttpRequest) -> str:
    """Who is calling, as well as this deployment can tell.

    With REQUIRE_ENTRA_AUTH on, that is a verified directory object id and the request is refused
    without one. With it off it is a forwarded IP, which shared networks make useless and a proxy makes
    forgeable -- good enough to spread a rate limit, not good enough to call authentication.
    """
    if not REQUIRE_AUTH:
        return (req.headers.get("X-Forwarded-For") or "unknown").split(",")[0].strip()
    if not (ENTRA_TENANT and ENTRA_AUDIENCE):
        # Fail closed. "Authentication required" with nothing configured to check it against must not
        # silently become "authentication skipped".
        raise PermissionError("REQUIRE_ENTRA_AUTH is set but ENTRA_TENANT_ID/ENTRA_AUDIENCE are not")
    header = req.headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        raise PermissionError("no bearer token")
    from entra_auth import AuthError, caller_id, verify
    try:
        return caller_id(verify(header[7:], tenant=ENTRA_TENANT, audience=ENTRA_AUDIENCE))
    except AuthError as e:
        # The reason is logged, never returned: a verifier that says which check failed helps tune the
        # next attempt.
        logging.warning("token rejected: %s", e)
        raise PermissionError("token rejected") from e


@app.route(route="ask", methods=["POST"])
def ask(req: func.HttpRequest) -> func.HttpResponse:
    if ORIGIN and req.headers.get("Origin") != ORIGIN:
        return _json({"type": "error", "code": "ORIGIN"}, 403)
    try:
        caller = _caller(req)
    except PermissionError:
        return _json({"type": "error", "code": "UNAUTHORIZED"}, 401)
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

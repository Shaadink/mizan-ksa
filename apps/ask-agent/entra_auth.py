"""Verify a Microsoft Entra ID access token, with no JWT library and no new dependency.

HONESTY row 15 says the Function cannot verify its caller: an `Origin` header is set by browsers and
forged trivially by anything else, so it deters casual abuse and prevents nothing. This module is the
fix for that, and it is written to be switched on the day the deployment can supply a token.

**It is deliberately opt-in** (`REQUIRE_ENTRA_AUTH=1`). ADR-013 records why the app cannot currently
obtain a token the Function would accept: Fabric and the Function live in different directories, and
cross-tenant guest access already fails in this tenant with Entra error 530035. Shipping the check
disabled, with the reason written down, is honest. Shipping it enabled so that nothing works, or not
shipping it at all and calling the gap a limitation, are both worse.

**Why no PyJWT.** The verification is three steps -- fetch the tenant's public keys, check the
signature, check the claims -- and `cryptography` is already a dependency because ZATCA invoices are
signed with it. Adding a library to a security boundary is a decision, not a default; this one did not
earn it. What matters is that the checks below are complete, so they are enumerated in `verify()` and
each has a test that removes it and watches the verification fail.

The signature check is **not optional and not configurable**. Every failure returns the same opaque
`AuthError` to the caller: a verifier that explains precisely which check failed is a verifier that
helps an attacker tune the next attempt. The detail goes to the log.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

LOGIN = "https://login.microsoftonline.com"
JWKS_TTL_S = 3600                       # Entra rotates signing keys; an hour is Microsoft's own guidance
CLOCK_SKEW_S = 120                      # tolerate two minutes of drift, no more
SUPPORTED_ALGS = ("RS256",)             # not "none", and not HS256 -- see test_an_unsigned_token_is_refused


class AuthError(Exception):
    """One error for every failure. The reason is logged, never returned."""


@dataclass
class JwksCache:
    """Entra's public signing keys, cached. A fetch on every request would be a dependency on Entra
    being reachable in the hot path, and a free denial-of-service against ourselves."""
    fetched_at: float = 0.0
    keys: dict[str, rsa.RSAPublicKey] = field(default_factory=dict)

    def fresh(self, now: float) -> bool:
        return bool(self.keys) and (now - self.fetched_at) < JWKS_TTL_S


_CACHE = JwksCache()


def _b64url(data: str | bytes) -> bytes:
    raw = data.encode() if isinstance(data, str) else data
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def _int(data: str) -> int:
    return int.from_bytes(_b64url(data), "big")


def fetch_jwks(tenant: str, *, now: float | None = None, opener=urllib.request.urlopen) -> dict:
    """Public signing keys for a tenant, cached for an hour."""
    now = now or time.time()
    if _CACHE.fresh(now):
        return _CACHE.keys
    url = f"{LOGIN}/{tenant}/discovery/v2.0/keys"
    try:
        with opener(url, timeout=10) as response:
            document = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AuthError(f"cannot reach the Entra key endpoint: {e}") from e
    keys = {}
    for key in document.get("keys", []):
        if key.get("kty") == "RSA" and key.get("n") and key.get("e"):
            keys[key["kid"]] = rsa.RSAPublicNumbers(_int(key["e"]), _int(key["n"])).public_key()
    if not keys:
        raise AuthError("the Entra key endpoint returned no usable RSA keys")
    _CACHE.keys, _CACHE.fetched_at = keys, now
    return keys


def verify(token: str, *, tenant: str, audience: str, now: float | None = None,
           opener=urllib.request.urlopen) -> dict:
    """Return the token's claims, or raise AuthError. Every check below is required.

      1. the token has three dot-separated parts and decodes
      2. the algorithm is RS256 -- never `none`, never a symmetric algorithm we would verify with a
         key an attacker could also hold
      3. the key id is one the tenant currently publishes
      4. the signature is valid over the exact header.payload bytes as received
      5. the issuer is this tenant's v2.0 issuer
      6. the audience is this API, so a token minted for Graph cannot be replayed here
      7. the tenant claim matches, so a token from another directory cannot be replayed here
      8. the token is not expired and not used before its time, within two minutes of skew
    """
    now = now or time.time()
    try:
        header_b64, payload_b64, signature_b64 = token.strip().split(".")
        header = json.loads(_b64url(header_b64))
        claims = json.loads(_b64url(payload_b64))
        signature = _b64url(signature_b64)
    except (ValueError, json.JSONDecodeError) as e:
        raise AuthError(f"malformed token: {e}") from e

    if header.get("alg") not in SUPPORTED_ALGS:
        raise AuthError(f"unsupported alg {header.get('alg')!r}")
    kid = header.get("kid")
    keys = fetch_jwks(tenant, now=now, opener=opener)
    if kid not in keys:
        raise AuthError(f"unknown key id {kid!r}")

    signed = f"{header_b64}.{payload_b64}".encode()
    try:
        keys[kid].verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as e:
        raise AuthError("signature does not verify") from e

    issuer = claims.get("iss", "")
    if issuer not in (f"{LOGIN}/{tenant}/v2.0", f"https://sts.windows.net/{tenant}/"):
        raise AuthError(f"unexpected issuer {issuer!r}")
    aud = claims.get("aud")
    if aud != audience:
        raise AuthError(f"token audience {aud!r} is not {audience!r}")
    if claims.get("tid") and claims["tid"] != tenant:
        raise AuthError("token was issued by a different directory")
    if float(claims.get("exp", 0)) + CLOCK_SKEW_S < now:
        raise AuthError("token has expired")
    if float(claims.get("nbf", 0)) - CLOCK_SKEW_S > now:
        raise AuthError("token is not valid yet")
    return claims


def caller_id(claims: dict) -> str:
    """A stable, non-identifying handle for rate limiting and logs.

    `oid` is the user's object id: stable across sign-ins, meaningless outside the directory, and not a
    name or an email. Rate limiting on a verified identity is strictly better than on a forwarded IP,
    which shared networks make useless and a proxy makes forgeable.
    """
    return str(claims.get("oid") or claims.get("sub") or "unknown")


def public_key_pem(key: rsa.RSAPublicKey) -> bytes:
    """Only used by the tests, which mint their own keys rather than calling Entra."""
    return key.public_bytes(serialization.Encoding.PEM,
                            serialization.PublicFormat.SubjectPublicKeyInfo)

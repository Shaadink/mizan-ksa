"""Token verification for the Ask MIZAN Function, tested by attacking it.

A verifier is only worth what its failures are worth, so every check in `verify()` gets a test that
removes exactly that protection and asserts the token is refused: an unsigned token, a token signed by
somebody else's key, one minted for a different API, one from a different directory, an expired one,
one that is not valid yet, and one whose payload was edited after signing.

The tests mint their own RSA keys rather than calling Entra, which is also how this runs in CI with no
network and no tenant.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "ask-agent"))

import entra_auth as EA  # noqa: E402

TENANT = "11111111-2222-3333-4444-555555555555"
AUDIENCE = "api://mizan-ask"
OTHER_TENANT = "99999999-8888-7777-6666-555555555555"


@pytest.fixture(autouse=True)
def _clear_cache():
    EA._CACHE.keys, EA._CACHE.fetched_at = {}, 0.0
    yield
    EA._CACHE.keys, EA._CACHE.fetched_at = {}, 0.0


@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwks_opener(key, kid="k1"):
    numbers = key.public_key().public_numbers()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @staticmethod
        def read():
            return json.dumps({"keys": [{
                "kty": "RSA", "kid": kid, "use": "sig",
                "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
                "e": _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big"))}]}).encode()

    return lambda _url, timeout=None: Response()


def mint(key, *, kid="k1", alg="RS256", sign_with=None, now=None, **overrides) -> str:
    now = now or time.time()
    claims = {"iss": f"{EA.LOGIN}/{TENANT}/v2.0", "aud": AUDIENCE, "tid": TENANT,
              "oid": "user-object-id", "exp": now + 3600, "nbf": now - 60, **overrides}
    header = _b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    signer = sign_with or key
    signature = signer.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64(signature)}"


# ------------------------------------------------------------------ the happy path

def test_a_valid_token_verifies_and_yields_a_stable_caller_id(keypair):
    claims = EA.verify(mint(keypair), tenant=TENANT, audience=AUDIENCE,
                       opener=_jwks_opener(keypair))
    assert claims["oid"] == "user-object-id"
    assert EA.caller_id(claims) == "user-object-id"


def test_the_caller_id_is_an_object_id_never_a_name_or_an_email(keypair):
    """Rate limits and logs must key on something stable and non-identifying."""
    claims = EA.verify(mint(keypair, name="Someone Real", preferred_username="a@b.com"),
                       tenant=TENANT, audience=AUDIENCE, opener=_jwks_opener(keypair))
    assert EA.caller_id(claims) == "user-object-id"
    assert "@" not in EA.caller_id(claims)


# ------------------------------------------------------------------ each check, removed

def test_an_unsigned_token_is_refused(keypair):
    """alg=none is the oldest JWT attack there is and still the first one tried."""
    header = _b64(json.dumps({"alg": "none", "kid": "k1"}).encode())
    payload = _b64(json.dumps({"aud": AUDIENCE, "tid": TENANT, "exp": time.time() + 99}).encode())
    with pytest.raises(EA.AuthError, match="unsupported alg"):
        EA.verify(f"{header}.{payload}.", tenant=TENANT, audience=AUDIENCE,
                  opener=_jwks_opener(keypair))


def test_a_token_signed_by_another_key_is_refused(keypair):
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = mint(keypair, sign_with=attacker)
    with pytest.raises(EA.AuthError, match="signature does not verify"):
        EA.verify(token, tenant=TENANT, audience=AUDIENCE, opener=_jwks_opener(keypair))


def test_a_payload_edited_after_signing_is_refused(keypair):
    """The signature covers the bytes as received, not the parsed claims."""
    header, payload, signature = mint(keypair).split(".")
    claims = json.loads(EA._b64url(payload))
    claims["oid"] = "somebody-else"
    with pytest.raises(EA.AuthError, match="signature does not verify"):
        EA.verify(f"{header}.{_b64(json.dumps(claims).encode())}.{signature}",
                  tenant=TENANT, audience=AUDIENCE, opener=_jwks_opener(keypair))


def test_a_token_for_a_different_api_is_refused(keypair):
    """A token minted for Microsoft Graph must not open this door."""
    token = mint(keypair, aud="https://graph.microsoft.com")
    with pytest.raises(EA.AuthError, match="audience"):
        EA.verify(token, tenant=TENANT, audience=AUDIENCE, opener=_jwks_opener(keypair))


def test_a_token_from_another_directory_is_refused(keypair):
    token = mint(keypair, iss=f"{EA.LOGIN}/{OTHER_TENANT}/v2.0", tid=OTHER_TENANT)
    with pytest.raises(EA.AuthError, match="issuer"):
        EA.verify(token, tenant=TENANT, audience=AUDIENCE, opener=_jwks_opener(keypair))


def test_a_right_issuer_but_wrong_tenant_claim_is_refused(keypair):
    token = mint(keypair, tid=OTHER_TENANT)
    with pytest.raises(EA.AuthError, match="different directory"):
        EA.verify(token, tenant=TENANT, audience=AUDIENCE, opener=_jwks_opener(keypair))


def test_an_expired_token_is_refused_outside_the_skew_window(keypair):
    now = time.time()
    token = mint(keypair, exp=now - 600, nbf=now - 7200, now=now)
    with pytest.raises(EA.AuthError, match="expired"):
        EA.verify(token, tenant=TENANT, audience=AUDIENCE, now=now, opener=_jwks_opener(keypair))


def test_a_token_a_minute_past_expiry_still_passes_because_clocks_drift(keypair):
    now = time.time()
    token = mint(keypair, exp=now - 60, nbf=now - 7200, now=now)
    assert EA.verify(token, tenant=TENANT, audience=AUDIENCE, now=now,
                     opener=_jwks_opener(keypair))["oid"] == "user-object-id"


def test_a_token_not_yet_valid_is_refused(keypair):
    now = time.time()
    token = mint(keypair, nbf=now + 3600, exp=now + 7200, now=now)
    with pytest.raises(EA.AuthError, match="not valid yet"):
        EA.verify(token, tenant=TENANT, audience=AUDIENCE, now=now, opener=_jwks_opener(keypair))


def test_a_token_signed_with_an_unpublished_key_is_refused(keypair):
    token = mint(keypair, kid="rotated-away")
    with pytest.raises(EA.AuthError, match="unknown key id"):
        EA.verify(token, tenant=TENANT, audience=AUDIENCE, opener=_jwks_opener(keypair))


def test_rubbish_is_refused_without_an_exception_escaping(keypair):
    for rubbish in ("", "not-a-token", "a.b", "a.b.c", "...", "x" * 5000):
        with pytest.raises(EA.AuthError):
            EA.verify(rubbish, tenant=TENANT, audience=AUDIENCE, opener=_jwks_opener(keypair))


# ------------------------------------------------------------------ the key cache

def test_keys_are_cached_so_entra_is_not_in_the_hot_path(keypair):
    calls = {"n": 0}
    opener = _jwks_opener(keypair)

    def counting(url, timeout=None):
        calls["n"] += 1
        return opener(url, timeout)

    for _ in range(5):
        EA.verify(mint(keypair), tenant=TENANT, audience=AUDIENCE, opener=counting)
    assert calls["n"] == 1, "the key endpoint was called more than once"


def test_the_cache_expires_so_a_rotated_key_is_picked_up(keypair):
    calls = {"n": 0}
    opener = _jwks_opener(keypair)

    def counting(url, timeout=None):
        calls["n"] += 1
        return opener(url, timeout)

    now = time.time()
    EA.verify(mint(keypair, now=now), tenant=TENANT, audience=AUDIENCE, now=now, opener=counting)
    later = now + EA.JWKS_TTL_S + 1
    EA.verify(mint(keypair, now=later), tenant=TENANT, audience=AUDIENCE, now=later, opener=counting)
    assert calls["n"] == 2


def test_an_unreachable_key_endpoint_fails_closed(keypair):
    def broken(_url, timeout=None):
        raise OSError("connection refused")
    with pytest.raises(EA.AuthError, match="cannot reach"):
        EA.verify(mint(keypair), tenant=TENANT, audience=AUDIENCE, opener=broken)

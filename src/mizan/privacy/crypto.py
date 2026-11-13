"""Encrypt-on-land primitives (ADR-003): HMAC-SHA256 subject tokens + per-subject AES-256-GCM DEKs.

Keys come ONLY from the environment / git-ignored .env (CLAUDE.md):
  MIZAN_HMAC_KEY_B64  32-byte key for subject_token_id and identifier HMACs
  MIZAN_KEK_B64       32-byte key-encryption key that wraps every per-subject DEK
In Fabric these come from Key Vault-backed environment secrets (Phase 10).

Field ciphertext format: "v1:" + base64(nonce[12] || ciphertext || tag[16]), AAD = "<token>|<column>", so a
ciphertext cannot be moved to another subject or column. Destroying a subject's DEK (crypto-shredding,
Phase 6) makes every copy of that subject's fields undecryptable at once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TOKEN_PREFIX = "sub_"  # noqa: S105 - an id prefix, not a secret
_REPO = Path(__file__).resolve().parents[3]


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE lines); never overrides variables already set."""
    p = path or (_REPO / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _key(name: str) -> bytes:
    load_dotenv()
    raw = os.environ.get(name)
    if not raw:
        raise RuntimeError(f"{name} is not set (put it in .env; run scripts/init_local_env.py for dev keys)")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError(f"{name} must decode to 32 bytes")
    return key


@dataclass(frozen=True)
class Keys:
    hmac_key: bytes
    kek: bytes
    kek_version: str = "KEK-1"

    @classmethod
    def from_env(cls) -> Keys:
        return cls(_key("MIZAN_HMAC_KEY_B64"), _key("MIZAN_KEK_B64"))


def hmac_hex(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def token_for(hmac_key: bytes, customer_ref: str | None) -> str | None:
    """Deterministic pseudonymous subject id for a source customer ref (e.g. 'POS-C000123')."""
    if not customer_ref:
        return None  # WALK_IN: no subject
    return TOKEN_PREFIX + hmac_hex(hmac_key, "SUBJECT|" + customer_ref)[:24]


def subject_token(keys: Keys, customer_ref: str | None) -> str | None:
    return token_for(keys.hmac_key, customer_ref)


def identifier_hmac_k(hmac_key: bytes, id_type: str, canonical_value: str) -> str:
    """Blocking key for exact identifier matching without decrypting (MDM, Phase 5)."""
    return hmac_hex(hmac_key, f"ID|{id_type}|{canonical_value}")


def identifier_hmac(keys: Keys, id_type: str, canonical_value: str) -> str:
    return identifier_hmac_k(keys.hmac_key, id_type, canonical_value)


def key_hmac(hmac_key: bytes, event_key: str) -> str:
    """Ledger key for business keys that ARE identifiers (e.g. CRM customer ids)."""
    return "h:" + hmac_hex(hmac_key, "KEY|" + event_key)[:32]


def new_dek() -> bytes:
    return secrets.token_bytes(32)


def wrap_dek(keys: Keys, token: str, dek: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(keys.kek).encrypt(nonce, dek, f"DEK|{token}".encode())


def unwrap_dek(keys: Keys, token: str, wrapped: bytes | None) -> bytes:
    if wrapped is None:
        raise PermissionError(f"DEK for {token} has been shredded")
    return AESGCM(keys.kek).decrypt(wrapped[:12], wrapped[12:], f"DEK|{token}".encode())


def encrypt_field(dek: bytes, token: str, column: str, plaintext: str | None) -> str | None:
    if plaintext is None or plaintext == "":
        return None
    nonce = secrets.token_bytes(12)
    ct = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), f"{token}|{column}".encode())
    return "v1:" + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_field(dek: bytes, token: str, column: str, ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    if not ciphertext.startswith("v1:"):
        raise ValueError("unknown ciphertext format")
    raw = base64.b64decode(ciphertext[3:])
    try:
        return AESGCM(dek).decrypt(raw[:12], raw[12:], f"{token}|{column}".encode()).decode("utf-8")
    except InvalidTag as e:
        raise PermissionError("ciphertext does not authenticate for this subject/column") from e


def encrypt_with_kek(keys: Keys, purpose: str, plaintext: str | None) -> str | None:
    """For the token->identifier link (security.subject_token_map), removed outright on erasure."""
    if not plaintext:
        return None
    nonce = secrets.token_bytes(12)
    return "k1:" + base64.b64encode(nonce + AESGCM(keys.kek).encrypt(nonce, plaintext.encode(), purpose.encode())
                                    ).decode("ascii")


def decrypt_with_kek(keys: Keys, purpose: str, ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    raw = base64.b64decode(ciphertext[3:])
    return AESGCM(keys.kek).decrypt(raw[:12], raw[12:], purpose.encode()).decode()

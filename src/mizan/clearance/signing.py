"""ECDSA secp256k1 signing with a self-generated TEST key (ADR-006).

The key is derived deterministically from a public label so tests are reproducible. It is a test key by
construction and must never be used for anything real; full XAdES and ZATCA CSID onboarding are out of scope
(HONESTY.md). The self-signed X.509 certificate exists only to provide QR tags 8 (public key) and 9
(certificate signature) as raw bytes.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.x509.oid import NameOID

_CURVE = ec.SECP256K1()
_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_ALG = ec.ECDSA(utils.Prehashed(hashes.SHA256()))


@dataclass(frozen=True)
class EgsSigner:
    egs_id: str
    generation: int
    private_key: ec.EllipticCurvePrivateKey
    certificate: x509.Certificate

    @property
    def public_key_der(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    @property
    def public_key_point(self) -> bytes:
        """The bare uncompressed EC point (0x04 || X || Y), 65 bytes for secp256k1.

        QR tag 8 carries the public key itself, not the DER SubjectPublicKeyInfo wrapper that
        public_key_der returns. The wrapper costs 23 extra bytes, which the QR cannot afford against
        ZATCA's 500-character cap (BR-CL-KSA-14).
        """
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    @property
    def certificate_der_b64(self) -> str:
        return base64.b64encode(self.certificate.public_bytes(serialization.Encoding.DER)).decode("ascii")

    @property
    def certificate_signature(self) -> bytes:
        return self.certificate.signature

    def sign_digest(self, digest: bytes) -> bytes:
        """Sign the 32-byte invoice digest (the invoice hash before base64)."""
        if len(digest) != 32:
            raise ValueError("digest must be 32 bytes (SHA-256)")
        return self.private_key.sign(digest, _ALG)


def spki_from_point(point: bytes) -> bytes:
    """Bare uncompressed EC point -> DER SubjectPublicKeyInfo, the inverse of public_key_point.

    Verifiers load SPKI, but the QR carries only the point, so a reader of the QR has to put the
    secp256k1 wrapper back before it can check the signature.
    """
    pub = ec.EllipticCurvePublicKey.from_encoded_point(_CURVE, point)
    return pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def ecdsa_der_to_raw(der: bytes) -> bytes:
    """DER SEQUENCE{INTEGER r, INTEGER s} -> fixed-width r || s (32 bytes each on secp256k1).

    DER stores r and s as minimal signed integers, so their length varies and a leading 0x00 appears
    whenever the top bit is set. ZATCA's QR carries the fixed-width form, which is also 6-8 bytes
    shorter -- and the QR has no room to spare (BR-CL-KSA-14 caps it at 500 characters).
    """
    if not der or der[0] != 0x30:
        raise ValueError("not a DER ECDSA signature")
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    if der[i] != 0x02:
        raise ValueError("expected INTEGER r")
    r_len = der[i + 1]
    r = der[i + 2:i + 2 + r_len]
    j = i + 2 + r_len
    if der[j] != 0x02:
        raise ValueError("expected INTEGER s")
    s_len = der[j + 1]
    s = der[j + 2:j + 2 + s_len]
    fixed = lambda b: b.lstrip(b"\x00").rjust(32, b"\x00")  # noqa: E731
    if len(fixed(r)) != 32 or len(fixed(s)) != 32:
        raise ValueError("r or s does not fit 32 bytes")
    return fixed(r) + fixed(s)


def verify_digest(public_key_der: bytes, signature: bytes, digest: bytes) -> bool:
    pub = serialization.load_der_public_key(public_key_der)
    if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name != "secp256k1":
        return False
    try:
        pub.verify(signature, digest, _ALG)
        return True
    except InvalidSignature:
        return False


@lru_cache(maxsize=64)
def signer_for(egs_id: str, generation: int = 1) -> EgsSigner:
    """generation increments when a CSID is 'renewed' (AUTH_HOLD path)."""
    seed = hashlib.sha256(f"MIZAN-KSA TEST KEY - NOT FOR PRODUCTION - {egs_id} - gen{generation}".encode()).digest()
    key = ec.derive_private_key(int.from_bytes(seed, "big") % (_ORDER - 1) + 1, _CURVE)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{egs_id} TEST"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MIZAN-KSA test EGS")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(int.from_bytes(seed[:8], "big") | 1)
            .not_valid_before(datetime(2026, 1, 1, tzinfo=UTC))
            .not_valid_after(datetime(2027, 12, 31, tzinfo=UTC))
            .sign(key, hashes.SHA256()))
    return EgsSigner(egs_id, generation, key, cert)

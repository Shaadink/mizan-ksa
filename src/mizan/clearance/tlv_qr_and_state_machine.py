# ==============================================================================
# FILE: src/mizan/clearance/tlv_qr_and_state_machine.py        (v1.1 design freeze)
# Reference code from spec Section 8 (Modules 1 & 2), kept faithful; additions are marked.
# ==============================================================================
import base64
import hashlib

from lxml import etree

# Genesis PIH = base64 of the HEX STRING of sha256("0") -> "NWZlY2Vi...OQ=="
GENESIS_PIH = base64.b64encode(hashlib.sha256(b"0").hexdigest().encode("ascii")).decode("ascii")

NS = {"ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
      "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
      "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"}

_EXCLUDED = ("//ext:UBLExtensions", "//cac:Signature",
             "//cac:AdditionalDocumentReference[cbc:ID='QR']")

# Hardened parser (addition): no DTDs, no entity expansion, no network.
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def parse_invoice_xml(xml_bytes: bytes):
    """Addition: hardened parse. Invoices never carry a DOCTYPE, so any DOCTYPE is refused outright."""
    root = etree.fromstring(xml_bytes, parser=_PARSER)
    if root.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE is not allowed in an invoice")
    return root


def canonical_bytes_for_hash(xml_bytes: bytes) -> bytes:
    """C14N 1.0 (inclusive, no comments) of the invoice minus UBLExtensions, Signature, QR ref (ADR-005)."""
    root = parse_invoice_xml(xml_bytes)
    for xp in _EXCLUDED:
        for el in root.xpath(xp, namespaces=NS):
            el.getparent().remove(el)
    return etree.tostring(root, method="c14n", exclusive=False, with_comments=False)


def invoice_digest(xml_bytes: bytes) -> bytes:
    """Raw SHA-256 digest that the ECDSA signature covers (addition; same bytes as the hash)."""
    return hashlib.sha256(canonical_bytes_for_hash(xml_bytes)).digest()


def zatca_invoice_hash(xml_bytes: bytes) -> str:
    """I-02: hash = base64(SHA-256(C14N(xml minus UBLExtensions, Signature, QR ref))).
    Computed ONCE at signing, stored in ctl.invoice_outbox.invoice_hash, and used
    unchanged as the next document's PIH whatever ZATCA later answers."""
    return base64.b64encode(invoice_digest(xml_bytes)).decode("ascii")


def encode_zatca_tlv_tag(tag_num: int, value) -> bytes:
    """TLV length = UTF-8 BYTE length, never char count (3 Arabic chars = 6 bytes).
    Tags 1-7 are text; tags 8-9 (public key, certificate signature) are raw bytes."""
    raw = bytes(value) if isinstance(value, bytes | bytearray) else str(value).encode("utf-8")
    if not 1 <= tag_num <= 9:
        raise ValueError(f"TLV tag {tag_num} outside 1-9")
    if len(raw) > 255:
        raise ValueError(f"TLV tag {tag_num} is {len(raw)} bytes; limit is 255")
    return bytes([tag_num, len(raw)]) + raw


def build_qr_tlv_base64(fields: dict[int, object]) -> str:
    """Addition: concatenate tags 1-9 in order and base64 the result (the QR payload)."""
    if sorted(fields) != list(range(1, 10)):
        raise ValueError(f"QR needs tags 1-9 exactly, got {sorted(fields)}")
    for tag in (8, 9):
        if not isinstance(fields[tag], bytes | bytearray):
            raise TypeError(f"TLV tag {tag} must be raw bytes")
    return base64.b64encode(b"".join(encode_zatca_tlv_tag(t, fields[t]) for t in range(1, 10))).decode("ascii")


def decode_qr_tlv(qr_b64: str) -> dict[int, bytes]:
    """Addition: parse a base64 TLV payload back to {tag: raw bytes}."""
    raw = base64.b64decode(qr_b64, validate=True)
    out, i = {}, 0
    while i < len(raw):
        if i + 2 > len(raw):
            raise ValueError("truncated TLV header")
        tag, length = raw[i], raw[i + 1]
        if i + 2 + length > len(raw):
            raise ValueError(f"truncated TLV value for tag {tag}")
        out[tag] = raw[i + 2: i + 2 + length]
        i += 2 + length
    return out


# Outbox: PENDING -> SIGNED -> SUBMITTING (persisted BEFORE the HTTP call) -> outcome
OUTBOX_STATES = ("PENDING", "SIGNED", "SUBMITTING", "CLEARED", "REPORTED", "ACCEPTED_WITH_WARNINGS",
                 "CONFIRMED_REJECTION", "AUTH_HOLD", "UNKNOWN_OUTCOME")
RETRY_IDENTICAL = {"UNKNOWN_OUTCOME", "AUTH_HOLD"}
SUCCESS_STATES = {"CLEARED", "REPORTED", "ACCEPTED_WITH_WARNINGS"}


def recover_after_restart(state: str) -> str:
    """A worker that died mid-call cannot know the outcome."""
    return "UNKNOWN_OUTCOME" if state == "SUBMITTING" else state


def resolve_submission_attempt(http_status: int | None, invoice_flow: str) -> dict:
    """I-03: only 200/202/400/401/403 are definitive. Every other code (408, 429,
    5xx, gateway errors, 409, unexpected 3xx) is UNKNOWN_OUTCOME: never a new UUID/ICV.
    Addition: http_status=None means a transport failure (timeout / no response)."""
    flow = invoice_flow.strip().upper()  # CLEARANCE (B2B) | REPORTING (B2C)
    if flow not in ("CLEARANCE", "REPORTING"):
        raise ValueError(f"Unknown invoice_flow {invoice_flow!r}")
    if http_status == 200:
        state = "CLEARED" if flow == "CLEARANCE" else "REPORTED"
    elif http_status == 202:
        state = "ACCEPTED_WITH_WARNINGS"
    elif http_status == 400:
        state = "CONFIRMED_REJECTION"  # stays in chain; fix = NEW doc, new ICV
    elif http_status in (401, 403):
        state = "AUTH_HOLD"  # renew CSID, then resend identical bytes
    else:
        state = "UNKNOWN_OUTCOME"
    return {"next_state": state,
            "retry_same_bytes": state in RETRY_IDENTICAL,
            "gl_action": gl_action(flow, state)}


def gl_action(flow: str, state: str) -> str:
    """GL key = invoice_uuid (idempotent). B2C revenue is posted at the point of sale,
    never held on a ZATCA timeout. B2B posts only once ZATCA has cleared it."""
    if flow == "REPORTING":
        return "POSTED_AT_SALE"
    return "POST_ONCE" if state in ("CLEARED", "ACCEPTED_WITH_WARNINGS") else "HOLD"

"""Phase 2 core: genesis PIH, invoice hash scope (I-02), TLV byte lengths (I-04), state machine (I-03), signing."""

import base64
import hashlib
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from lxml import etree

from mizan.clearance.engine import ZATCA_QR_MAX_CHARS, build_invoice_qr
from mizan.clearance.signing import signer_for, verify_digest
from mizan.clearance.tlv_qr_and_state_machine import (
    GENESIS_PIH,
    build_qr_tlv_base64,
    decode_qr_tlv,
    encode_zatca_tlv_tag,
    gl_action,
    invoice_digest,
    recover_after_restart,
    resolve_submission_attempt,
    zatca_invoice_hash,
)
from mizan.clearance.ubl import attach_signature_and_qr, build_unsigned_xml, read_refs
from mizan.generator import catalog as cat

ARABIC = st.text(alphabet=st.characters(min_codepoint=0x0600, max_codepoint=0x06FF), min_size=0, max_size=60)


@pytest.fixture(scope="module")
def sample_req(gen_dir):
    with (gen_dir / "zatca/invoice_requests.jsonl").open(encoding="utf-8") as f:
        return json.loads(f.readline())


# ---------------------------------------------------------------- genesis + hash scope

def test_genesis_pih_is_base64_of_hex_string():
    assert GENESIS_PIH == base64.b64encode(hashlib.sha256(b"0").hexdigest().encode()).decode()
    assert GENESIS_PIH.startswith("NWZlY2Vi") and GENESIS_PIH.endswith("OQ==")
    assert GENESIS_PIH != base64.b64encode(hashlib.sha256(b"0").digest()).decode()  # the v1.0 defect


def _signed(req, icv=1, pih=GENESIS_PIH, sig="U0lH", cert="Q0VSVA==", qr="UVI="):
    unsigned = build_unsigned_xml(req, icv=icv, pih=pih)
    # ds:SignedInfo carries the invoice digest; it lives inside UBLExtensions, which the hash excludes.
    invoice_hash = base64.b64encode(invoice_digest(unsigned)).decode("ascii")
    return unsigned, attach_signature_and_qr(unsigned, signature_b64=sig, certificate_b64=cert, qr_b64=qr,
                                             invoice_hash=invoice_hash)


def test_hash_ignores_signature_extensions_and_qr(sample_req):
    unsigned, signed = _signed(sample_req)
    _, signed2 = _signed(sample_req, sig="T1RIRVI=", cert="T1RIRVI=", qr="T1RIRVI=")
    assert zatca_invoice_hash(unsigned) == zatca_invoice_hash(signed) == zatca_invoice_hash(signed2)


def test_hash_changes_with_business_content(sample_req):
    a, _ = _signed(sample_req)
    changed = dict(sample_req, total_incl_vat_sar="999999.99")
    b, _ = _signed(changed)
    assert zatca_invoice_hash(a) != zatca_invoice_hash(b)


def test_hash_covers_icv_and_pih(sample_req):
    a, _ = _signed(sample_req, icv=1)
    b, _ = _signed(sample_req, icv=2)
    c, _ = _signed(sample_req, icv=1, pih="b3RoZXI=")
    assert len({zatca_invoice_hash(x) for x in (a, b, c)}) == 3


def test_hash_is_c14n_stable_under_attribute_order_and_whitespace_in_tags(sample_req):
    unsigned, _ = _signed(sample_req)
    root = etree.fromstring(unsigned)
    reserialised = etree.tostring(root, xml_declaration=False, encoding="UTF-8")
    assert zatca_invoice_hash(unsigned) == zatca_invoice_hash(reserialised)


def test_parser_refuses_entity_expansion():
    evil = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&e;</Invoice>')
    with pytest.raises(ValueError, match="DOCTYPE"):
        invoice_digest(evil)


def test_refs_round_trip(sample_req):
    _, signed = _signed(sample_req, icv=7, pih="cGloLXZhbHVl")
    refs = read_refs(signed)
    assert refs["icv"] == "7" and refs["pih"] == "cGloLXZhbHVl" and refs["uuid"] == sample_req["invoice_uuid"]
    assert refs["qr"] == "UVI="


# ---------------------------------------------------------------- TLV (I-04)

def test_tlv_counts_utf8_bytes_not_chars():
    v = "\u0639\u0644\u064A"  # 3 chars, 6 bytes
    assert encode_zatca_tlv_tag(1, v) == bytes([1, 6]) + v.encode("utf-8")


@settings(max_examples=300)
@given(ARABIC, st.integers(min_value=1, max_value=7))
def test_tlv_length_is_utf8_bytes_property(text, tag):
    raw = text.encode("utf-8")
    if len(raw) > 255:
        with pytest.raises(ValueError):
            encode_zatca_tlv_tag(tag, text)
    else:
        out = encode_zatca_tlv_tag(tag, text)
        assert out[0] == tag and out[1] == len(raw) and out[2:] == raw


@given(st.binary(min_size=0, max_size=255))
def test_tags_8_9_are_raw_bytes(raw):
    assert encode_zatca_tlv_tag(8, raw) == bytes([8, len(raw)]) + raw


def test_tlv_rejects_bad_tag_and_oversize():
    with pytest.raises(ValueError):
        encode_zatca_tlv_tag(10, "x")
    with pytest.raises(ValueError):
        encode_zatca_tlv_tag(1, "\u0639" * 128)  # 256 bytes


def test_qr_round_trip_and_raw_tag_enforcement():
    signer = signer_for("EGS-T")
    fields = {1: "\u0645\u062C\u0645\u0648\u0639\u0629", 2: "300000000000003", 3: "2026-02-12T10:00:00",
              4: "115.00", 5: "15.00", 6: "aGFzaA==", 7: b"sig", 8: signer.public_key_der,
              9: signer.certificate_signature}
    decoded = decode_qr_tlv(build_qr_tlv_base64(fields))
    assert decoded[1].decode("utf-8") == fields[1]
    assert decoded[7] == b"sig"                                    # tag 7 is raw, like 8 and 9
    assert decoded[8] == signer.public_key_der and decoded[9] == signer.certificate_signature
    with pytest.raises(TypeError):
        build_qr_tlv_base64({**fields, 8: "not-bytes"})


def test_qr_fits_zatca_500_char_limit():
    """BR-CL-KSA-14 caps the QR at 500 characters, and the margin here is four.

    The guard runs every QR through build_invoice_qr, the same function the engine signs with, because
    the previous version of this test built the fields itself and drifted: it still used the raw
    signature, the DER public key and the DER certificate signature after the engine had moved to
    base64 tag 7, the bare EC point and raw r||s. It was measuring an encoding no invoice has used
    since, landing on 504 characters whenever the ECDSA signature DER-encoded to 72 bytes -- about one
    run in four, which is why it failed intermittently and was written off as flaky.

    The ECDSA signature is the only part whose length varies (69-72 bytes DER, so 92 or 96 base64
    characters), so every signature length is exercised here rather than whichever one the first
    signature happens to produce. Lengthen the seller name, or let the totals grow by a few digits,
    and this fails with a clear reason instead of being rejected by ZATCA later.
    """
    signer = signer_for("EGS-T")
    req = {"seller": {"name_ar": cat.SELLER_NAME_AR, "vat_number": cat.SELLER_VAT},
           "issue_ts_utc": "2026-02-12T07:00:00Z",
           "total_incl_vat_sar": "1085.60", "vat_total_sar": "1023.30"}   # longest totals in the dataset
    invoice_hash = base64.b64encode(b"x" * 32).decode()                   # SHA-256 base64 = 44 chars
    seen = {}
    for i in range(400):
        sig = signer.sign_digest(hashlib.sha256(f"probe-{i}".encode()).digest())
        qr = build_invoice_qr(req, invoice_hash=invoice_hash,
                              sig_b64=base64.b64encode(sig).decode("ascii"), signer=signer)
        seen.setdefault(len(sig), set()).add(len(qr))
        assert len(qr) <= ZATCA_QR_MAX_CHARS, (
            f"QR is {len(qr)} characters with a {len(sig)}-byte signature, over ZATCA's 500 limit "
            "(BR-CL-KSA-14). Shorten the seller name, or move another tag to raw bytes.")
    assert max(seen) >= 71, f"only saw {sorted(seen)}-byte signatures; the long ones went unmeasured"
    assert max(max(v) for v in seen.values()) == 496, "the four characters of headroom have moved"


# ---------------------------------------------------------------- state machine (I-03)

@pytest.mark.parametrize("status,flow,state,retry,gl", [
    (200, "REPORTING", "REPORTED", False, "POSTED_AT_SALE"),
    (200, "CLEARANCE", "CLEARED", False, "POST_ONCE"),
    (202, "CLEARANCE", "ACCEPTED_WITH_WARNINGS", False, "POST_ONCE"),
    (400, "CLEARANCE", "CONFIRMED_REJECTION", False, "HOLD"),
    (401, "CLEARANCE", "AUTH_HOLD", True, "HOLD"),
    (403, "REPORTING", "AUTH_HOLD", True, "POSTED_AT_SALE"),
    (None, "CLEARANCE", "UNKNOWN_OUTCOME", True, "HOLD"),
    (None, "REPORTING", "UNKNOWN_OUTCOME", True, "POSTED_AT_SALE"),
])
def test_definitive_status_table(status, flow, state, retry, gl):
    r = resolve_submission_attempt(status, flow)
    assert (r["next_state"], r["retry_same_bytes"], r["gl_action"]) == (state, retry, gl)


# 303 is excluded because it is not an outcome at all: ZATCA uses it to say "clearance is switched off,
# send this to the reporting endpoint" (Detailed Technical Guideline v2). It gets its own cases below.
# This test caught the 303 change the moment it landed, which is exactly what it is for -- the rule it
# encodes is frozen (CLAUDE.md, spec Section 12) and must not drift by accident.
@given(st.integers(min_value=100, max_value=599).filter(lambda s: s not in (200, 202, 400, 401, 403, 303)))
def test_every_other_status_is_unknown_outcome(status):
    assert resolve_submission_attempt(status, "CLEARANCE")["next_state"] == "UNKNOWN_OUTCOME"


def test_303_on_clearance_is_a_redirect_and_not_an_outcome():
    """The document stays in SUBMITTING and is re-sent to the reporting endpoint, identical in every way."""
    r = resolve_submission_attempt(303, "CLEARANCE")
    assert r["next_state"] == "SUBMITTING"
    assert r["resubmit_to"] == "REPORTING"
    assert r["retry_same_bytes"] is True
    assert r["gl_action"] == "HOLD", "nothing may post until ZATCA has actually accepted the document"


def test_303_on_a_simplified_document_stays_unknown():
    """A B2C document never went to the clearance endpoint, so a 303 about it means nothing ZATCA defines.
    Reading it as 'go to reporting' would be acting on a status that cannot have been meant for us."""
    assert resolve_submission_attempt(303, "REPORTING")["next_state"] == "UNKNOWN_OUTCOME"


def test_a_standard_document_accepted_by_reporting_is_reported_and_posts():
    """After the redirect, the SAME 200 means something different: accepted by reporting, not cleared."""
    r = resolve_submission_attempt(200, "CLEARANCE", "REPORTING")
    assert r["next_state"] == "REPORTED"
    assert r["gl_action"] == "POST_ONCE", (
        "the B2B hold was waiting for ZATCA to accept the document, and ZATCA has")


def test_flow_is_case_folded_and_unknown_flow_fails_closed():
    assert resolve_submission_attempt(200, " reporting ")["next_state"] == "REPORTED"
    with pytest.raises(ValueError):
        resolve_submission_attempt(200, "B2C")


def test_restart_recovery():
    assert recover_after_restart("SUBMITTING") == "UNKNOWN_OUTCOME"
    assert recover_after_restart("REPORTED") == "REPORTED"


def test_gl_action_b2c_never_held():
    for state in ("UNKNOWN_OUTCOME", "AUTH_HOLD", "CONFIRMED_REJECTION", "SUBMITTING"):
        assert gl_action("REPORTING", state) == "POSTED_AT_SALE"
        assert gl_action("CLEARANCE", state) == "HOLD"


# ---------------------------------------------------------------- signing (ADR-006)

def test_ecdsa_secp256k1_sign_verify():
    s = signer_for("EGS-01")
    d = hashlib.sha256(b"invoice").digest()
    sig = s.sign_digest(d)
    assert s.private_key.curve.name == "secp256k1"
    assert verify_digest(s.public_key_der, sig, d)
    assert not verify_digest(s.public_key_der, sig, hashlib.sha256(b"tampered").digest())


def test_test_key_is_deterministic_per_egs_and_generation():
    assert signer_for("EGS-01").public_key_der == signer_for("EGS-01").public_key_der
    assert signer_for("EGS-01").public_key_der != signer_for("EGS-02").public_key_der
    assert signer_for("EGS-01", 1).public_key_der != signer_for("EGS-01", 2).public_key_der

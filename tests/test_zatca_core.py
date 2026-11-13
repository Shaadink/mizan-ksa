"""Phase 2 core: genesis PIH, invoice hash scope (I-02), TLV byte lengths (I-04), state machine (I-03), signing."""

import base64
import hashlib
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from lxml import etree

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
    return unsigned, attach_signature_and_qr(unsigned, signature_b64=sig, certificate_b64=cert, qr_b64=qr)


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
              4: "115.00", 5: "15.00", 6: "aGFzaA==", 7: "c2ln", 8: signer.public_key_der,
              9: signer.certificate_signature}
    decoded = decode_qr_tlv(build_qr_tlv_base64(fields))
    assert decoded[1].decode("utf-8") == fields[1]
    assert decoded[8] == signer.public_key_der and decoded[9] == signer.certificate_signature
    with pytest.raises(TypeError):
        build_qr_tlv_base64({**fields, 8: "not-bytes"})


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


@given(st.integers(min_value=100, max_value=599).filter(lambda s: s not in (200, 202, 400, 401, 403)))
def test_every_other_status_is_unknown_outcome(status):
    assert resolve_submission_attempt(status, "CLEARANCE")["next_state"] == "UNKNOWN_OUTCOME"


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

"""Phase 3 (pure Python): CP1256 three cases, encrypt-on-land primitives, Module 4 reference validators."""

import base64
import os
import secrets

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mizan.generator.build import mojibake
from mizan.ingest.cp1256 import decode_cp1256_bytes, repair_text
from mizan.mdm.arabic_norm_and_privacy import (
    build_arabic_search_key,
    validate_saudi_10digit_id,
    validate_unified_700,
    validate_vat_number,
)
from mizan.privacy import crypto

NAME = "\u0645\u062D\u0645\u062F \u0628\u0644\u0627\u0644 \u0627\u0644\u0639\u062A\u064A\u0628\u064A"
CP1256_ARABIC = st.text(alphabet=st.sampled_from(
    [chr(c) for c in range(0x0621, 0x064B) if chr(c).encode("cp1256", "ignore")] + [" "]), min_size=1, max_size=30)


@pytest.fixture
def keys():
    return crypto.Keys(secrets.token_bytes(32), secrets.token_bytes(32))


# ---------------------------------------------------------------- CP1256 (3 cases)

def test_case1_raw_cp1256_bytes():
    assert decode_cp1256_bytes(NAME.encode("cp1256")) == NAME


def test_case1_needs_the_declared_encoding():
    """cp1256 maps every byte, so the source's declared encoding is what keeps decoding honest:
    the same bytes read as UTF-8 fail loudly instead of becoming garbage."""
    raw = NAME.encode("cp1256")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert decode_cp1256_bytes(raw) == NAME


def test_case2_mojibake_repaired_with_round_trip():
    assert repair_text(mojibake(NAME)) == (NAME, "REPAIRED_MOJIBAKE")


@given(CP1256_ARABIC)
def test_case2_property_any_cp1256_arabic(text):
    if not text.strip():
        return
    repaired, status = repair_text(mojibake(text))
    assert (repaired, status) == (text, "REPAIRED_MOJIBAKE")


def test_case3_question_marks_unrecoverable():
    assert repair_text("????? ????") == (None, "UNRECOVERABLE")


@pytest.mark.parametrize("clean", [NAME, "Mohammed Al Otaibi", "Caf\u00E9 Riyadh", "", None, "Q?"])
def test_clean_text_passes_through(clean):
    text, status = repair_text(clean)
    assert status == "CLEAN" and text == clean


# ---------------------------------------------------------------- encrypt on land

def test_subject_token_deterministic_and_keyed(keys):
    a = crypto.subject_token(keys, "POS-C000001")
    assert a == crypto.subject_token(keys, "POS-C000001") and a.startswith("sub_")
    other = crypto.Keys(secrets.token_bytes(32), keys.kek)
    assert crypto.subject_token(other, "POS-C000001") != a
    assert crypto.subject_token(keys, "") is None  # WALK_IN


def test_field_encryption_round_trip_and_binding(keys):
    dek = crypto.new_dek()
    ct = crypto.encrypt_field(dek, "sub_a", "full_name_ar", NAME)
    assert NAME not in ct and ct.startswith("v1:")
    assert crypto.decrypt_field(dek, "sub_a", "full_name_ar", ct) == NAME
    with pytest.raises(PermissionError):  # moved to another subject
        crypto.decrypt_field(dek, "sub_b", "full_name_ar", ct)
    with pytest.raises(PermissionError):  # moved to another column
        crypto.decrypt_field(dek, "sub_a", "mobile", ct)
    with pytest.raises(PermissionError):  # wrong key = shredded key
        crypto.decrypt_field(crypto.new_dek(), "sub_a", "full_name_ar", ct)


def test_dek_wrap_and_shred(keys):
    dek = crypto.new_dek()
    wrapped = crypto.wrap_dek(keys, "sub_a", dek)
    assert crypto.unwrap_dek(keys, "sub_a", wrapped) == dek
    with pytest.raises(PermissionError):
        crypto.unwrap_dek(keys, "sub_a", None)


def test_keys_come_from_env(monkeypatch):
    k = base64.b64encode(secrets.token_bytes(32)).decode()
    monkeypatch.setenv("MIZAN_HMAC_KEY_B64", k)
    monkeypatch.setenv("MIZAN_KEK_B64", k)
    assert len(crypto.Keys.from_env().kek) == 32
    monkeypatch.setenv("MIZAN_KEK_B64", base64.b64encode(b"short").decode())
    with pytest.raises(RuntimeError):
        crypto.Keys.from_env()


def test_env_file_is_gitignored_and_not_tracked():
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tracked = subprocess.run(["git", "ls-files", ".env"], cwd=root, capture_output=True, text=True).stdout
    assert tracked.strip() == ""


# ---------------------------------------------------------------- Module 4 reference validators

def test_arabic_indic_id_folded_to_canonical():
    import random

    from mizan.common.saudi_ids import mint_saudi_id, to_arabic_indic
    v = mint_saudi_id(random.Random(5), "1")
    assert validate_saudi_10digit_id(to_arabic_indic(v)) == v
    assert validate_saudi_10digit_id("3" + v[1:]) is None
    assert validate_saudi_10digit_id("\u00E9") is None  # v1.0 crashed on this


def test_vat_and_700_validators():
    assert validate_vat_number("300000000000003") == "300000000000003"
    assert validate_vat_number("300000000000004") is None
    assert validate_unified_700("7001234567") == "7001234567"
    assert validate_unified_700("6001234567") is None


def test_search_key_folds_ligature_tashkeel_and_spacing():
    plain = build_arabic_search_key(NAME)
    lig = build_arabic_search_key("\u0645\u064F\u062D\u064E\u0645\u0651\u064E\u062F  \u0628\uFEFB\u0644 "
                                  "\u0627\u0644\u0639\u064F\u062A\u064E\u064A\u0652\u0628\u0650\u064A")
    assert plain == lig

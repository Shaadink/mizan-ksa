# ==============================================================================
# FILE: src/mizan/mdm/arabic_norm_and_privacy.py              (v1.1 design freeze)
# Reference code from spec Section 8 (Modules 4, 5 & 6), kept faithful.
# All Arabic literals are \u escapes: right-to-left text reverses arguments in PDFs.
# ==============================================================================
import re
import unicodedata

TASHKEEL_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670]")
ALEF_RE = re.compile(r"[\u0623\u0625\u0622\u0671]")  # alef variants
ARABIC_INDIC_MAP = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
                                 "\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9",
                                 "01234567890123456789")
ABD_AL, ABDAL = "\u0639\u0628\u062F \u0627\u0644", "\u0639\u0628\u062F\u0627\u0644"


def build_arabic_search_key(raw_text: str) -> str:
    """Lossy blocking key ONLY; the raw legal name stays untouched in slv.golden_party_scd2."""
    s = unicodedata.normalize("NFKC", raw_text or "")  # \uFEFB -> \u0644\u0627
    s = TASHKEEL_RE.sub("", s).replace("\u0640", "").translate(ARABIC_INDIC_MAP)
    s = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()  # collapse FIRST
    s = ALEF_RE.sub("\u0627", s).replace("\u0629", "\u0647").replace("\u0649", "\u064A")
    return s.replace(ABD_AL, ABDAL)


def validate_saudi_10digit_id(id_str: str):
    """National ID (1...) / Iqama (2...) Luhn-style check. Returns the CANONICAL ASCII
    form (Arabic-Indic digits folded) or None. Store only the returned value."""
    s = (id_str or "").strip().translate(ARABIC_INDIC_MAP)
    if not re.fullmatch(r"[12][0-9]{9}", s):
        return None
    total = sum(((2 * int(c)) // 10 + (2 * int(c)) % 10) if i % 2 == 0 else int(c)
                for i, c in enumerate(s))
    return s if total % 10 == 0 else None


def validate_vat_number(vat: str):
    s = (vat or "").strip().translate(ARABIC_INDIC_MAP)
    return s if re.fullmatch(r"3[0-9]{13}3", s) else None


def validate_unified_700(num: str):
    """FORMAT-ONLY: no public checksum is claimed for the 700 Unified Number."""
    s = (num or "").strip().translate(ARABIC_INDIC_MAP)
    return s if re.fullmatch(r"7[0-9]{9}", s) else None


LEGAL_HOLD_CLASSES = {"TAX", "SAMA"}
VALID_HOLD_CLASSES = LEGAL_HOLD_CLASSES | {"CONSENT"}


def execute_pdpl_erasure_decision(subject_token: str, legal_hold_class: str,
                                  vault_store: dict, tombstone_set: set,
                                  token_map: dict) -> dict:
    """Signed tax XML (audit.zatca_chain_journal) stays LEGAL_HOLD_RETAINED; every other
    copy of the subject's PII (Bronze, Silver, Gold, exports, AI chunks) is crypto-shredded.
    Fails closed on an unknown class. Caller must then VACUUM the vault table (Patch E)."""
    cls = (legal_hold_class or "").strip().upper()
    if cls not in VALID_HOLD_CLASSES:
        raise ValueError(f"Unknown legal_hold_class {legal_hold_class!r}: refusing to decide")
    tombstone_set.add(subject_token)  # ctl.deletion_tombstones: Restore Guard
    if subject_token in vault_store:
        vault_store[subject_token]["wrapped_dek"] = None
        vault_store[subject_token]["status"] = "SHREDDED"
    token_map.pop(subject_token, None)  # break token -> National ID link
    return {"subject_token": subject_token,
            "analytical_pii_status": "CRYPTO_SHREDDED_UNRECOVERABLE",
            "signed_tax_invoice_status": ("LEGAL_HOLD_RETAINED" if cls in LEGAL_HOLD_CLASSES
                                          else "PURGE_SCHEDULED"),
            "restore_guard_tombstone": True,
            "vault_vacuum_required": True}

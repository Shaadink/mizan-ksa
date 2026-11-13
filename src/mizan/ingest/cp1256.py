"""Windows-1256 repair, the three cases of spec Module 4 (decoding in Python, never Spark's CSV option).

  case 1  raw bytes from a legacy export     -> bytes.decode("cp1256")             DECODED_CP1256
  case 2  mojibake (CP1256 bytes read as CP1252 / latin-1) -> re-encode, decode cp1256, and accept only if
          re-applying the corruption reproduces the input exactly (round-trip check)   REPAIRED_MOJIBAKE
  case 3  literal '?????' (the bytes were lost before we got them)       -> UNRECOVERABLE -> quarantine
Anything already-clean Unicode passes through as CLEAN.
"""

from __future__ import annotations

import re

STATUSES = ("CLEAN", "DECODED_CP1256", "REPAIRED_MOJIBAKE", "UNRECOVERABLE")
_ARABIC = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_QMARKS = re.compile(r"^[\s?]*\?{3,}[\s?]*$")
# characters a CP1256->CP1252 mis-decode produces: Latin-1 supplement, C1 controls, and CP1252's 0x80-0x9F glyphs
_MOJI_CHARS = re.compile(r"[\u0080-\u00FF\u0152\u0153\u0160\u0161\u0178\u017D\u017E\u0192\u02C6\u02DC"
                         r"\u2013\u2014\u2018-\u201E\u2020-\u2022\u2026\u2030\u2039\u203A\u20AC\u2122]")


def decode_cp1256_bytes(raw: bytes) -> str:
    """Case 1. Strict: an undecodable byte is an error, not a silent replacement."""
    return raw.decode("cp1256")


def _to_cp1252_bytes(s: str) -> bytes | None:
    out = bytearray()
    for c in s:
        o = ord(c)
        if o < 0x80:
            out.append(o)
            continue
        try:
            out += c.encode("cp1252")
        except UnicodeEncodeError:
            if o <= 0xFF:          # latin-1 fallback for CP1252's five undefined bytes
                out.append(o)
            else:
                return None
    return bytes(out)


def _mojibake(text: str) -> str:
    chars = []
    for b in text.encode("cp1256"):
        try:
            chars.append(bytes([b]).decode("cp1252"))
        except UnicodeDecodeError:
            chars.append(chr(b))
    return "".join(chars)


def repair_text(s: str | None) -> tuple[str | None, str]:
    """Returns (text, status) for an already-decoded string (cases 2 and 3; clean passthrough)."""
    if s is None or s == "":
        return s, "CLEAN"
    if _QMARKS.match(s):
        return None, "UNRECOVERABLE"
    if _ARABIC.search(s) or not _MOJI_CHARS.search(s):
        return s, "CLEAN"
    raw = _to_cp1252_bytes(s)
    if raw is None:
        return s, "CLEAN"
    try:
        candidate = raw.decode("cp1256")
    except UnicodeDecodeError:
        return s, "CLEAN"
    if _ARABIC.search(candidate) and _mojibake(candidate) == s:
        return candidate, "REPAIRED_MOJIBAKE"
    return s, "CLEAN"

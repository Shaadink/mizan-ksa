r"""Parse a REAL ZATCA QR from a real Saudi receipt with MIZAN's own TLV decoder.

    .\.venv\Scripts\python.exe scripts\decode_real_zatca_qr.py "<base64 from the QR>"
    .\.venv\Scripts\python.exe scripts\decode_real_zatca_qr.py --file payload.txt

**Why this exists.** `decode_qr_tlv` and `encode_zatca_tlv_tag` were written from ZATCA's specification and
have only ever been tested against invoices this project generated itself -- which means they have only
ever been tested against one reading of the spec. Mine. A real receipt from a real Saudi POS, signed by a
real EGS device, is the first independent input they have seen.

The case most likely to be wrong is tag 1, the seller's name in Arabic. The rule is that a TLV length is
the **UTF-8 byte** length and never the character count, so an Arabic name is where a char-count bug
shows. Every seller name in `data/generated` was chosen by this project, so the generated data cannot
find that class of bug; somebody else's receipt can.

**Privacy.** The payload identifies a real business: tag 1 is its registered name and tag 2 its VAT
registration number. Those are printed on every receipt it issues and are not secret, but they are not
ours to republish, so this prints them redacted by default. `--show-identifiers` prints them in full for
local inspection and should never be used to produce something that gets committed or posted.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mizan.clearance.tlv_qr_and_state_machine import decode_qr_tlv  # noqa: E402

# ZATCA Detailed Technical Guideline, QR specification. Tags 1-7 are text; 8 and 9 are raw bytes.
TAGS = {1: "seller name", 2: "VAT registration number", 3: "timestamp (ISO 8601)",
        4: "invoice total (incl. VAT)", 5: "VAT total", 6: "invoice hash (base64 SHA-256)",
        7: "ECDSA signature (base64)", 8: "public key (raw bytes)", 9: "certificate signature (raw bytes)"}
IDENTIFYING = (1, 2)


def report(payload: str, show_identifiers: bool) -> int:
    raw = base64.b64decode(payload, validate=True)
    print(f"payload   {len(payload)} base64 chars -> {len(raw)} bytes")
    fields = decode_qr_tlv(payload)
    print(f"parsed    {len(fields)} TLV tags: {sorted(fields)}\n")

    worst = 0
    for tag in sorted(fields):
        value = fields[tag]
        worst = max(worst, len(value))
        name = TAGS.get(tag, "unknown tag")
        if tag in (8, 9):
            shown = f"<{len(value)} raw bytes> {value[:8].hex()}..."
        else:
            text = value.decode("utf-8")
            if tag in IDENTIFYING and not show_identifiers:
                shown = f"[redacted, {len(text)} chars / {len(value)} UTF-8 bytes]"
            else:
                shown = text
        print(f"  tag {tag}  {name:<28} {len(value):>3} bytes  {shown}")

    print()
    problems = []
    if sorted(fields) != list(range(1, 10)):
        problems.append(f"expected tags 1-9, got {sorted(fields)}")
    if worst > 255:
        problems.append(f"a value is {worst} bytes; the TLV limit is 255")
    for tag in (1, 2, 3, 4, 5, 6, 7):
        try:
            fields[tag].decode("utf-8")
        except (KeyError, UnicodeDecodeError) as exc:
            problems.append(f"tag {tag} is not valid UTF-8 text: {exc}")

    # The point of the exercise: an Arabic seller name is where a char-count bug would show.
    if 1 in fields:
        name_bytes, name_chars = len(fields[1]), len(fields[1].decode("utf-8", "replace"))
        if name_bytes != name_chars:
            print(f"tag 1 is {name_bytes} UTF-8 bytes for {name_chars} characters -- a non-ASCII name, "
                  f"which is exactly the case a char-count length bug would get wrong.")

    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: 9 tags, all values within the 255-byte TLV limit (largest {worst}), tags 1-7 valid UTF-8.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payload", nargs="?", help="the base64 string from the receipt's QR code")
    ap.add_argument("--file", help="read the base64 from this file instead")
    ap.add_argument("--show-identifiers", action="store_true",
                    help="print the seller name and VAT number in full (local inspection only)")
    args = ap.parse_args()

    text = Path(args.file).read_text(encoding="utf-8").strip() if args.file else (args.payload or "").strip()
    if not text:
        raise SystemExit("give the base64 payload as an argument or with --file")
    return report(text, args.show_identifiers)


if __name__ == "__main__":
    raise SystemExit(main())

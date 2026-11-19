"""Measure the driver-side adapter boundary (ADR-008) instead of arguing about it.

The standing objection to ADR-008 is that single-threaded Python in front of a distributed engine cannot
scale. That is correct in shape and wrong in magnitude, and the only honest way to settle it is a number.
This measures the two operations that run per PII field at the Bronze write: subject tokenisation
(HMAC-SHA256) and field encryption (AES-256-GCM, random 96-bit nonce, AAD "token|column").

Run:  .\\.venv\\Scripts\\python.exe scripts\\bench_adapter.py
The numbers land in ADR-008. Re-run and update them if the machine or the crypto changes.
"""

from __future__ import annotations

import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mizan.privacy.crypto import encrypt_field, hmac_hex

ROWS = 20_000

# A realistic field: Arabic name, a sequence number so no two are identical, a Latin city and a number.
# Encryption cost is length-sensitive, so a toy "abc" would overstate throughput.
SAMPLE = "\u0645\u062D\u0645\u062F \u0627\u0644\u0642\u062D\u0637\u0627\u0646\u064A {i} Riyadh 12345"


def main() -> int:
    hmac_key = secrets.token_bytes(32)
    dek = secrets.token_bytes(32)
    values = [SAMPLE.format(i=i) for i in range(ROWS)]

    t0 = time.perf_counter()
    tokens = [hmac_hex(hmac_key, v) for v in values]
    t1 = time.perf_counter()
    for token, value in zip(tokens, values, strict=True):
        encrypt_field(dek, token, "full_name", value)
    t2 = time.perf_counter()

    hmac_rate = ROWS / (t1 - t0)
    enc_rate = ROWS / (t2 - t1)
    both = ROWS / (t2 - t0)

    print(f"fields                {ROWS:,}")
    print(f"hmac_hex              {hmac_rate:>10,.0f} fields/sec")
    print(f"encrypt_field         {enc_rate:>10,.0f} fields/sec")
    print(f"combined per field    {both:>10,.0f} fields/sec")
    print()
    # Contracts carry 3 to 7 PII columns (src/mizan/spark/contracts.py), so quote the range, not one number.
    for cols in (3, 7):
        print(f"  at {cols} PII columns/row: {both / cols:>9,.0f} rows/sec"
              f"  ({both / cols * 3600 / 1e6:>6,.0f}M rows/hour)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

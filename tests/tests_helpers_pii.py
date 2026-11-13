"""Cleartext PII probes taken from the generated source files (used to prove nothing leaked into Bronze+)."""

import csv
from pathlib import Path

from mizan.ingest.cp1256 import decode_cp1256_bytes


def cleartext_probes(gen_dir: Path, limit: int = 400) -> list[str]:
    probes: list[str] = []
    eco = list(csv.DictReader((gen_dir / "crm/crm_ecom_utf8.csv").open(encoding="utf-8", newline="")))
    import io
    pos = list(csv.DictReader(io.StringIO(decode_cp1256_bytes((gen_dir / "crm/crm_pos_cp1256.csv").read_bytes()),
                                          newline="")))
    for r in (pos + eco)[:limit]:
        for k in ("full_name_ar", "full_name_en", "national_id", "mobile", "landline", "email",
                  "spl_short_address", "source_customer_id"):
            v = r.get(k)
            if v and len(v) >= 6 and set(v) != {"?"}:
                probes.append(v)
    orders = list(csv.DictReader((gen_dir / "orders/commerce_events.csv").open(encoding="utf-8", newline="")))
    for r in orders[:limit]:
        for k in ("buyer_name", "buyer_mobile", "delivery_short_address", "customer_ref"):
            if r[k] and len(r[k]) >= 6:
                probes.append(r[k])
    return sorted(set(probes))

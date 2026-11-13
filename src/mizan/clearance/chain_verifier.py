"""Chain verifier (I-01, I-02): walk each EGS chain from the genesis PIH.

Emits rows shaped for quarantine.zatca_chain_violations:
  ICV_GAP       - ICV not exactly previous + 1 (or chain not starting at 1)
  PIH_MISMATCH  - PIH[n] != invoice_hash[n-1] (genesis for ICV 1)
  HASH_MISMATCH - recomputing the hash from the stored signed XML disagrees with the stored hash
  XML_REF_MISMATCH - ICV/PIH/UUID inside the signed XML disagree with the journal columns
"""

from __future__ import annotations

from collections import defaultdict

from mizan.clearance.tlv_qr_and_state_machine import GENESIS_PIH, zatca_invoice_hash
from mizan.clearance.ubl import read_refs

VIOLATION_TYPES = ("ICV_GAP", "PIH_MISMATCH", "HASH_MISMATCH", "XML_REF_MISMATCH")


def verify_chain(journal_rows) -> list[dict]:
    by_egs: dict[str, list[dict]] = defaultdict(list)
    for r in journal_rows:
        by_egs[r["egs_id"]].append(r)
    violations: list[dict] = []

    def flag(r, vtype, detail):
        violations.append({"egs_id": r["egs_id"], "icv": r["icv"], "invoice_uuid": r["invoice_uuid"],
                           "violation_type": vtype, "detail": detail})

    for egs in sorted(by_egs):
        expected_icv, prev_hash = 1, GENESIS_PIH
        for r in sorted(by_egs[egs], key=lambda x: x["icv"]):
            if r["icv"] != expected_icv:
                flag(r, "ICV_GAP", f"expected ICV {expected_icv}, found {r['icv']}")
            if r["pih"] != prev_hash:
                flag(r, "PIH_MISMATCH", "PIH does not equal the previous document's invoice_hash")
            if zatca_invoice_hash(r["signed_xml"]) != r["invoice_hash"]:
                flag(r, "HASH_MISMATCH", "stored invoice_hash does not match the signed XML")
            refs = read_refs(r["signed_xml"])
            if (refs["icv"], refs["pih"], refs["uuid"]) != (str(r["icv"]), r["pih"], r["invoice_uuid"]):
                flag(r, "XML_REF_MISMATCH", "ICV/PIH/UUID inside the XML differ from the journal row")
            expected_icv, prev_hash = r["icv"] + 1, r["invoice_hash"]
    return violations

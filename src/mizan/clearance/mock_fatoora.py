"""Mock ZATCA Fatoora endpoint, driven by the generator's planted fault plan.

It is NOT the real portal (HONESTY.md). It does real checks on what it receives:
  * QR tag 6 must equal the recomputed invoice hash;
  * the ECDSA signature (tag 7) must verify against the public key (tag 8) over that hash;
  * header VAT must equal the sum of line VAT (planted D04 violates this -> 400).
Scripted outcomes (per request_id, consumed one per attempt) come first:
  TRANSPORT_TIMEOUT -> raises TransportFailure (no HTTP status ever arrives)
  WORKER_CRASH_IN_SUBMITTING -> raises WorkerCrash (the worker dies mid-call)
  HTTP_<code> -> that status (200 still validates; any other code is returned verbatim)
Re-sending an already accepted UUID with identical bytes is idempotent (returns the same status).
"""

from __future__ import annotations

import base64
import copy
import hashlib
from decimal import Decimal

from mizan.clearance.signing import verify_digest
from mizan.clearance.tlv_qr_and_state_machine import decode_qr_tlv, invoice_digest
from mizan.clearance.ubl import read_refs


class TransportFailure(Exception):
    """Transport failure (5xx/timeout): the caller cannot know whether ZATCA processed the call."""


class WorkerCrash(Exception):
    """Simulated worker death between persisting SUBMITTING and receiving any response."""


class MockFatoora:
    def __init__(self, plan: dict | None = None):
        plan = plan or {}
        self._script: dict[str, list[str]] = copy.deepcopy(plan.get("responses", {}))
        self.default = plan.get("default_response", "HTTP_200")
        self.log: list[dict] = []
        self.accepted: dict[str, tuple[str, int]] = {}  # uuid -> (bytes sha256, status)
        self.csid_generation: dict[str, int] = {}

    def script(self, request_id: str, outcomes: list[str]) -> None:
        self._script[request_id] = list(outcomes)

    def renew_csid(self, egs_id: str) -> int:
        self.csid_generation[egs_id] = self.csid_generation.get(egs_id, 1) + 1
        return self.csid_generation[egs_id]

    def validate(self, xml_bytes: bytes) -> tuple[int, str]:
        refs = read_refs(xml_bytes)
        if not refs["qr"]:
            return 400, "QR_MISSING"
        tlv = decode_qr_tlv(refs["qr"])
        digest = invoice_digest(xml_bytes)
        if tlv.get(6, b"").decode("ascii", "replace") != base64.b64encode(digest).decode("ascii"):
            return 400, "INVOICE_HASH_MISMATCH"
        if not verify_digest(tlv.get(8, b""), base64.b64decode(tlv.get(7, b"")), digest):
            return 400, "SIGNATURE_INVALID"
        if Decimal(refs["vat_total"]) != sum((Decimal(v) for v in refs["line_vats"]), Decimal("0")):
            return 400, "VAT_TOTAL_MISMATCH"
        return 200, "OK"

    def submit(self, *, egs_id: str, request_id: str, invoice_uuid: str, invoice_flow: str, xml_bytes: bytes) -> int:
        sha = hashlib.sha256(xml_bytes).hexdigest()
        script = self._script.get(request_id)
        outcome = script.pop(0) if script else self.default
        self.log.append({"request_id": request_id, "invoice_uuid": invoice_uuid, "egs_id": egs_id,
                         "bytes_sha256": sha, "outcome": outcome})
        if outcome == "TRANSPORT_TIMEOUT":
            raise TransportFailure(f"timeout submitting {request_id}")
        if outcome == "WORKER_CRASH_IN_SUBMITTING":
            raise WorkerCrash(f"worker died while submitting {request_id}")
        if not outcome.startswith("HTTP_"):
            raise ValueError(f"unknown scripted outcome {outcome!r}")
        status = int(outcome.removeprefix("HTTP_"))
        if status == 200:
            if invoice_uuid in self.accepted and self.accepted[invoice_uuid][0] == sha:
                return self.accepted[invoice_uuid][1]
            status, _reason = self.validate(xml_bytes)
        if status in (200, 202):
            self.accepted[invoice_uuid] = (sha, status)
        return status

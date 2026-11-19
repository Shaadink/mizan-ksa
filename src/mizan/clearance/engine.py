"""ZATCA chain engine (Modules 1-2): per-EGS single-writer sequencer, outbox state machine, GL posting.

Tables (spec Section 7): ctl.egs_chain_state, ctl.invoice_outbox, audit.zatca_chain_journal. Phase 2 keeps
them in ChainStore (a durable-by-contract in-memory store that outlives any worker, so a "crash" loses only
the worker); Phase 3 lands the same rows as Delta tables in LH_MIZAN.

Rules enforced here (CLAUDE.md / spec Section 8):
  * ICV and PIH are minted under a per-EGS lock: one writer per EGS, no gaps.
  * invoice_hash is computed ONCE at signing and becomes the next PIH whatever ZATCA answers.
  * SUBMITTING is persisted BEFORE the HTTP call; a restart turns SUBMITTING into UNKNOWN_OUTCOME.
  * UNKNOWN_OUTCOME / AUTH_HOLD resend the identical stored bytes and UUID, never a new ICV.
  * CONFIRMED_REJECTION stays in the chain; the correction is a new document with a new ICV.
  * GL key = invoice_uuid of the sale. B2C posts at sale; B2B posts once cleared. Exactly one posting.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import threading
import uuid as uuidlib
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from mizan.clearance.mock_fatoora import TransportFailure, WorkerCrash
from mizan.clearance.signing import ecdsa_der_to_raw, signer_for
from mizan.clearance.tlv_qr_and_state_machine import (
    GENESIS_PIH,
    RETRY_IDENTICAL,
    build_qr_tlv_base64,
    invoice_digest,
    recover_after_restart,
    resolve_submission_attempt,
)
from mizan.clearance.ubl import attach_signature_and_qr, build_unsigned_xml, issue_ts_ksa
from mizan.common.money import fmt_sar

CORRECTION_NS = uuidlib.UUID("6f1d0c3e-6a43-4a49-9d1c-6d2a0b6d9a11")

ZATCA_QR_MAX_CHARS = 500          # BR-CL-KSA-14, on the base64 string


def build_invoice_qr(req: dict, *, invoice_hash: str, sig_b64: str, signer) -> str:
    """The QR exactly as a signed invoice carries it. One definition, used by the engine and the guard.

    It lives here rather than inline because it did not: the engine encoded tag 7 as base64 text and
    tags 8-9 as the bare point and raw r||s, while the 500-character guard in the tests still built the
    older shape (raw signature bytes, DER key, DER certificate signature). The guard was therefore
    measuring 504 characters for an encoding no invoice has used since, and failing about one run in
    four, while the real QR tops out at 496. Two copies of one rule is the bug; this is the rule.
    """
    return build_qr_tlv_base64({
        1: req["seller"]["name_ar"], 2: req["seller"]["vat_number"],
        # ZATCA's QR validator compares tag 3 to IssueDate + IssueTime and wants the ISO 8601
        # "Z" form; without it the check reports "timeStamp does not match". An explicit
        # +03:00 offset would also satisfy it but costs 6 characters, and the QR has none to
        # spare against the 500-character cap (BR-CL-KSA-14).
        3: issue_ts_ksa(req["issue_ts_utc"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
        4: req["total_incl_vat_sar"], 5: req["vat_total_sar"], 6: invoice_hash, 7: sig_b64,
        # Tags 8-9 carry the key and the certificate's signature as bytes. The bare EC point
        # and the raw r||s form are what ZATCA's spec describes, and together they save 30
        # bytes against the DER wrappers -- the difference between 532 and 492 characters.
        8: signer.public_key_point, 9: ecdsa_der_to_raw(signer.certificate_signature)})


@dataclass
class OutboxRow:
    """ctl.invoice_outbox: 1 row per invoice or credit note (spec 7.1 hop 2)."""
    invoice_uuid: str
    request_id: str
    egs_id: str
    icv: int
    pih: str
    invoice_hash: str
    signed_xml: bytes
    qr_tlv_b64: str
    invoice_flow: str
    document_type: str
    order_id: str
    gl_key: str
    total_incl_vat_sar: str
    corrects_invoice_uuid: str | None = None
    state: str = "SIGNED"
    attempts: int = 0
    history: list[dict] = field(default_factory=list)


class ChainStore:
    """Durable control-plane state. Every write stores a copy, so no worker holds live references."""

    def __init__(self):
        self.egs_chain_state: dict[str, dict] = {}
        self.invoice_outbox: dict[str, OutboxRow] = {}
        self.zatca_chain_journal: dict[tuple[str, int], dict] = {}
        self.by_request_id: dict[str, str] = {}
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._guard = threading.Lock()

    def egs_lock(self, egs_id: str) -> threading.Lock:
        with self._guard:
            return self._locks[egs_id]

    def chain_head(self, egs_id: str) -> tuple[int, str]:
        s = self.egs_chain_state.get(egs_id)
        return (s["last_icv"], s["last_invoice_hash"]) if s else (0, GENESIS_PIH)

    def commit_signed(self, row: OutboxRow) -> None:
        """Atomic under the EGS lock: outbox row + legal-hold journal row + chain head advance."""
        last_icv, last_hash = self.chain_head(row.egs_id)
        if row.icv != last_icv + 1 or row.pih != last_hash:
            raise RuntimeError(f"chain head moved under {row.egs_id}: single-writer violated")
        self.invoice_outbox[row.invoice_uuid] = copy.deepcopy(row)
        self.by_request_id[row.request_id] = row.invoice_uuid
        self.zatca_chain_journal[(row.egs_id, row.icv)] = {
            "egs_id": row.egs_id, "icv": row.icv, "invoice_uuid": row.invoice_uuid, "order_id": row.order_id,
            "pih": row.pih, "invoice_hash": row.invoice_hash, "signed_xml": row.signed_xml,
            "legal_hold_class": "TAX", "retention_status": "LEGAL_HOLD_RETAINED"}
        self.egs_chain_state[row.egs_id] = {"egs_id": row.egs_id, "last_icv": row.icv,
                                            "last_invoice_hash": row.invoice_hash}

    def get(self, invoice_uuid: str) -> OutboxRow:
        return copy.deepcopy(self.invoice_outbox[invoice_uuid])

    def put(self, row: OutboxRow) -> None:
        self.invoice_outbox[row.invoice_uuid] = copy.deepcopy(row)


class GlPostingSink:
    """Stands in for the ERP posting API. Idempotent on gl_key (= the sale's invoice_uuid)."""

    def __init__(self):
        self.postings: dict[str, dict] = {}
        self.calls: dict[str, int] = defaultdict(int)

    def has(self, gl_key: str) -> bool:
        return gl_key in self.postings

    def post(self, gl_key: str, amount_sar: str, reason: str) -> None:
        self.calls[gl_key] += 1
        self.postings.setdefault(gl_key, {"gl_key": gl_key, "amount_sar": amount_sar, "reason": reason})

    def accounting_postings(self, gl_key: str) -> int:
        return 1 if gl_key in self.postings else 0


class ZatcaWorker:
    """One worker process. It can die at any time; ChainStore and the sink survive it."""

    def __init__(self, store: ChainStore, client, gl: GlPostingSink):
        self.store, self.client, self.gl = store, client, gl

    # -- signing (sequencer) ------------------------------------------------------------------
    def enqueue(self, req: dict, *, corrects: OutboxRow | None = None) -> str:
        """Mint ICV/PIH, build, hash once, sign, persist SIGNED. Idempotent on request_id."""
        existing = self.store.by_request_id.get(req["request_id"])
        if existing:
            return existing
        egs = req["egs_id"]
        with self.store.egs_lock(egs):
            existing = self.store.by_request_id.get(req["request_id"])
            if existing:
                return existing
            last_icv, last_hash = self.store.chain_head(egs)
            icv, pih = last_icv + 1, last_hash
            unsigned = build_unsigned_xml(req, icv=icv, pih=pih)
            digest = invoice_digest(unsigned)
            invoice_hash = base64.b64encode(digest).decode("ascii")
            signer = signer_for(egs)
            signature = signer.sign_digest(digest)
            sig_b64 = base64.b64encode(signature).decode("ascii")
            qr = build_invoice_qr(req, invoice_hash=invoice_hash, sig_b64=sig_b64, signer=signer)
            signed = attach_signature_and_qr(unsigned, signature_b64=sig_b64,
                                             certificate_b64=signer.certificate_der_b64, qr_b64=qr,
                                             invoice_hash=invoice_hash)
            row = OutboxRow(invoice_uuid=req["invoice_uuid"], request_id=req["request_id"], egs_id=egs, icv=icv,
                            pih=pih, invoice_hash=invoice_hash, signed_xml=signed, qr_tlv_b64=qr,
                            invoice_flow=req["invoice_flow"], document_type=req["document_type"],
                            order_id=req["order_id"],
                            gl_key=corrects.gl_key if corrects else req["invoice_uuid"],
                            total_incl_vat_sar=req["total_incl_vat_sar"],
                            corrects_invoice_uuid=corrects.invoice_uuid if corrects else None)
            row.history.append({"event": "SIGNED", "icv": icv})
            self.store.commit_signed(row)
        if row.invoice_flow == "REPORTING" and not self.gl.has(row.gl_key):
            self.gl.post(row.gl_key, row.total_incl_vat_sar, "POSTED_AT_SALE")  # B2C: never held by ZATCA
        return row.invoice_uuid

    # -- submission (state machine) -------------------------------------------------------------
    def submit(self, invoice_uuid: str) -> str:
        row = self.store.get(invoice_uuid)
        if row.state not in ("SIGNED",) and row.state not in RETRY_IDENTICAL:
            return row.state
        if row.state == "AUTH_HOLD":
            self.client.renew_csid(row.egs_id)
        row.state, row.attempts = "SUBMITTING", row.attempts + 1
        row.history.append({"event": "SUBMITTING", "attempt": row.attempts,
                            "bytes_sha256": hashlib.sha256(row.signed_xml).hexdigest()})
        self.store.put(row)  # persisted BEFORE the network call
        try:
            status = self.client.submit(egs_id=row.egs_id, request_id=row.request_id,
                                        invoice_uuid=row.invoice_uuid, invoice_flow=row.invoice_flow,
                                        xml_bytes=row.signed_xml)
        except TransportFailure:
            status = None
        # WorkerCrash propagates: the row stays SUBMITTING in the store, exactly as a dead process leaves it
        res = resolve_submission_attempt(status, row.invoice_flow)
        row.state = res["next_state"]
        row.history.append({"event": "RESPONSE", "attempt": row.attempts, "http_status": status,
                            "state": row.state})
        if res["gl_action"] == "POST_ONCE" and not self.gl.has(row.gl_key):
            self.gl.post(row.gl_key, row.total_incl_vat_sar, "POST_ONCE_CLEARED")
        self.store.put(row)
        return row.state

    def recover(self) -> list[str]:
        """Run on worker start: anything left SUBMITTING has an unknown outcome."""
        recovered = []
        for u in sorted(self.store.invoice_outbox):
            row = self.store.get(u)
            new = recover_after_restart(row.state)
            if new != row.state:
                row.history.append({"event": "RECOVERED_AFTER_RESTART", "from": row.state, "to": new})
                row.state = new
                self.store.put(row)
                recovered.append(u)
        return recovered


def correction_request(req: dict, attempt: int = 1) -> dict:
    """A rejected document is never edited: the fix is a NEW document (new UUID, new ICV)."""
    fixed = copy.deepcopy(req)
    line_net = sum((Decimal(ln["line_net_sar"]) for ln in fixed["lines"]), Decimal("0"))
    line_vat = sum((Decimal(ln["line_vat_sar"]) for ln in fixed["lines"]), Decimal("0"))
    fixed.update({"request_id": f"{req['request_id']}-C{attempt}",
                  "invoice_uuid": str(uuidlib.uuid5(CORRECTION_NS, f"{req['invoice_uuid']}/{attempt}")),
                  "total_excl_vat_sar": fmt_sar(line_net), "vat_total_sar": fmt_sar(line_vat),
                  "total_incl_vat_sar": fmt_sar(line_net + line_vat)})
    return fixed


@dataclass
class ChainRun:
    store: ChainStore
    gl: GlPostingSink
    client: object
    restarts: int = 0
    corrections: dict[str, str] = field(default_factory=dict)  # rejected uuid -> correction uuid


def process_requests(requests: list[dict], client, *, store: ChainStore | None = None,
                     gl: GlPostingSink | None = None, max_attempts: int = 6) -> ChainRun:
    """Drive requests through sign -> submit -> retry, restarting the worker whenever it crashes."""
    run = ChainRun(store or ChainStore(), gl or GlPostingSink(), client)
    worker = ZatcaWorker(run.store, client, run.gl)
    worker.recover()
    queue = list(requests)
    i = 0
    while i < len(queue):
        req = queue[i]
        corrects = run.store.get(req["_corrects"]) if req.get("_corrects") else None
        u = worker.enqueue(req, corrects=corrects)
        for _ in range(max_attempts):
            try:
                state = worker.submit(u)
            except WorkerCrash:
                run.restarts += 1
                worker = ZatcaWorker(run.store, client, run.gl)  # a fresh process
                worker.recover()
                state = run.store.get(u).state
            if state not in RETRY_IDENTICAL:
                break
        if state == "CONFIRMED_REJECTION":
            fix = correction_request({k: v for k, v in req.items() if k != "_corrects"})
            fix["_corrects"] = u
            run.corrections[u] = fix["invoice_uuid"]
            queue.insert(i + 1, fix)
        i += 1
    return run

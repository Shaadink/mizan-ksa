"""Phase 2: the 8 ZATCA chaos tests (spec Day 3 core four + Day 8 remaining four) plus planted-fault replay.

Invariants: I-01 (no ICV gaps from genesis), I-02 (PIH chain), I-03 (UNKNOWN_OUTCOME retries identical bytes,
accounting_postings == 1 per invoice_uuid).
"""

import json
import threading
from collections import Counter

import pytest

from mizan.clearance.chain_verifier import verify_chain
from mizan.clearance.engine import ChainStore, GlPostingSink, ZatcaWorker, process_requests
from mizan.clearance.mock_fatoora import MockFatoora, WorkerCrash
from mizan.clearance.tlv_qr_and_state_machine import GENESIS_PIH


@pytest.fixture(scope="module")
def requests(gen_dir):
    with (gen_dir / "zatca/invoice_requests.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture(scope="module")
def plan(gen_dir):
    return json.loads((gen_dir / "zatca/fatoora_fault_plan.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tape_run(requests, plan):
    e5 = [r for r in requests if r["egs_id"] == "EGS-05"][:130]
    client = MockFatoora(plan)
    return process_requests(e5, client), client, plan


def by_icv(run, egs):
    return {r.icv: r for r in run.store.invoice_outbox.values() if r.egs_id == egs}


def sent_hashes(client, request_id):
    return [e["bytes_sha256"] for e in client.log if e["request_id"] == request_id]


def assert_one_posting_per_sale(run):
    assert all(c == 1 for c in run.gl.calls.values()), Counter(run.gl.calls.values())
    sales = {r.gl_key for r in run.store.invoice_outbox.values()}
    for key in sales:
        assert run.gl.accounting_postings(key) <= 1


# ---------------------------------------------------------------- chaos 1-4 (core)

def test_chaos1_transport_timeout_retries_identical_bytes(tape_run):
    run, client, plan = tape_run
    rid = plan["tape"]["positions"]["102"]
    row = run.store.get(run.store.by_request_id[rid])
    assert row.icv == 102 and row.state == "REPORTED"
    hashes = sent_hashes(client, rid)
    assert len(hashes) == 3 and len(set(hashes)) == 1          # same signed bytes every time
    assert {e["invoice_uuid"] for e in client.log if e["request_id"] == rid} == {row.invoice_uuid}
    assert next(h["state"] for h in row.history if h["event"] == "RESPONSE") == "UNKNOWN_OUTCOME"


def test_chaos2_worker_killed_in_submitting_recovers_to_unknown_outcome(tape_run):
    run, _, plan = tape_run
    row = run.store.get(run.store.by_request_id[plan["tape"]["positions"]["102"]])
    events = [h["event"] for h in row.history]
    assert run.restarts == 1
    assert {"event": "RECOVERED_AFTER_RESTART", "from": "SUBMITTING", "to": "UNKNOWN_OUTCOME"} in row.history
    # SUBMITTING was persisted before each of the 3 calls
    assert events.count("SUBMITTING") == 3


def test_chaos3_rejected_document_retained_and_correction_chains_from_it(tape_run):
    run, _, _plan = tape_run
    chain = by_icv(run, "EGS-05")
    assert chain[103].state == "CONFIRMED_REJECTION"
    assert chain[104].corrects_invoice_uuid == chain[103].invoice_uuid
    assert chain[104].pih == chain[103].invoice_hash               # ICV 104 chains from 103's hash
    assert chain[104].invoice_uuid != chain[103].invoice_uuid and chain[104].state == "REPORTED"
    assert (("EGS-05", 103) in run.store.zatca_chain_journal)      # the rejected doc stays in the legal chain


def test_chaos4_chain_verifies_from_genesis(tape_run):
    run, _, _ = tape_run
    assert by_icv(run, "EGS-05")[1].pih == GENESIS_PIH
    assert sorted(by_icv(run, "EGS-05")) == list(range(1, 132))   # 130 requests + 1 correction, no gaps
    assert verify_chain(run.store.zatca_chain_journal.values()) == []
    assert_one_posting_per_sale(run)


def test_planted_icv_gap_tamper_detected(requests, plan):
    t = plan["tamper"][0]
    e3 = [r for r in requests if r["egs_id"] == t["egs_id"]][: t["icv"] + 5]
    run = process_requests(e3, MockFatoora(plan))
    journal = dict(run.store.zatca_chain_journal)
    assert verify_chain(journal.values()) == []
    del journal[(t["egs_id"], t["icv"])]                          # someone deletes page 500
    v = verify_chain(journal.values())
    assert {(x["icv"], x["violation_type"]) for x in v} == {(t["icv"] + 1, "ICV_GAP"),
                                                             (t["icv"] + 1, "PIH_MISMATCH")}


def test_tampered_xml_detected(tape_run):
    run, _, _ = tape_run
    journal = {k: dict(v) for k, v in run.store.zatca_chain_journal.items()}
    row = journal[("EGS-05", 50)]
    row["signed_xml"] = row["signed_xml"].replace(b"<cbc:TaxAmount", b"<cbc:TaxAmount ", 1)  # harmless
    assert verify_chain(journal.values()) == []
    target = row["signed_xml"].split(b'currencyID="SAR">', 1)
    row["signed_xml"] = target[0] + b'currencyID="SAR">9' + target[1]                     # amount edit
    assert {x["violation_type"] for x in verify_chain(journal.values())} == {"HASH_MISMATCH"}


# ---------------------------------------------------------------- chaos 5-8 (remaining)

@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504, 302])
def test_chaos5_non_definitive_statuses_never_mint_new_uuid_or_icv(requests, status):
    reqs = [r for r in requests if r["egs_id"] == "EGS-05"][:5]
    client = MockFatoora()
    client.script(reqs[2]["request_id"], [f"HTTP_{status}", f"HTTP_{status}", "HTTP_200"])
    run = process_requests(reqs, client)
    row = run.store.get(run.store.by_request_id[reqs[2]["request_id"]])
    assert row.icv == 3 and row.state == "REPORTED" and row.attempts == 3
    assert len(set(sent_hashes(client, reqs[2]["request_id"]))) == 1
    assert sorted(by_icv(run, "EGS-05")) == [1, 2, 3, 4, 5]
    assert_one_posting_per_sale(run)


@pytest.mark.parametrize("status", [401, 403])
def test_chaos6_auth_hold_renews_csid_and_resends_identical_bytes(requests, status):
    b2b = [r for r in requests if r["invoice_flow"] == "CLEARANCE" and r["egs_id"] == "EGS-01"][:3]
    client = MockFatoora()
    client.script(b2b[1]["request_id"], [f"HTTP_{status}", "HTTP_200"])
    run = process_requests(b2b, client)
    row = run.store.get(run.store.by_request_id[b2b[1]["request_id"]])
    assert [h["state"] for h in row.history if h["event"] == "RESPONSE"] == ["AUTH_HOLD", "CLEARED"]
    assert client.csid_generation["EGS-01"] == 2
    assert len(set(sent_hashes(client, b2b[1]["request_id"]))) == 1
    assert run.gl.accounting_postings(row.gl_key) == 1


def test_chaos7_b2b_held_until_cleared_b2c_posted_despite_timeout(requests):
    b2b = next(r for r in requests if r["invoice_flow"] == "CLEARANCE")
    b2c = next(r for r in requests if r["invoice_flow"] == "REPORTING" and r["egs_id"] == b2b["egs_id"])
    store, gl, client = ChainStore(), GlPostingSink(), MockFatoora()
    client.script(b2b["request_id"], ["TRANSPORT_TIMEOUT", "HTTP_503", "HTTP_200"])
    client.script(b2c["request_id"], ["TRANSPORT_TIMEOUT", "HTTP_200"])
    w = ZatcaWorker(store, client, gl)
    u_b2b, u_b2c = w.enqueue(b2b), w.enqueue(b2c)
    assert gl.accounting_postings(u_b2c) == 1        # B2C: posted at sale, before ZATCA answers
    assert gl.accounting_postings(u_b2b) == 0        # B2B: held
    assert w.submit(u_b2c) == "UNKNOWN_OUTCOME" and gl.accounting_postings(u_b2c) == 1
    assert w.submit(u_b2b) == "UNKNOWN_OUTCOME" and gl.accounting_postings(u_b2b) == 0
    assert w.submit(u_b2b) == "UNKNOWN_OUTCOME" and gl.accounting_postings(u_b2b) == 0
    assert w.submit(u_b2b) == "CLEARED" and gl.accounting_postings(u_b2b) == 1
    assert w.submit(u_b2c) == "REPORTED"
    assert w.submit(u_b2b) == "CLEARED"              # resubmitting a final state is a no-op
    assert gl.calls[u_b2b] == 1 and gl.calls[u_b2c] == 1


def test_chaos8_concurrent_lanes_single_writer_no_gaps(requests):
    reqs = [r for r in requests if r["egs_id"] == "EGS-02"][:240]
    store, gl, client = ChainStore(), GlPostingSink(), MockFatoora()
    lanes = [reqs[i::8] for i in range(8)]
    errors = []

    def lane(batch):
        w = ZatcaWorker(store, client, gl)
        try:
            for r in batch:
                w.submit(w.enqueue(r))
                w.enqueue(r)                              # POS re-sends the same request: idempotent
        except Exception as e:  # pragma: no cover - surfaced by the assert below
            errors.append(e)

    threads = [threading.Thread(target=lane, args=(b,)) for b in lanes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(r.icv for r in store.invoice_outbox.values()) == list(range(1, 241))
    assert verify_chain(store.zatca_chain_journal.values()) == []
    assert all(c == 1 for c in gl.calls.values()) and len(gl.postings) == 240


# ---------------------------------------------------------------- restart semantics

def test_crash_leaves_submitting_and_new_worker_recovers(requests):
    r = next(x for x in requests if x["egs_id"] == "EGS-04")
    store, gl, client = ChainStore(), GlPostingSink(), MockFatoora()
    client.script(r["request_id"], ["WORKER_CRASH_IN_SUBMITTING", "HTTP_200"])
    w = ZatcaWorker(store, client, gl)
    u = w.enqueue(r)
    with pytest.raises(WorkerCrash):
        w.submit(u)
    assert store.get(u).state == "SUBMITTING"         # persisted before the call
    w2 = ZatcaWorker(store, client, gl)
    assert w2.recover() == [u] and store.get(u).state == "UNKNOWN_OUTCOME"
    expected = "CLEARED" if r["invoice_flow"] == "CLEARANCE" else "REPORTED"
    assert w2.submit(u) == expected
    assert len(set(sent_hashes(client, r["request_id"]))) == 1

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

# 303 is in this list on purpose. It is meaningful ONLY from the clearance endpoint; arriving on a
# simplified (B2C) document it means nothing ZATCA defines, so it must stay UNKNOWN_OUTCOME rather than
# be read as "go to reporting" by a document that is already there.
@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504, 302, 303])
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


# ---------------------------------------------------------------- price corrected after signing (row 29)


def _repriced(req, factor="0.80"):
    """The same sale with one line's price changed, as an upstream price correction would leave it."""
    from decimal import Decimal
    out = json.loads(json.dumps(req))
    ln = out["lines"][0]
    net = (Decimal(ln["line_net_sar"]) * Decimal(factor)).quantize(Decimal("0.01"))
    ln["line_net_sar"] = f"{net:.2f}"
    ln["unit_price_sar"] = f"{(net / Decimal(ln['qty'])).quantize(Decimal('0.01')):.2f}"
    ln["line_vat_sar"] = f"{(net * Decimal('0.15')).quantize(Decimal('0.01')):.2f}"
    # A real upstream correction restates the header totals too, so the fixture does as well. Leaving the
    # header on the old figure would have made this test pass against a product that never recomputed.
    tn = sum((Decimal(x["line_net_sar"]) for x in out["lines"]), Decimal("0"))
    tv = sum((Decimal(x["line_vat_sar"]) for x in out["lines"]), Decimal("0"))
    out.update({"total_excl_vat_sar": f"{tn:.2f}", "vat_total_sar": f"{tv:.2f}",
                "total_incl_vat_sar": f"{tn + tv:.2f}"})
    return out


def test_price_correction_nets_the_chain_to_the_corrected_amount(requests):
    """The whole point of HONESTY row 29. Correcting a price moved Silver, Gold and the bank reconciliation
    and left the tax ledger on the old figure. The chain must now arrive at the corrected total -- by
    issuing documents, never by re-pricing a signed one."""
    from decimal import Decimal

    from mizan.clearance.engine import price_correction_documents
    signed = next(r for r in requests if r["document_type"] == "INVOICE")
    corrected = _repriced(signed)
    pair = price_correction_documents(signed, corrected)

    assert [d["document_type"] for d in pair] == ["CREDIT_NOTE", "INVOICE"]
    signed_total = Decimal(signed["total_incl_vat_sar"])
    cancel, replacement = (Decimal(d["total_incl_vat_sar"]) for d in pair)
    assert cancel == signed_total, "the credit note must reverse the original in full"
    # original - cancellation + replacement == the corrected amount, exactly, in halalas.
    assert signed_total - cancel + replacement == Decimal(corrected["total_incl_vat_sar"])
    assert replacement < signed_total


def test_price_correction_never_touches_the_signed_document(requests):
    """Re-signing a document ZATCA already holds is the one thing a tax chain must not do."""
    from mizan.clearance.engine import price_correction_documents
    signed = next(r for r in requests if r["document_type"] == "INVOICE")
    before = json.dumps(signed, sort_keys=True)
    pair = price_correction_documents(signed, _repriced(signed))
    assert json.dumps(signed, sort_keys=True) == before, "the signed request was mutated in place"
    for d in pair:
        assert d["invoice_uuid"] != signed["invoice_uuid"]
        assert d["request_id"] != signed["request_id"]
        assert d["billing_reference_uuid"] == signed["invoice_uuid"], (
            "both documents must name the invoice they correct, or an auditor cannot follow it")


def test_price_correction_is_deterministic(requests):
    """CLAUDE.md: a rerun must be byte-identical. Non-deterministic UUIDs here would mint a second pair of
    ICVs on every run and the chain would grow without anything changing."""
    from mizan.clearance.engine import price_correction_documents
    signed = next(r for r in requests if r["document_type"] == "INVOICE")
    corrected = _repriced(signed)
    a = price_correction_documents(signed, corrected)
    b = price_correction_documents(signed, corrected)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_an_unchanged_price_issues_nothing(requests):
    """The detector runs over every document on every run. If it emitted a pair when nothing had changed it
    would add two ICVs per invoice per night, for ever."""
    from mizan.clearance.engine import price_correction_documents
    signed = next(r for r in requests if r["document_type"] == "INVOICE")
    assert price_correction_documents(signed, json.loads(json.dumps(signed))) == []


def test_a_second_correction_cancels_the_replacement_not_the_original(requests):
    """Correcting the same invoice twice. The second credit note must reverse the FIRST REPLACEMENT.

    Reversing the original a second time would subtract it twice and the chain would net to an amount
    nobody ever invoiced. `cancels_uuid` is what makes the difference, and this is the only test that would
    notice if it stopped being passed.
    """
    from decimal import Decimal

    from mizan.clearance.engine import price_correction_documents
    signed = next(r for r in requests if r["document_type"] == "INVOICE")
    first_pair = price_correction_documents(signed, _repriced(signed, "0.80"))
    replacement = first_pair[1]

    second_pair = price_correction_documents(replacement, _repriced(signed, "0.50"), attempt=2,
                                             cancels_uuid=replacement["invoice_uuid"])
    cancel2, replacement2 = second_pair
    assert cancel2["billing_reference_uuid"] == replacement["invoice_uuid"], (
        "the second cancellation names the original instead of the document it actually reverses")
    assert Decimal(cancel2["total_incl_vat_sar"]) == Decimal(replacement["total_incl_vat_sar"])

    chain = (Decimal(signed["total_incl_vat_sar"])
             - Decimal(first_pair[0]["total_incl_vat_sar"]) + Decimal(replacement["total_incl_vat_sar"])
             - Decimal(cancel2["total_incl_vat_sar"]) + Decimal(replacement2["total_incl_vat_sar"]))
    assert chain == Decimal(replacement2["total_incl_vat_sar"]), (
        f"after two corrections the chain nets to {chain}, not the latest stated amount")
    assert len({d["invoice_uuid"] for d in (*first_pair, *second_pair)}) == 4, "a UUID was reused"


def test_a_changed_credit_note_raises_instead_of_guessing(requests):
    """Cancelling a credit note needs a debit note (ZATCA 383), which this project does not model. Failing
    closed is the only honest option: a half-handled tax correction is worse than a refusal."""
    from mizan.clearance.engine import price_correction_documents
    cn = next(r for r in requests if r["document_type"] == "CREDIT_NOTE")
    with pytest.raises(ValueError, match="debit note"):
        price_correction_documents(cn, _repriced(cn))


def test_the_correction_pair_signs_into_the_chain_with_its_own_icvs(requests):
    """End to end: the pair goes through the real engine, gets its own ICVs, and the chain still verifies
    from genesis with no gaps -- which is what makes this a correction rather than a rewrite."""
    from decimal import Decimal

    from mizan.clearance.engine import price_correction_documents
    base = [r for r in requests if r["egs_id"] == "EGS-01" and r["document_type"] == "INVOICE"][:3]
    signed = base[1]
    pair = price_correction_documents(signed, _repriced(signed))

    client = MockFatoora()
    run = process_requests([*base, *pair], client)
    assert sorted(by_icv(run, "EGS-01")) == [1, 2, 3, 4, 5], "the pair must extend the chain, not replace it"
    assert verify_chain(run.store.zatca_chain_journal.values()) == []

    rows = {r.request_id: r for r in run.store.invoice_outbox.values()}
    original = rows[signed["request_id"]]
    cancel = rows[pair[0]["request_id"]]
    replacement = rows[pair[1]["request_id"]]
    assert original.state in ("CLEARED", "REPORTED")
    net = (Decimal(original.total_incl_vat_sar) - Decimal(cancel.total_incl_vat_sar)
           + Decimal(replacement.total_incl_vat_sar))
    assert net == Decimal(pair[1]["total_incl_vat_sar"])
    assert_one_posting_per_sale(run)


# ---------------------------------------------------------------- clearance switched off (HTTP 303)


def test_303_resubmits_the_identical_document_to_reporting_instead_of_looping(requests):
    """ZATCA's Detailed Technical Guideline v2: when clearance is deactivated, a standard document POSTed
    to the clearance API is answered 303 and must go to the reporting API, where it is Reported.

    Until 2026-11-21 this project treated 303 as UNKNOWN_OUTCOME, which is a live defect rather than a
    conservative default: the retry goes back to the clearance endpoint, which is still deactivated, which
    answers 303 again. It never resolves. And because ZATCA switches clearance off tenant-wide, it would
    happen to every standard invoice at once.
    """
    b2b = [r for r in requests if r["invoice_flow"] == "CLEARANCE" and r["egs_id"] == "EGS-01"][:3]
    client = MockFatoora()
    client.deactivate_clearance()
    run = process_requests(b2b, client)

    rows = [run.store.get(run.store.by_request_id[r["request_id"]]) for r in b2b]
    assert [r.state for r in rows] == ["REPORTED"] * 3, (
        "a standard document must end REPORTED when clearance is off, not loop on UNKNOWN_OUTCOME")
    assert all(r.attempts == 1 for r in rows), "the redirect is followed inside one attempt, not retried"
    # The document is unchanged in every way that matters to the chain.
    assert [r.invoice_flow for r in rows] == ["CLEARANCE"] * 3, (
        "the document is still a standard B2B invoice; only the endpoint that accepted it changed")
    assert sorted(by_icv(run, "EGS-01")) == [1, 2, 3]
    for r in b2b:
        assert len(set(sent_hashes(client, r["request_id"]))) == 1, "redirect resent different bytes"
    assert_one_posting_per_sale(run)


def test_303_posts_the_b2b_ledger_entry_once_reporting_accepts_it(requests):
    """The hold exists because ZATCA might reject a B2B document. Once ZATCA has ACCEPTED it -- by whichever
    endpoint it told us to use -- the condition the hold was waiting for is met. Holding anyway would strand
    every B2B sale for as long as ZATCA keeps clearance off, which is a decision ZATCA makes, not us."""
    b2b = next(r for r in requests if r["invoice_flow"] == "CLEARANCE")
    store, gl, client = ChainStore(), GlPostingSink(), MockFatoora()
    client.deactivate_clearance()
    w = ZatcaWorker(store, client, gl)
    uuid = w.enqueue(b2b)
    assert gl.accounting_postings(uuid) == 0, "B2B must still be held at sale"
    assert w.submit(uuid) == "REPORTED"
    assert gl.accounting_postings(uuid) == 1
    assert w.submit(uuid) == "REPORTED" and gl.calls[uuid] == 1, "a settled document re-posts nothing"


def test_303_is_recorded_so_an_auditor_can_see_why_a_b2b_doc_was_reported(requests):
    """A standard invoice in REPORTED state is otherwise inexplicable. The reason has to be in the history,
    because this is a tax record and 'why is this one different' is the first question anyone asks."""
    b2b = next(r for r in requests if r["invoice_flow"] == "CLEARANCE")
    store, gl, client = ChainStore(), GlPostingSink(), MockFatoora()
    client.deactivate_clearance()
    w = ZatcaWorker(store, client, gl)
    row = store.get(w.enqueue(b2b))
    w.submit(row.invoice_uuid)
    row = store.get(row.invoice_uuid)
    redirect = [h for h in row.history if h["event"] == "CLEARANCE_DEACTIVATED"]
    assert len(redirect) == 1 and redirect[0]["http_status"] == 303
    assert redirect[0]["resubmitted_to"] == "REPORTING"
    response = [h for h in row.history if h["event"] == "RESPONSE"][-1]
    assert response["endpoint"] == "REPORTING" and response["state"] == "REPORTED"


def test_a_b2c_document_is_untouched_when_clearance_is_deactivated(requests):
    """Simplified invoices never went to the clearance endpoint, so switching it off must change nothing
    about them -- including that they still post at sale."""
    b2c = next(r for r in requests if r["invoice_flow"] == "REPORTING")
    store, gl, client = ChainStore(), GlPostingSink(), MockFatoora()
    client.deactivate_clearance()
    w = ZatcaWorker(store, client, gl)
    uuid = w.enqueue(b2c)
    assert gl.accounting_postings(uuid) == 1
    assert w.submit(uuid) == "REPORTED"
    row = store.get(uuid)
    assert not [h for h in row.history if h["event"] == "CLEARANCE_DEACTIVATED"]


def test_303_does_not_consume_a_planted_fault(requests):
    """A guard on the fixture, not the product. If deactivation ate a scripted outcome, turning clearance
    off would shift every planted fault onto a different attempt and quietly weaken the other chaos tests."""
    b2b = [r for r in requests if r["invoice_flow"] == "CLEARANCE" and r["egs_id"] == "EGS-01"][:1]
    client = MockFatoora()
    client.deactivate_clearance()
    client.script(b2b[0]["request_id"], ["HTTP_400"])
    run = process_requests(b2b, client)
    row = run.store.get(run.store.by_request_id[b2b[0]["request_id"]])
    assert row.state == "CONFIRMED_REJECTION", (
        "the scripted 400 must still be the answer the REPORTING endpoint gives, not be eaten by the 303")


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


def test_chain_head_guard_refuses_a_stale_write_rather_than_forking(requests):
    """The 8-lane test above proves the happy path. This proves the GUARD, which is the part that matters.

    Those 8 lanes are threads in one process sharing one ChainStore, so `threading.Lock` is sufficient and the
    test can never exercise what happens when the lock does NOT hold -- which is exactly the case a second
    worker process, or a retried Fabric job, would create. Two writers both read `last_icv = n`, both mint
    `n+1`, and the chain forks: two different documents claiming the same ICV, which is unrecoverable because
    a submitted ICV cannot be withdrawn.

    `ChainStore.commit_signed` guards against this by re-reading the head and refusing to write if it moved
    (compare-and-set, not read-then-write). Nothing tested that the refusal actually fires, so here it is:
    simulate the lost race by advancing the head out of band between the mint and the commit.
    """
    req = next(r for r in requests if r["egs_id"] == "EGS-03")
    store, gl, client = ChainStore(), GlPostingSink(), MockFatoora()
    worker = ZatcaWorker(store, client, gl)

    uuid_1 = worker.enqueue(req)
    row = store.get(uuid_1)
    assert row.icv == 1 and row.pih == GENESIS_PIH

    # The competing writer wins the race: the head is now at ICV 1 with a different document's hash.
    store.egs_chain_state["EGS-03"] = {"egs_id": "EGS-03", "last_icv": 1,
                                       "last_invoice_hash": "c29tZS1vdGhlci1kb2N1bWVudA=="}

    # Our row was minted against the head as it was. Committing it now would fork the chain.
    with pytest.raises(RuntimeError, match="single-writer violated"):
        store.commit_signed(row)

    # The loser wrote nothing: the head is untouched and the journal holds one document at ICV 1.
    assert store.egs_chain_state["EGS-03"]["last_icv"] == 1
    assert [k for k in store.zatca_chain_journal if k[0] == "EGS-03"] == [("EGS-03", 1)]


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


# ---------------------------------------------------------------- credit notes + replay (GL idempotency)

def test_credit_note_posts_under_its_own_uuid_and_replay_posts_nothing(requests, plan):
    cns = [r for r in requests if r["document_type"] == "CREDIT_NOTE"][:25]
    originals = {r["billing_reference_uuid"] for r in cns}
    subset = sorted([r for r in requests if r["invoice_uuid"] in originals] + cns, key=lambda r: r["issue_ts_utc"])
    client = MockFatoora(plan)
    run = process_requests(subset, client)
    for cn in cns:
        row = run.store.get(cn["invoice_uuid"])
        assert row.document_type == "CREDIT_NOTE"
        assert row.gl_key == cn["invoice_uuid"] != cn["billing_reference_uuid"]
        assert run.gl.accounting_postings(cn["invoice_uuid"]) == 1
        assert run.gl.postings[cn["invoice_uuid"]]["amount_sar"] == cn["total_incl_vat_sar"]   # positive amount
        assert run.gl.accounting_postings(cn["billing_reference_uuid"]) == 1                   # sale posted apart
    assert_one_posting_per_sale(run)
    calls, http = dict(run.gl.calls), len(client.log)
    process_requests(subset, client, store=run.store, gl=run.gl)                                # full replay
    assert run.gl.calls == calls and len(client.log) == http                                    # nothing posted/sent

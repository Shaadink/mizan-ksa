"""HONESTY row 18: the ZATCA chain head in a transactional store, not a Python dict.

The existing guard is `test_chain_head_guard_refuses_a_stale_write_rather_than_forking` in
test_zatca_chaos.py. It proves the compare-and-set LOGIC is right, and it can only ever prove that much,
because its eight lanes are eight threads sharing one `ChainStore` -- one dict, one lock, one process. The
failure everyone actually worries about is two worker PROCESSES, or one worker and a retried Fabric job,
which share no dict at all: both read `last_icv = n`, both mint `n + 1`, and the chain forks into two
documents claiming the same ICV. A submitted ICV cannot be withdrawn, so that fork is unrecoverable.

These tests exercise the same compare-and-set against a real Delta transaction log, which IS shared across
processes. They still drive it from threads -- starting two JVMs per assertion would add minutes to the
suite for no extra coverage of the thing under test, because what is being tested is whether the storage
layer serialises conflicting head advances, and Delta does that identically whoever asks.

What this does not claim: that the pipeline runs multi-process today. `run_zatca` is single-process and
keeps the in-memory head, where a Delta round trip per signature would cost real time for no safety. This
is the mechanism and the proof that a multi-worker deployment needs, built rather than promised.
"""

from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("delta")
pytestmark = pytest.mark.spark

from mizan.clearance.tlv_qr_and_state_machine import GENESIS_PIH  # noqa: E402

EGS = "EGS-01"


def _hash(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode("ascii")


@pytest.fixture
def head(spark, tmp_path):
    from mizan.spark.chain_head import DeltaChainHead
    from mizan.spark.lake import Lake
    from mizan.spark.session import TableLocator
    return DeltaChainHead(Lake(spark, TableLocator("local", tmp_path / "lake")))


def test_a_new_chain_starts_at_genesis(head):
    assert head.read(EGS) == (0, GENESIS_PIH)


def test_the_first_document_takes_icv_1(head):
    assert head.compare_and_set(EGS, 0, 1, _hash("doc1")) is True
    assert head.read(EGS) == (1, _hash("doc1"))


def test_a_stale_writer_is_refused_rather_than_allowed_to_fork(head):
    """The lost race, made deterministic. A worker reads the head, something else advances it, and the
    worker then tries to commit the ICV it had already minted. It must be told no."""
    head.compare_and_set(EGS, 0, 1, _hash("doc1"))
    seen_icv, _ = head.read(EGS)                       # worker A reads: 1

    assert head.compare_and_set(EGS, 1, 2, _hash("doc2")) is True      # worker B gets there first

    # Worker A now tries to commit ICV 2 as well. This is the fork, and it must not happen.
    assert head.compare_and_set(EGS, seen_icv, 2, _hash("doc2-from-A")) is False
    assert head.read(EGS) == (2, _hash("doc2")), "the loser overwrote the winner's head"


def test_only_one_of_two_racing_writers_can_take_an_icv(head):
    """Both threads read the same head and both try to advance it. Exactly one may succeed."""
    head.compare_and_set(EGS, 0, 1, _hash("doc1"))
    expected, _ = head.read(EGS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda who: head.compare_and_set(EGS, expected, expected + 1, _hash(f"doc2-{who}")),
            ("A", "B")))

    assert results.count(True) == 1, f"two writers both believed they took ICV 2: {results}"
    icv, final_hash = head.read(EGS)
    assert icv == 2
    assert final_hash in (_hash("doc2-A"), _hash("doc2-B"))


def test_two_writers_cannot_both_start_the_same_chain(head):
    """The empty-table case has its own path (MERGE, not UPDATE), so it needs its own race test: an EGS
    that has never signed anything must still end with exactly one document at ICV 1."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda who: head.compare_and_set(EGS, 0, 1, _hash(f"first-{who}")),
                                ("A", "B")))
    assert results.count(True) == 1, f"both writers started the chain: {results}"
    assert head.read(EGS)[0] == 1

    from mizan.spark.chain_head import TABLE
    rows = head.lake.read(*TABLE).filter(f"egs_id = '{EGS}'").count()
    assert rows == 1, f"the chain head table holds {rows} rows for one EGS"


def test_a_head_can_only_advance_by_one(head):
    """Skipping an ICV is a gap, and a gap in a tax chain has to be explained to ZATCA. Refuse it at the
    store rather than discover it later in verify_chain."""
    head.compare_and_set(EGS, 0, 1, _hash("doc1"))
    with pytest.raises(ValueError, match="exactly one ICV"):
        head.compare_and_set(EGS, 1, 5, _hash("doc5"))


def test_the_engine_signs_a_gapless_chain_through_the_delta_head(head, gen_dir):
    """End to end: the real engine, with its head in Delta instead of in memory, still produces a chain
    that verifies from genesis. If the wiring were wrong this is where it would show."""
    import json

    from mizan.clearance.chain_verifier import verify_chain
    from mizan.clearance.engine import ChainStore, process_requests
    from mizan.clearance.mock_fatoora import MockFatoora

    with (gen_dir / "zatca/invoice_requests.jsonl").open(encoding="utf-8") as f:
        reqs = [json.loads(line) for line in f]
    mine = [r for r in reqs if r["egs_id"] == EGS][:6]

    store = ChainStore(head_store=head)
    run = process_requests(mine, MockFatoora(), store=store)

    icvs = sorted(r.icv for r in run.store.invoice_outbox.values())
    assert icvs == [1, 2, 3, 4, 5, 6], f"the Delta-backed head produced {icvs}"
    assert verify_chain(run.store.zatca_chain_journal.values()) == []
    assert head.read(EGS)[0] == 6, "the durable head did not keep up with the chain"

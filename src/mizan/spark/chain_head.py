"""The ZATCA chain head in a transactional store, so two worker PROCESSES cannot fork a chain.

HONESTY row 18, and the distinction it turns on. `ChainStore.commit_signed` already does a compare-and-set
rather than a read-then-write: it re-reads the head and refuses the write if it moved. That logic is right,
and until now it ran over a Python dict guarded by a `threading.Lock`. A dict and a lock are not shared
between processes. Two workers -- or one worker and a retried Fabric job -- would each read `last_icv = n`,
each mint `n + 1`, and the chain would fork into two documents claiming the same ICV.

**A submitted ICV cannot be withdrawn.** That is what makes a fork unrecoverable and a gap merely bad: a gap
is visible to `verify_chain` from genesis and can be explained, whereas two live documents at ICV 500 cannot
be reconciled by anybody, including ZATCA.

This moves the compare-and-set onto `ctl.egs_chain_state`, a Delta table. Delta serialises commits through
its transaction log, so of two writers racing to advance the same EGS exactly one finds `last_icv = n` still
true when its commit lands; the other updates nothing.

**How the winner is determined, and why it is not a row count.** The obvious check -- ask Delta how many
rows the UPDATE touched -- means reading the table history *after* the write, by which time another process
may have committed again, so the number read is not necessarily the number written. Instead the writer
reads the row back and checks the head now holds *its own* invoice hash. Two racing writers are signing two
different documents, so their hashes differ; the one whose hash is in the table is the one whose update
landed. The only way two writers can produce the same hash is by signing byte-identical documents at the
same ICV, which is the idempotent re-send that `by_request_id` short-circuits long before this point -- and
if it did reach here, both writers agreeing is the correct outcome rather than a race at all.

Not wired in by default. `run_zatca` is single-process, so the in-memory head is accurate there and taking a
Delta round trip per signature would cost real time for no safety. This exists so that a multi-worker
deployment has the mechanism and the test, rather than a note saying it would need one.
"""

from __future__ import annotations

from mizan.clearance.tlv_qr_and_state_machine import GENESIS_PIH
from mizan.spark.lake import Lake

TABLE = ("ctl", "egs_chain_state")


class DeltaChainHead:
    """Chain head over ctl.egs_chain_state. Satisfies the two-method contract ChainStore expects."""

    def __init__(self, lake: Lake, *, create: bool = True):
        self.lake = lake
        if create:
            self.ensure_table()

    def ensure_table(self) -> None:
        """Create the chain-head table empty, up front, if it does not exist.

        Not an optimisation -- a correctness fix, and Delta's own advice in the error it raises without it:
        "This happens when multiple writers are writing to an empty directory. Creating the table ahead of
        time will avoid this conflict." Creating it lazily inside `compare_and_set` meant two writers
        starting the same chain both tried to CREATE it, and the loser got a `ProtocolChangedException`
        thrown at it instead of a clean `False`. Found by the race test, not by reading the code.
        """
        if self.lake.exists(*TABLE):
            return
        from pyspark.sql import functions as F
        empty = self.lake.spark.createDataFrame(
            [], "egs_id string, last_icv int, last_invoice_hash string").withColumn(
            "updated_at", F.current_timestamp())
        self.lake.write(empty, *TABLE, "append")

    # -- reads ---------------------------------------------------------------------------------
    def read(self, egs_id: str) -> tuple[int, str]:
        row = self._row(egs_id)
        if row is None:
            return 0, GENESIS_PIH
        return int(row["last_icv"]), str(row["last_invoice_hash"])

    def _row(self, egs_id: str) -> dict | None:
        from pyspark.sql import functions as F
        if not self.lake.exists(*TABLE):
            return None
        rows = self.lake.read(*TABLE).filter(F.col("egs_id") == egs_id).collect()
        return rows[0].asDict() if rows else None

    # -- the compare-and-set -------------------------------------------------------------------
    def compare_and_set(self, egs_id: str, expected_icv: int, new_icv: int, new_hash: str) -> bool:
        """Advance the head only if it is still where the caller last saw it. False means the race was lost.

        The caller must treat False as "do not submit this document": its ICV now belongs to somebody else.
        """
        if new_icv != expected_icv + 1:
            raise ValueError(f"{egs_id}: a chain head advances by exactly one ICV "
                             f"(expected {expected_icv} -> {expected_icv + 1}, got {new_icv})")
        from delta.exceptions import (
            ConcurrentAppendException,
            ConcurrentDeleteDeleteException,
            ConcurrentDeleteReadException,
            MetadataChangedException,
            ProtocolChangedException,
        )
        from delta.tables import DeltaTable
        from pyspark.sql import functions as F

        # Losing a race is a NORMAL outcome here, not an error, so Delta's conflict exceptions are caught
        # and answered by the read-back below rather than propagated. The read-back is authoritative either
        # way: if the write landed despite the conflict, the head carries our hash and we won.
        conflicts = (ConcurrentAppendException, ConcurrentDeleteReadException,
                     ConcurrentDeleteDeleteException, MetadataChangedException, ProtocolChangedException)

        self.ensure_table()
        table = DeltaTable.forPath(self.lake.spark, self.lake.path(*TABLE))
        if expected_icv == 0:
            # A chain nobody has written yet. MERGE rather than INSERT so that two writers starting the same
            # EGS at once cannot both add a row: the second one matches and does nothing.
            source = self.lake.spark.createDataFrame(
                [(egs_id, int(new_icv), str(new_hash))], "egs_id string, last_icv int, last_invoice_hash string")
            try:
                (table.alias("t").merge(source.alias("s"), "t.egs_id = s.egs_id")
                     .whenNotMatchedInsert(values={"egs_id": "s.egs_id", "last_icv": "s.last_icv",
                                                   "last_invoice_hash": "s.last_invoice_hash",
                                                   "updated_at": F.current_timestamp()})
                     .execute())
            except conflicts:
                pass
        else:
            try:
                table.update(
                    condition=(F.col("egs_id") == egs_id) & (F.col("last_icv") == int(expected_icv)),
                    set={"last_icv": F.lit(int(new_icv)), "last_invoice_hash": F.lit(str(new_hash)),
                         "updated_at": F.current_timestamp()})
            except conflicts:
                pass
        # Read back: the head is ours only if it carries OUR hash. See the module docstring.
        return self.read(egs_id) == (new_icv, new_hash)

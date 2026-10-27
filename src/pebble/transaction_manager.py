"""V3 Person A (from V4) — begin / commit / abort; allocate txn ids + timestamps.

PREREQUISITES:
  - pebble.transaction.Transaction, TransactionState
  - Optional: pebble.wal.LogManager (append COMMIT/ABORT records on commit/abort)
  - Optional: pebble.undo_log (rollback write_set on abort)

USED BY:
  - database.py: BEGIN / COMMIT / ROLLBACK SQL (Person A patch)
  - Insert/Delete/Update executors (receive current Transaction)
  - tests/test_transaction.py

PSEUDOCODE
==========
class TransactionManager:
    def __init__(self, wal: LogManager | None = None):
        self._next_txn_id = 1
        self._next_ts = 1
        self._active: dict[int, Transaction] = {}
        self._wal = wal

    def begin(self, isolation=SNAPSHOT) -> Transaction:
        # txn_id = next_id++; read_ts = next_ts (or last_commit_ts)
        # optionally WAL BEGIN; store in _active; return txn

    def commit(self, txn: Transaction) -> None:
        # validate write_set if optimistic; commit_ts = next_ts++
        # WAL COMMIT + flush; txn.state = COMMITTED; drop from _active

    def abort(self, txn: Transaction) -> None:
        # walk undo / write_set and revert; WAL ABORT; state = ABORTED

DONE WHEN:
  - begin → commit path assigns increasing commit_ts
  - abort marks ABORTED and removes from active set
  - Double commit / commit-after-abort raises
"""

from __future__ import annotations

"""Transaction ID and timestamp management."""

from pebble.log_record import LogRecordType
from pebble.transaction import (
    IsolationLevel,
    Transaction,
    TransactionState,
)


class TransactionManager:
    """Allocate and finish transactions in a single-threaded database."""

    def __init__(self, wal: object | None = None) -> None:
        self._wal = wal
        self._next_txn_id = 1
        self._next_ts = 1
        self._active: dict[int, Transaction] = {}

    def begin(
        self,
        isolation: IsolationLevel = IsolationLevel.SNAPSHOT,
    ) -> Transaction:
        txn_id = self._next_txn_id
        self._next_txn_id += 1

        # Snapshot reads see all transactions committed before this begin.
        txn = Transaction(
            txn_id=txn_id,
            read_ts=self._next_ts - 1,
            isolation=isolation,
        )

        if self._wal is not None:
            self._wal.append(txn_id, LogRecordType.BEGIN)

        self._active[txn_id] = txn
        return txn

    def commit(self, txn: Transaction) -> None:
        self._require_active(txn)

        commit_ts = self._next_ts
        if self._wal is not None:
            commit_lsn = self._wal.append(txn.txn_id, LogRecordType.COMMIT)
            self._wal.flush(commit_lsn)

        txn.commit_ts = commit_ts
        txn.state = TransactionState.COMMITTED
        self._next_ts += 1
        del self._active[txn.txn_id]

    def abort(self, txn: Transaction) -> None:
        self._require_active(txn)

        if self._wal is not None:
            abort_lsn = self._wal.append(txn.txn_id, LogRecordType.ABORT)
            self._wal.flush(abort_lsn)

        txn.state = TransactionState.ABORTED
        del self._active[txn.txn_id]

    def get(self, txn_id: int) -> Transaction | None:
        """Return the active transaction with this ID, if any."""
        return self._active.get(txn_id)

    def _require_active(self, txn: Transaction) -> None:
        active_txn = self._active.get(txn.txn_id)
        if (
            active_txn is not txn
            or txn.state is not TransactionState.ACTIVE
        ):
            raise ValueError(f"transaction {txn.txn_id} is not active")

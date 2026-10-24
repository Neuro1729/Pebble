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

from pebble.transaction import IsolationLevel, Transaction


class TransactionManager:
    """Allocate and finish transactions (single-threaded)."""

    def __init__(self, wal: object | None = None) -> None:
        # PSEUDO: store wal; init counters
        raise NotImplementedError("V3 Person A: implement TransactionManager.__init__")

    def begin(
        self,
        isolation: IsolationLevel = IsolationLevel.SNAPSHOT,
    ) -> Transaction:
        raise NotImplementedError("V3 Person A: implement TransactionManager.begin")

    def commit(self, txn: Transaction) -> None:
        raise NotImplementedError("V3 Person A: implement TransactionManager.commit")

    def abort(self, txn: Transaction) -> None:
        raise NotImplementedError("V3 Person A: implement TransactionManager.abort")

    def get(self, txn_id: int) -> Transaction | None:
        raise NotImplementedError("V3 Person A: implement TransactionManager.get")

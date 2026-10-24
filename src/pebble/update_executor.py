"""V3 Person B (from V4) — UpdateExecutor: update columns on matching rows.

PREREQUISITES:
  - pebble.executor.Executor
  - pebble.catalog.TableInfo
  - pebble.undo_log.UndoLog (record_update)
  - pebble.transaction.Transaction
  - Indexes: delete old key + insert new key when key columns change

USED BY:
  - database.py: UPDATE t SET col=val WHERE ... (Person B SQL patch)
  - tests/test_delete_update.py

PSEUDOCODE
==========
class UpdateExecutor(Executor):
    def __init__(self, table, child, assignments: dict[col_index, Value],
                 txn=None, undo=None, wal=None):
        ...

    def next(self):
        # get (rid, old_tup) from child / rid scan
        # new_values = old with assignments applied
        # WAL UPDATE with before/after
        # undo.record_update(...)
        # MVP storage: delete old slot + insert new tuple (new RID)
        #   OR in-place if same size (harder with slotted pages)
        # maintain indexes if key cols change
        # yield new tuple

DONE WHEN:
  - UPDATE changes values seen by later SELECT
  - Indexed key update keeps IndexScan correct
  - Abort restores before image via UndoLog
"""

from __future__ import annotations

from pebble.catalog import TableInfo
from pebble.executor import Executor
from pebble.tuple import Tuple
from pebble.types import Value


class UpdateExecutor(Executor):
    """Update columns on rows from a child plan."""

    def __init__(
        self,
        table: TableInfo,
        child: Executor,
        assignments: dict[int, Value],
        txn: object | None = None,
        undo: object | None = None,
        wal: object | None = None,
    ) -> None:
        raise NotImplementedError("V3 Person B: implement UpdateExecutor.__init__")

    def init(self) -> None:
        raise NotImplementedError("V3 Person B: implement UpdateExecutor.init")

    def next(self) -> Tuple | None:
        raise NotImplementedError("V3 Person B: implement UpdateExecutor.next")

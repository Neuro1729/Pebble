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
from pebble.delete_executor import _resolve_target
from pebble.executor import Executor
from pebble.slotted_page import SlottedPage
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
        self._table = table
        self._child = child
        self._assignments = dict(assignments)
        self._txn = txn
        self._undo = undo
        self._wal = wal
        for index in self._assignments:
            if index < 0 or index >= table.schema.column_count():
                raise IndexError(f"assignment column index out of range: {index}")

    def init(self) -> None:
        self._child.init()

    def next(self) -> Tuple | None:
        target = self._child.next()
        if target is None:
            return None
        old_rid, before = _resolve_target(self._table, target)
        values = list(before.values)
        for index, value in self._assignments.items():
            values[index] = value
        after = Tuple.from_values(self._table.schema, values)
        txn_id = getattr(self._txn, "txn_id", None)
        if self._undo is not None and txn_id is not None:
            self._undo.record_update(txn_id, old_rid, before, after)
        with self._table.heap._bpm.fetch_page_write(old_rid.page_id) as guard:
            SlottedPage(guard.page).delete_tuple(old_rid.slot_num)
        for index in self._table.indexes:
            index.tree.delete(index.key_from_tuple(before))
        new_rid = self._table.heap.insert_tuple(after)
        for index in self._table.indexes:
            index.tree.insert(index.key_from_tuple(after), new_rid)
        if self._undo is not None and txn_id is not None:
            self._undo.set_replacement_rid(txn_id, new_rid)
        if self._txn is not None:
            self._txn.write_set.append(new_rid)
        return after

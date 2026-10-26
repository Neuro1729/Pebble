"""V3 Person B (from V4) — DeleteExecutor: delete rows from child RIDs / predicates.

PREREQUISITES:
  - pebble.executor.Executor
  - pebble.catalog.TableInfo (heap + indexes)
  - pebble.undo_log.UndoLog (record_delete)
  - pebble.transaction.Transaction (optional but preferred)
  - slotted_page already has delete_tuple; TableHeap may need mark_delete helper

USED BY:
  - database.py: DELETE FROM t WHERE ... (Person B SQL patch)
  - tests/test_delete_update.py

PSEUDOCODE
==========
class DeleteExecutor(Executor):
    def __init__(self, table, child, txn=None, undo=None, wal=None):
        # child yields tuples to delete; OR child yields (RID, Tuple)
        # Prefer: child is SeqScan/Filter; you need RIDs → extend scan to expose RID
        #   MVP: child is a list of RIDs planned by database.py

    def init(self):
        # child.init(); self._done counting

    def next(self):
        # pull next target from child
        # WAL DELETE (if wal)
        # undo.record_delete(...)
        # heap.mark_deleted(rid)  # may add method on TableHeap
        # index.tree.delete(key) for each secondary index
        # txn.write_set.append(rid)
        # yield deleted tuple (or count-only later)

NOTE: If SeqScan does not expose RID yet, add a tiny RidSeqScan helper in this
file or extend TableHeap.scan usage in database planning.

DONE WHEN:
  - DELETE removes row from later SeqScan
  - Index entry removed when indexed
  - Abort path can restore via UndoLog (with Person A TM.abort)
"""

from __future__ import annotations

from pebble.catalog import TableInfo
from pebble.executor import Executor
from pebble.rid import RID
from pebble.slotted_page import SlottedPage
from pebble.tuple import Tuple


class DeleteExecutor(Executor):
    """Delete rows identified by a child plan (or RID list)."""

    def __init__(
        self,
        table: TableInfo,
        child: Executor,
        txn: object | None = None,
        undo: object | None = None,
        wal: object | None = None,
    ) -> None:
        self._table = table
        self._child = child
        self._txn = txn
        self._undo = undo
        self._wal = wal

    def init(self) -> None:
        self._child.init()

    def next(self) -> Tuple | None:
        target = self._child.next()
        if target is None:
            return None
        rid, tup = _resolve_target(self._table, target)
        txn_id = getattr(self._txn, "txn_id", None)
        if self._undo is not None and txn_id is not None:
            self._undo.record_delete(txn_id, rid, tup)
        with self._table.heap._bpm.fetch_page_write(rid.page_id) as guard:
            SlottedPage(guard.page).delete_tuple(rid.slot_num)
        for index in self._table.indexes:
            index.tree.delete(index.key_from_tuple(tup))
        if self._txn is not None:
            self._txn.write_set.append(rid)
        return tup


def _resolve_target(table: TableInfo, target: object) -> tuple[RID, Tuple]:
    if isinstance(target, tuple) and len(target) == 2 and isinstance(target[0], RID):
        rid, tup = target
        return rid, tup
    if isinstance(target, RID):
        return target, table.heap.get_tuple(target)
    if isinstance(target, Tuple):
        for rid, tup in table.heap.scan():
            if tup.values == target.values:
                return rid, tup
        raise ValueError("target tuple is no longer present in the table")
    raise TypeError("DML child must yield Tuple, RID, or (RID, Tuple)")

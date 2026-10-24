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
        raise NotImplementedError("V3 Person B: implement DeleteExecutor.__init__")

    def init(self) -> None:
        raise NotImplementedError("V3 Person B: implement DeleteExecutor.init")

    def next(self) -> Tuple | None:
        raise NotImplementedError("V3 Person B: implement DeleteExecutor.next")

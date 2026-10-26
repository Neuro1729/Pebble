"""V3 Person B (from V4) — undo / version-chain helpers for MVCC-ish rows.

PREREQUISITES:
  - pebble.rid.RID
  - pebble.tuple.Tuple
  - slotted_page delete/mark helpers (already have delete_tuple)
  - Optional: LogRecord payload format from Person A (agree on bytes layout)

USED BY:
  - delete_executor / update_executor
  - TableHeap visibility (later wire into scan)
  - TransactionManager.abort rollback
  - tests/test_undo_log.py

DESIGN (V3 MVP, optimistic / timestamp style):
  Each row version conceptually:
    begin_ts, end_ts (inf if alive), txn_id that wrote it, prev_version RID/link
  V3 may store undo as in-memory chain keyed by RID if page format change is hard.
  Prefer: in-memory UndoLog first; document how page header would look in V4.

PSEUDOCODE
==========
@dataclass
class UndoRecord:
    rid: RID
    txn_id: int
    kind: INSERT | DELETE | UPDATE
    before_tuple: Tuple | None
    after_tuple: Tuple | None
    prev: UndoRecord | None

class UndoLog:
    def __init__(self):
        self._by_txn: dict[int, list[UndoRecord]] = {}

    def record_insert(self, txn_id, rid, after_tuple): ...
    def record_delete(self, txn_id, rid, before_tuple): ...
    def record_update(self, txn_id, rid, before, after): ...

    def rollback_txn(self, txn_id, heap) -> None:
        # apply undo records in reverse: restore before images / un-delete

def visible(version_meta, read_ts: int, active_txn_ids: set[int]) -> bool:
    # SNAPSHOT: begin_ts <= read_ts < end_ts and writer committed
    # (document exact rule you implement)

DONE WHEN:
  - Undo records round-trip for insert/delete/update
  - rollback_txn restores heap state for a simple abort test
  - visible() unit-tested with hand-built timestamps
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from pebble.rid import RID
from pebble.slotted_page import SlottedPage
from pebble.tuple import Tuple


class UndoKind(Enum):
    INSERT = auto()
    DELETE = auto()
    UPDATE = auto()


@dataclass
class UndoRecord:
    rid: RID
    txn_id: int
    kind: UndoKind
    before_tuple: Tuple | None
    after_tuple: Tuple | None
    replacement_rid: RID | None = None


@dataclass
class VersionMeta:
    """Logical version stamp (in-memory MVP OK)."""

    begin_ts: int
    end_ts: int  # use a large sentinel for \"alive\"
    writer_txn_id: int


def visible(
    meta: VersionMeta,
    read_ts: int,
    committed_txn_ids: set[int],
) -> bool:
    """Return True if this version is visible to a reader at read_ts."""
    return (
        meta.writer_txn_id in committed_txn_ids
        and meta.begin_ts <= read_ts < meta.end_ts
    )


class UndoLog:
    """Per-txn undo list for abort rollback."""

    def __init__(self) -> None:
        self._by_txn: dict[int, list[UndoRecord]] = {}

    def record_insert(self, txn_id: int, rid: RID, after_tuple: Tuple) -> None:
        self._by_txn.setdefault(txn_id, []).append(
            UndoRecord(rid, txn_id, UndoKind.INSERT, None, after_tuple)
        )

    def record_delete(self, txn_id: int, rid: RID, before_tuple: Tuple) -> None:
        self._by_txn.setdefault(txn_id, []).append(
            UndoRecord(rid, txn_id, UndoKind.DELETE, before_tuple, None)
        )

    def record_update(
        self,
        txn_id: int,
        rid: RID,
        before_tuple: Tuple,
        after_tuple: Tuple,
    ) -> None:
        self._by_txn.setdefault(txn_id, []).append(
            UndoRecord(rid, txn_id, UndoKind.UPDATE, before_tuple, after_tuple)
        )

    def set_replacement_rid(self, txn_id: int, rid: RID) -> None:
        """Attach the new heap RID used by a delete-plus-insert update."""
        if not self._by_txn.get(txn_id) or self._by_txn[txn_id][-1].kind is not UndoKind.UPDATE:
            raise ValueError("no pending update record for transaction")
        self._by_txn[txn_id][-1].replacement_rid = rid

    def records_for(self, txn_id: int) -> list[UndoRecord]:
        return list(self._by_txn.get(txn_id, ()))

    def clear_txn(self, txn_id: int) -> None:
        self._by_txn.pop(txn_id, None)

    def rollback_txn(self, txn_id: int, table: object) -> None:
        """Undo changes in reverse order; ``table`` is a TableInfo or TableHeap.

        Updates use a delete-plus-insert heap representation, so restoring a
        deleted or updated row may assign it a new RID. Indexes are repaired.
        """
        records = self._by_txn.get(txn_id, [])
        heap = getattr(table, "heap", table)
        indexes = getattr(table, "indexes", [])
        for record in reversed(records):
            if record.kind is UndoKind.INSERT:
                if record.after_tuple is not None:
                    _mark_deleted(heap, record.rid)
                    _remove_indexes(indexes, record.after_tuple)
            elif record.kind is UndoKind.DELETE:
                if record.before_tuple is not None:
                    restored = heap.insert_tuple(record.before_tuple)
                    _insert_indexes(indexes, record.before_tuple, restored)
            else:  # UPDATE
                if record.replacement_rid is not None and record.after_tuple is not None:
                    _mark_deleted(heap, record.replacement_rid)
                    _remove_indexes(indexes, record.after_tuple)
                if record.before_tuple is not None:
                    restored = heap.insert_tuple(record.before_tuple)
                    _insert_indexes(indexes, record.before_tuple, restored)
        self.clear_txn(txn_id)


def _mark_deleted(heap: object, rid: RID) -> None:
    bpm = heap._bpm
    with bpm.fetch_page_write(rid.page_id) as guard:
        SlottedPage(guard.page).delete_tuple(rid.slot_num)


def _remove_indexes(indexes: list[object], tup: Tuple) -> None:
    for index in indexes:
        index.tree.delete(index.key_from_tuple(tup))


def _insert_indexes(indexes: list[object], tup: Tuple, rid: RID) -> None:
    for index in indexes:
        index.tree.insert(index.key_from_tuple(tup), rid)

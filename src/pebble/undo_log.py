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
    raise NotImplementedError("V3 Person B: implement visible()")


class UndoLog:
    """Per-txn undo list for abort rollback."""

    def __init__(self) -> None:
        raise NotImplementedError("V3 Person B: implement UndoLog.__init__")

    def record_insert(self, txn_id: int, rid: RID, after_tuple: Tuple) -> None:
        raise NotImplementedError("V3 Person B: implement record_insert")

    def record_delete(self, txn_id: int, rid: RID, before_tuple: Tuple) -> None:
        raise NotImplementedError("V3 Person B: implement record_delete")

    def record_update(
        self,
        txn_id: int,
        rid: RID,
        before_tuple: Tuple,
        after_tuple: Tuple,
    ) -> None:
        raise NotImplementedError("V3 Person B: implement record_update")

    def records_for(self, txn_id: int) -> list[UndoRecord]:
        raise NotImplementedError("V3 Person B: implement records_for")

    def clear_txn(self, txn_id: int) -> None:
        raise NotImplementedError("V3 Person B: implement clear_txn")

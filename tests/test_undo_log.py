from __future__ import annotations

from pebble.rid import RID
from pebble.tuple import Tuple
from pebble.undo_log import UndoKind, UndoLog, VersionMeta, visible


def test_record_and_list_for_txn() -> None:
    log = UndoLog()
    rid = RID(2, 1)
    log.record_insert(1, rid, Tuple([1]))
    log.record_delete(1, rid, Tuple([1]))
    log.record_update(2, rid, Tuple([1]), Tuple([2]))
    assert [r.kind for r in log.records_for(1)] == [UndoKind.INSERT, UndoKind.DELETE]
    assert log.records_for(2)[0].after_tuple.values == [2]


def test_visible_snapshot_rules() -> None:
    assert visible(VersionMeta(2, 9, 1), 3, {1})
    assert not visible(VersionMeta(4, 9, 1), 3, {1})
    assert not visible(VersionMeta(2, 9, 2), 3, {1})
    assert not visible(VersionMeta(2, 3, 1), 3, {1})

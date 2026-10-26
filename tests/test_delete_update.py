from __future__ import annotations

from pathlib import Path

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.delete_executor import DeleteExecutor
from pebble.disk_manager import DiskManager
from pebble.executor import Executor, IndexScanExecutor, InsertExecutor, SeqScanExecutor, poll
from pebble.rid import RID
from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId
from pebble.undo_log import UndoLog
from pebble.update_executor import UpdateExecutor


class Rows(Executor):
    def __init__(self, rows): self.rows, self.i = rows, 0
    def init(self): self.i = 0
    def next(self):
        if self.i >= len(self.rows): return None
        row = self.rows[self.i]; self.i += 1; return row


def _table(tmp_path: Path):
    disk = DiskManager(tmp_path / "dml.db")
    bpm = BufferPoolManager(8, disk)
    catalog = Catalog(bpm)
    schema = Schema([Column("id", TypeId.INTEGER), Column("name", TypeId.VARCHAR)])
    table = catalog.create_table("t", schema)
    return disk, bpm, catalog, table


def test_delete_removes_from_seqscan(tmp_path: Path) -> None:
    disk, bpm, _catalog, table = _table(tmp_path)
    try:
        poll(InsertExecutor(table, [Tuple([1, "a"]), Tuple([2, "b"])]))
        poll(DeleteExecutor(table, Rows([Tuple([1, "a"])])))
        assert [row.values for row in poll(SeqScanExecutor(table))] == [[2, "b"]]
    finally:
        bpm.close(); disk.close()


def test_update_changes_values(tmp_path: Path) -> None:
    disk, bpm, _catalog, table = _table(tmp_path)
    try:
        poll(InsertExecutor(table, [Tuple([1, "a"])]))
        poll(UpdateExecutor(table, Rows([Tuple([1, "a"])]), {1: "updated"}))
        assert [row.values for row in poll(SeqScanExecutor(table))] == [[1, "updated"]]
    finally:
        bpm.close(); disk.close()


def test_update_maintains_index(tmp_path: Path) -> None:
    disk, bpm, catalog, table = _table(tmp_path)
    try:
        poll(InsertExecutor(table, [Tuple([1, "a"])]))
        index = catalog.create_index("by_id", "t", ["id"])
        poll(UpdateExecutor(table, Rows([Tuple([1, "a"])]), {0: 2}))
        assert poll(IndexScanExecutor(table, index, equals_key=1)) == []
        assert [t.values for t in poll(IndexScanExecutor(table, index, equals_key=2))] == [[2, "a"]]
    finally:
        bpm.close(); disk.close()


def test_abort_restores_deleted_row(tmp_path: Path) -> None:
    disk, bpm, _catalog, table = _table(tmp_path)
    try:
        poll(InsertExecutor(table, [Tuple([1, "a"])]))
        rid, original = next(table.heap.scan())
        undo = UndoLog()
        poll(DeleteExecutor(table, Rows([(rid, original)]), txn=type("Txn", (), {"txn_id": 7, "write_set": []})(), undo=undo))
        undo.rollback_txn(7, table)
        assert [row.values for row in poll(SeqScanExecutor(table))] == [[1, "a"]]
    finally:
        bpm.close(); disk.close()

"""Step 5: table heap insert/scan across multiple pages."""

from __future__ import annotations

from pathlib import Path

from pebble.buffer_pool import BufferPoolManager
from pebble.disk_manager import DiskManager
from pebble.schema import Column, Schema
from pebble.table_heap import TableHeap
from pebble.tuple import Tuple
from pebble.types import TypeId


def _schema() -> Schema:
    return Schema(
        [
            Column("id", TypeId.INTEGER),
            Column("name", TypeId.VARCHAR),
        ]
    )


def test_insert_many_rows_scan_after_reopen(tmp_path: Path) -> None:
    db_file = tmp_path / "heap.db"
    schema = _schema()
    n = 400  # large enough that rows spill across multiple pages

    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=8, disk_manager=disk)
        heap = TableHeap.create(bpm, schema)
        first = heap.first_page_id
        for i in range(n):
            heap.insert_tuple(Tuple.from_values(schema, [i, f"row-{i:04d}"]))
        last = heap.last_page_id
        assert last != first  # spilled across pages
        bpm.flush_all_pages()

    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=8, disk_manager=disk)
        heap = TableHeap(bpm, schema, first_page_id=first, last_page_id=last)
        rows = list(heap.scan())
        assert len(rows) == n
        assert [t.values[0] for _, t in rows] == list(range(n))
        assert [t.values[1] for _, t in rows] == [f"row-{i:04d}" for i in range(n)]


def test_get_tuple_by_rid(tmp_path: Path) -> None:
    db_file = tmp_path / "get.db"
    schema = _schema()
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=4, disk_manager=disk)
        heap = TableHeap.create(bpm, schema)
        rid = heap.insert_tuple(Tuple.from_values(schema, [7, "seven"]))
        got = heap.get_tuple(rid)
        assert got.values == [7, "seven"]

"""V2 step 1: page guards pin on enter and unpin on exit."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_read_write_guards_unpin_on_exit(tmp_path: Path) -> None:
    db_file = tmp_path / "guards.db"
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=4, disk_manager=disk)

        with bpm.new_page_write() as wguard:
            page_id = wguard.page_id
            wguard.page.data[0:4] = b"ZZZZ"
            assert bpm.get_pin_count(page_id) == 1

        assert bpm.get_pin_count(page_id) == 0

        with bpm.fetch_page_read(page_id) as rguard:
            assert bytes(rguard.page.data[0:4]) == b"ZZZZ"
            assert bpm.get_pin_count(page_id) == 1

        assert bpm.get_pin_count(page_id) == 0


def test_drop_is_idempotent(tmp_path: Path) -> None:
    db_file = tmp_path / "drop.db"
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=2, disk_manager=disk)
        guard = bpm.new_page_write()
        page_id = guard.page_id
        guard.drop()
        guard.drop()
        assert bpm.get_pin_count(page_id) == 0
        with pytest.raises(RuntimeError, match="already dropped"):
            _ = guard.page


def test_heap_ops_leave_zero_pins(tmp_path: Path) -> None:
    db_file = tmp_path / "heap_pins.db"
    schema = _schema()
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=8, disk_manager=disk)
        heap = TableHeap.create(bpm, schema)
        first = heap.first_page_id
        assert bpm.get_pin_count(first) == 0

        for i in range(50):
            heap.insert_tuple(Tuple.from_values(schema, [i, f"r{i}"]))
        assert bpm.get_pin_count(heap.first_page_id) == 0
        assert bpm.get_pin_count(heap.last_page_id) == 0

        rows = list(heap.scan())
        assert len(rows) == 50
        assert bpm.get_pin_count(heap.first_page_id) == 0
        assert bpm.get_pin_count(heap.last_page_id) == 0

        rid, _ = rows[0]
        got = heap.get_tuple(rid)
        assert got.values[0] == 0
        assert bpm.get_pin_count(rid.page_id) == 0

"""Step 4: slotted page insert/get and survive flush + reload."""

from __future__ import annotations

from pathlib import Path

import pytest

from pebble.buffer_pool import BufferPoolManager
from pebble.disk_manager import DiskManager
from pebble.page import Page
from pebble.schema import Column, Schema
from pebble.slotted_page import SlottedPage
from pebble.tuple import Tuple
from pebble.types import TypeId


def test_insert_and_get_multiple_tuples() -> None:
    page = Page(page_id=0)
    sp = SlottedPage.initialize(page)

    s0 = sp.insert_tuple(b"hello")
    s1 = sp.insert_tuple(b"world")
    s2 = sp.insert_tuple(b"!")

    assert s0 == 0
    assert s1 == 1
    assert s2 == 2
    assert sp.get_tuple(0) == b"hello"
    assert sp.get_tuple(1) == b"world"
    assert sp.get_tuple(2) == b"!"
    assert sp.iter_slots() == [(0, b"hello"), (1, b"world"), (2, b"!")]


def test_survives_flush_and_reload_via_buffer_pool(tmp_path: Path) -> None:
    schema = Schema([Column("id", TypeId.INTEGER), Column("name", TypeId.VARCHAR)])
    t0 = Tuple.from_values(schema, [1, "a"]).to_bytes(schema)
    t1 = Tuple.from_values(schema, [2, "bb"]).to_bytes(schema)

    db_file = tmp_path / "slotted.db"
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=4, disk_manager=disk)
        page = bpm.new_page()
        page_id = page.page_id
        sp = SlottedPage.initialize(page)
        sp.insert_tuple(t0)
        sp.insert_tuple(t1)
        bpm.unpin_page(page_id, is_dirty=True)
        bpm.flush_all_pages()

    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=4, disk_manager=disk)
        page = bpm.fetch_page(page_id)
        sp = SlottedPage(page)
        assert Tuple.from_bytes(schema, sp.get_tuple(0)).values == [1, "a"]
        assert Tuple.from_bytes(schema, sp.get_tuple(1)).values == [2, "bb"]
        bpm.unpin_page(page_id, is_dirty=False)


def test_page_full_raises() -> None:
    page = Page(page_id=0)
    sp = SlottedPage.initialize(page)
    # Fill until insert fails.
    chunk = b"x" * 64
    with pytest.raises(MemoryError, match="full"):
        while True:
            sp.insert_tuple(chunk)


def test_delete_marks_slot_empty() -> None:
    page = Page(page_id=0)
    sp = SlottedPage.initialize(page)
    sp.insert_tuple(b"a")
    sp.insert_tuple(b"b")
    sp.delete_tuple(0)
    with pytest.raises(ValueError, match="empty"):
        sp.get_tuple(0)
    assert sp.iter_slots() == [(1, b"b")]

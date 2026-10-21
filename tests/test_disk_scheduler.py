"""V2 step 3: DiskScheduler queues I/O onto a background worker."""

from __future__ import annotations

from pathlib import Path

import pytest

from pebble.buffer_pool import BufferPoolManager
from pebble.config import PAGE_SIZE
from pebble.disk_manager import DiskManager
from pebble.disk_scheduler import DiskScheduler
from pebble.page import Page


def test_scheduler_write_then_read(tmp_path: Path) -> None:
    db_file = tmp_path / "sched.db"
    with DiskManager(db_file) as disk:
        with DiskScheduler(disk) as sched:
            page_id = sched.allocate_page()
            page = Page(page_id=page_id)
            page.data[0:5] = b"hello"
            sched.write_page(page)

            loaded = sched.read_page(page_id)
            assert bytes(loaded.data[0:5]) == b"hello"
            assert len(loaded.data) == PAGE_SIZE


def test_scheduler_propagates_errors(tmp_path: Path) -> None:
    db_file = tmp_path / "err.db"
    with DiskManager(db_file) as disk:
        with DiskScheduler(disk) as sched:
            with pytest.raises(ValueError, match="does not exist"):
                sched.read_page(99)


def test_bpm_fetch_flush_via_scheduler(tmp_path: Path) -> None:
    db_file = tmp_path / "bpm_sched.db"
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=2, disk_manager=disk) as bpm:
            p0 = bpm.new_page()
            id0 = p0.page_id
            p0.data[0:4] = b"AAAA"
            bpm.unpin_page(id0, is_dirty=True)

            p1 = bpm.new_page()
            id1 = p1.page_id
            p1.data[0:4] = b"BBBB"
            bpm.unpin_page(id1, is_dirty=True)

            # Evict + reload through scheduler-backed I/O
            p2 = bpm.new_page()
            bpm.unpin_page(p2.page_id, is_dirty=False)

            again = bpm.fetch_page(id0)
            assert bytes(again.data[0:4]) == b"AAAA"
            bpm.unpin_page(id0, is_dirty=False)
            bpm.flush_all_pages()

    with DiskManager(db_file) as disk:
        assert bytes(disk.read_page(id0).data[0:4]) == b"AAAA"
        assert bytes(disk.read_page(id1).data[0:4]) == b"BBBB"

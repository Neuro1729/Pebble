"""Step 3: Buffer pool with FIFO eviction."""

from __future__ import annotations

from pathlib import Path

import pytest

from pebble.buffer_pool import BufferPoolManager
from pebble.disk_manager import DiskManager


def test_fetch_more_than_pool_size_evicts_and_persists(tmp_path: Path) -> None:
    db_file = tmp_path / "pool.db"
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=2, disk_manager=disk)

        p0 = bpm.new_page()
        id0 = p0.page_id
        p0.data[0:4] = b"AAAA"
        bpm.unpin_page(id0, is_dirty=True)

        p1 = bpm.new_page()
        id1 = p1.page_id
        p1.data[0:4] = b"BBBB"
        bpm.unpin_page(id1, is_dirty=True)

        # Pool full; this must evict the oldest (id0) and flush dirty bytes.
        p2 = bpm.new_page()
        id2 = p2.page_id
        p2.data[0:4] = b"CCCC"
        bpm.unpin_page(id2, is_dirty=True)

        # id0 should come back from disk with the written marker.
        again = bpm.fetch_page(id0)
        assert bytes(again.data[0:4]) == b"AAAA"
        bpm.unpin_page(id0, is_dirty=False)

        bpm.flush_all_pages()

    with DiskManager(db_file) as disk:
        assert bytes(disk.read_page(id0).data[0:4]) == b"AAAA"
        assert bytes(disk.read_page(id1).data[0:4]) == b"BBBB"
        assert bytes(disk.read_page(id2).data[0:4]) == b"CCCC"


def test_cannot_evict_when_all_frames_pinned(tmp_path: Path) -> None:
    db_file = tmp_path / "pinned.db"
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=2, disk_manager=disk)
        bpm.new_page()
        bpm.new_page()
        with pytest.raises(RuntimeError, match="no evictable"):
            bpm.new_page()


def test_fetch_hit_increments_pin(tmp_path: Path) -> None:
    db_file = tmp_path / "hit.db"
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=2, disk_manager=disk)
        page = bpm.new_page()
        page_id = page.page_id
        page.data[0] = 7
        bpm.unpin_page(page_id, is_dirty=True)

        a = bpm.fetch_page(page_id)
        b = bpm.fetch_page(page_id)
        assert a is b
        assert a.data[0] == 7
        bpm.unpin_page(page_id, is_dirty=False)
        bpm.unpin_page(page_id, is_dirty=False)

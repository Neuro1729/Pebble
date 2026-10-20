"""Step 2: Page + DiskManager persist and reload."""

from __future__ import annotations

from pathlib import Path

import pytest

from pebble.config import PAGE_SIZE
from pebble.disk_manager import DiskManager
from pebble.page import Page


def test_write_page0_reopen_read_back(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    payload = bytes((i * 7) % 256 for i in range(PAGE_SIZE))

    with DiskManager(db_file) as dm:
        page = Page(page_id=0, data=payload)
        dm.write_page(page)

    with DiskManager(db_file) as dm:
        restored = dm.read_page(0)
        assert restored.page_id == 0
        assert bytes(restored.data) == payload


def test_allocate_page_then_read(tmp_path: Path) -> None:
    db_file = tmp_path / "alloc.db"

    with DiskManager(db_file) as dm:
        page_id = dm.allocate_page()
        assert page_id == 0
        page = dm.read_page(page_id)
        page.data[0:4] = b"abcd"
        dm.write_page(page)

        page_id2 = dm.allocate_page()
        assert page_id2 == 1

    with DiskManager(db_file) as dm:
        assert bytes(dm.read_page(0).data[0:4]) == b"abcd"
        assert bytes(dm.read_page(1).data[0:4]) == b"\x00\x00\x00\x00"


def test_page_rejects_wrong_size() -> None:
    with pytest.raises(ValueError, match="4096"):
        Page(page_id=0, data=b"too-small")

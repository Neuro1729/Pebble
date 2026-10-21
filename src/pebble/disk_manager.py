"""Sync page I/O against a single database file.

V1: blocking seek + read/write at page_id * PAGE_SIZE.
V2: BufferPoolManager talks to DiskManager only via DiskScheduler (one worker).
"""

from __future__ import annotations

from pathlib import Path

from pebble.config import PAGE_SIZE
from pebble.page import Page


class DiskManager:
    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Create file if missing; keep existing contents on reopen.
        self._file = self._path.open("r+b") if self._path.exists() else self._path.open("w+b")
        self._next_page_id = self._file_page_count()

    def close(self) -> None:
        self._file.flush()
        self._file.close()

    def __enter__(self) -> DiskManager:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def db_path(self) -> Path:
        return self._path

    def allocate_page(self) -> int:
        """Reserve a new page_id and extend the file with a zero page."""
        page_id = self._next_page_id
        self._next_page_id += 1
        self.write_page(Page(page_id=page_id))
        return page_id

    def write_page(self, page: Page) -> None:
        if page.page_id < 0:
            raise ValueError(f"invalid page_id: {page.page_id}")
        if len(page.data) != PAGE_SIZE:
            raise ValueError(f"page must be {PAGE_SIZE} bytes")
        self._file.seek(page.page_id * PAGE_SIZE)
        self._file.write(page.data)
        self._file.flush()
        if page.page_id >= self._next_page_id:
            self._next_page_id = page.page_id + 1

    def read_page(self, page_id: int) -> Page:
        if page_id < 0:
            raise ValueError(f"invalid page_id: {page_id}")
        self._file.seek(page_id * PAGE_SIZE)
        raw = self._file.read(PAGE_SIZE)
        if len(raw) == 0:
            raise ValueError(f"page_id {page_id} does not exist on disk")
        if len(raw) != PAGE_SIZE:
            raise ValueError(f"short read for page_id {page_id}: got {len(raw)} bytes")
        return Page(page_id=page_id, data=raw)

    def _file_page_count(self) -> int:
        self._file.seek(0, 2)
        size = self._file.tell()
        if size % PAGE_SIZE != 0:
            raise ValueError(f"corrupt db file size {size}, not a multiple of {PAGE_SIZE}")
        return size // PAGE_SIZE

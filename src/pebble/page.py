"""Fixed-size page: PAGE_SIZE bytes of raw storage.

A page is the unit of disk I/O. Contents are opaque here; slotted layout comes in step 4.
"""

from __future__ import annotations

from pebble.config import INVALID_PAGE_ID, PAGE_SIZE


class Page:
    def __init__(self, page_id: int = INVALID_PAGE_ID, data: bytes | bytearray | None = None) -> None:
        if data is None:
            self._data = bytearray(PAGE_SIZE)
        else:
            if len(data) != PAGE_SIZE:
                raise ValueError(f"page data must be {PAGE_SIZE} bytes, got {len(data)}")
            self._data = bytearray(data)
        self.page_id = page_id

    @property
    def data(self) -> bytearray:
        return self._data

    def clear(self) -> None:
        self._data[:] = b"\x00" * PAGE_SIZE

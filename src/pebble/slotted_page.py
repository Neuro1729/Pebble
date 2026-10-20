"""Slotted page layout over a Page's bytearray.

Layout (PAGE_SIZE bytes):
  [ header | slot directory growing → | free space | ← tuple bytes ]

Header (8 bytes):
  next_page_id : int32   (for table-heap chaining in step 5)
  num_slots    : uint16
  free_top     : uint16  (start of tuple region; grows downward)

Each slot (4 bytes):
  offset : uint16  (start of tuple bytes in the page)
  length : uint16  (0 means deleted / empty slot)

V1: no compaction on delete. LATER: reclaim free space / defrag.
"""

from __future__ import annotations

import struct

from pebble.config import INVALID_PAGE_ID, PAGE_SIZE
from pebble.page import Page

_HEADER = struct.Struct("<iHH")  # next_page_id, num_slots, free_top
_SLOT = struct.Struct("<HH")  # offset, length
_HEADER_SIZE = _HEADER.size
_SLOT_SIZE = _SLOT.size


class SlottedPage:
    def __init__(self, page: Page) -> None:
        if len(page.data) != PAGE_SIZE:
            raise ValueError("page data must be PAGE_SIZE")
        self._page = page

    @property
    def page(self) -> Page:
        return self._page

    @classmethod
    def initialize(cls, page: Page, next_page_id: int = INVALID_PAGE_ID) -> SlottedPage:
        """Format a raw page as an empty slotted page."""
        page.clear()
        page.data[0:_HEADER_SIZE] = _HEADER.pack(next_page_id, 0, PAGE_SIZE)
        return cls(page)

    def get_next_page_id(self) -> int:
        next_page_id, _, _ = _HEADER.unpack_from(self._page.data, 0)
        return next_page_id

    def set_next_page_id(self, next_page_id: int) -> None:
        _, num_slots, free_top = _HEADER.unpack_from(self._page.data, 0)
        _HEADER.pack_into(self._page.data, 0, next_page_id, num_slots, free_top)

    def num_slots(self) -> int:
        _, num_slots, _ = _HEADER.unpack_from(self._page.data, 0)
        return num_slots

    def free_space(self) -> int:
        """Bytes available for a new slot entry + tuple payload."""
        _, num_slots, free_top = _HEADER.unpack_from(self._page.data, 0)
        lower = _HEADER_SIZE + num_slots * _SLOT_SIZE
        return free_top - lower

    def insert_tuple(self, data: bytes) -> int:
        """Insert tuple bytes; return slot_num. Raises if not enough space."""
        if not data:
            raise ValueError("cannot insert empty tuple")
        next_page_id, num_slots, free_top = _HEADER.unpack_from(self._page.data, 0)
        needed = _SLOT_SIZE + len(data)
        lower = _HEADER_SIZE + num_slots * _SLOT_SIZE
        if free_top - lower < needed:
            raise MemoryError("page is full")

        new_free_top = free_top - len(data)
        self._page.data[new_free_top:free_top] = data

        slot_num = num_slots
        slot_off = _HEADER_SIZE + slot_num * _SLOT_SIZE
        _SLOT.pack_into(self._page.data, slot_off, new_free_top, len(data))
        _HEADER.pack_into(self._page.data, 0, next_page_id, num_slots + 1, new_free_top)
        return slot_num

    def get_tuple(self, slot_num: int) -> bytes:
        offset, length = self._slot(slot_num)
        if length == 0:
            raise ValueError(f"slot {slot_num} is empty/deleted")
        return bytes(self._page.data[offset : offset + length])

    def delete_tuple(self, slot_num: int) -> None:
        """Mark slot deleted (length=0). Does not compact free space in V1."""
        offset, length = self._slot(slot_num)
        if length == 0:
            return
        slot_off = _HEADER_SIZE + slot_num * _SLOT_SIZE
        _SLOT.pack_into(self._page.data, slot_off, offset, 0)

    def iter_slots(self) -> list[tuple[int, bytes]]:
        """Return (slot_num, tuple_bytes) for all non-deleted slots."""
        result: list[tuple[int, bytes]] = []
        for slot_num in range(self.num_slots()):
            offset, length = self._slot(slot_num)
            if length == 0:
                continue
            result.append((slot_num, bytes(self._page.data[offset : offset + length])))
        return result

    def _slot(self, slot_num: int) -> tuple[int, int]:
        if slot_num < 0 or slot_num >= self.num_slots():
            raise IndexError(f"slot_num {slot_num} out of range")
        slot_off = _HEADER_SIZE + slot_num * _SLOT_SIZE
        return _SLOT.unpack_from(self._page.data, slot_off)

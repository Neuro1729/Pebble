"""B+Tree leaf / internal page layouts over a Page (V2 step 4).

Keys are signed int32 (matches TypeId.INTEGER). Values are RID on leaves
and child page_id on internals.

Leaf layout:
  [ type u8 | size u16 | max_size u16 | next_page_id i32 | pad 3 ]
  [ key0..keyN-1 (i32 each) ]
  [ rid0..ridN-1 (page_id i32 + slot u16 + pad u16) ]

Internal layout (BusTub-style: size = #children; key[0] unused):
  [ type u8 | size u16 | max_size u16 | pad 3 ]
  [ key0.. | page_id0.. ] interleaved as (key i32, child i32) slots
  Lookup ignores key[0]; child i covers keys in [key[i], key[i+1]).

Step 4: layout + binary search + manual tree walk. Split/merge = step 5.
"""

from __future__ import annotations

import struct
from enum import IntEnum

from pebble.buffer_pool import BufferPoolManager
from pebble.config import INVALID_PAGE_ID, PAGE_SIZE
from pebble.page import Page
from pebble.rid import RID

_LEAF_HDR = struct.Struct("<BHH i 3x")  # type, size, max_size, next, pad
_INTERNAL_HDR = struct.Struct("<BHH 3x")
_KEY = struct.Struct("<i")
_RID = struct.Struct("<iHxx")  # page_id, slot_num, pad
_INTERNAL_SLOT = struct.Struct("<ii")  # key, child_page_id

_LEAF_HDR_SIZE = _LEAF_HDR.size
_INTERNAL_HDR_SIZE = _INTERNAL_HDR.size
_KEY_SIZE = _KEY.size
_RID_SIZE = _RID.size
_INTERNAL_SLOT_SIZE = _INTERNAL_SLOT.size

LEAF_MAX_SIZE = (PAGE_SIZE - _LEAF_HDR_SIZE) // (_KEY_SIZE + _RID_SIZE)
INTERNAL_MAX_SIZE = (PAGE_SIZE - _INTERNAL_HDR_SIZE) // _INTERNAL_SLOT_SIZE


class BPlusPageType(IntEnum):
    INVALID = 0
    LEAF = 1
    INTERNAL = 2


def page_type_of(page: Page) -> BPlusPageType:
    return BPlusPageType(page.data[0])


class BPlusLeafPage:
    """Ordered (key, RID) pairs + sibling link."""

    def __init__(self, page: Page) -> None:
        if len(page.data) != PAGE_SIZE:
            raise ValueError("page data must be PAGE_SIZE")
        self._page = page

    @property
    def page(self) -> Page:
        return self._page

    @classmethod
    def initialize(
        cls,
        page: Page,
        *,
        max_size: int = LEAF_MAX_SIZE,
        next_page_id: int = INVALID_PAGE_ID,
    ) -> BPlusLeafPage:
        if max_size < 1 or max_size > LEAF_MAX_SIZE:
            raise ValueError(f"leaf max_size out of range: {max_size}")
        page.clear()
        leaf = cls(page)
        leaf._pack_header(size=0, max_size=max_size, next_page_id=next_page_id)
        return leaf

    def size(self) -> int:
        return self._header()[1]

    def max_size(self) -> int:
        return self._header()[2]

    def next_page_id(self) -> int:
        return self._header()[3]

    def set_next_page_id(self, next_page_id: int) -> None:
        _, size, max_size, _ = self._header()
        self._pack_header(size, max_size, next_page_id)

    def key_at(self, index: int) -> int:
        self._check_index(index, allow_end=False)
        (key,) = _KEY.unpack_from(self._page.data, self._key_offset(index))
        return key

    def rid_at(self, index: int) -> RID:
        self._check_index(index, allow_end=False)
        page_id, slot = _RID.unpack_from(self._page.data, self._rid_offset(index))
        return RID(page_id=page_id, slot_num=slot)

    def set_at(self, index: int, key: int, rid: RID) -> None:
        self._check_index(index, allow_end=True)
        _KEY.pack_into(self._page.data, self._key_offset(index), key)
        _RID.pack_into(
            self._page.data, self._rid_offset(index), rid.page_id, rid.slot_num
        )

    def insert_at(self, index: int, key: int, rid: RID) -> None:
        """Insert (key, rid) at index, shifting larger keys right."""
        size = self.size()
        max_size = self.max_size()
        if size >= max_size:
            raise MemoryError("leaf page is full")
        if index < 0 or index > size:
            raise IndexError(f"leaf insert index {index} out of range for size {size}")
        for i in range(size, index, -1):
            self.set_at(i, self.key_at(i - 1), self.rid_at(i - 1))
        self.set_at(index, key, rid)
        _, _, max_size, next_id = self._header()
        self._pack_header(size + 1, max_size, next_id)

    def find_key(self, key: int) -> int | None:
        """Binary search: index of ``key``, or None if absent."""
        lo, hi = 0, self.size()
        while lo < hi:
            mid = (lo + hi) // 2
            mid_key = self.key_at(mid)
            if mid_key < key:
                lo = mid + 1
            elif mid_key > key:
                hi = mid
            else:
                return mid
        return None

    def lower_bound(self, key: int) -> int:
        """First index with key_at(i) >= key (or size if all smaller)."""
        lo, hi = 0, self.size()
        while lo < hi:
            mid = (lo + hi) // 2
            if self.key_at(mid) < key:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def dump(self) -> str:
        keys = [str(self.key_at(i)) for i in range(self.size())]
        return f"Leaf(size={self.size()}, next={self.next_page_id()}, keys=[{', '.join(keys)}])"

    def _header(self) -> tuple[int, int, int, int]:
        typ, size, max_size, next_id = _LEAF_HDR.unpack_from(self._page.data, 0)
        if typ != BPlusPageType.LEAF:
            raise ValueError(f"not a leaf page (type={typ})")
        return typ, size, max_size, next_id

    def _pack_header(self, size: int, max_size: int, next_page_id: int) -> None:
        _LEAF_HDR.pack_into(
            self._page.data, 0, BPlusPageType.LEAF, size, max_size, next_page_id
        )

    def _key_offset(self, index: int) -> int:
        return _LEAF_HDR_SIZE + index * _KEY_SIZE

    def _rid_offset(self, index: int) -> int:
        return _LEAF_HDR_SIZE + self.max_size() * _KEY_SIZE + index * _RID_SIZE

    def _check_index(self, index: int, *, allow_end: bool) -> None:
        if index < 0 or index >= self.max_size():
            raise IndexError(f"leaf index {index} out of max_size {self.max_size()}")
        limit = self.size() + (1 if allow_end else 0)
        if index >= limit:
            raise IndexError(f"leaf index {index} out of size {self.size()}")


class BPlusInternalPage:
    """Ordered separator keys + child page_ids (key[0] unused)."""

    def __init__(self, page: Page) -> None:
        if len(page.data) != PAGE_SIZE:
            raise ValueError("page data must be PAGE_SIZE")
        self._page = page

    @property
    def page(self) -> Page:
        return self._page

    @classmethod
    def initialize(
        cls, page: Page, *, max_size: int = INTERNAL_MAX_SIZE
    ) -> BPlusInternalPage:
        if max_size < 2 or max_size > INTERNAL_MAX_SIZE:
            raise ValueError(f"internal max_size out of range: {max_size}")
        page.clear()
        node = cls(page)
        node._pack_header(size=0, max_size=max_size)
        return node

    def size(self) -> int:
        """Number of child pointers (valid keys are indices 1 .. size-1)."""
        return self._header()[1]

    def max_size(self) -> int:
        return self._header()[2]

    def key_at(self, index: int) -> int:
        if index < 0 or index >= self.size():
            raise IndexError(f"internal key index {index}")
        key, _ = _INTERNAL_SLOT.unpack_from(self._page.data, self._slot_offset(index))
        return key

    def value_at(self, index: int) -> int:
        if index < 0 or index >= self.size():
            raise IndexError(f"internal value index {index}")
        _, child = _INTERNAL_SLOT.unpack_from(
            self._page.data, self._slot_offset(index)
        )
        return child

    def set_key_at(self, index: int, key: int) -> None:
        if index < 0 or index >= self.size():
            raise IndexError(f"internal key index {index}")
        _, child = _INTERNAL_SLOT.unpack_from(
            self._page.data, self._slot_offset(index)
        )
        _INTERNAL_SLOT.pack_into(self._page.data, self._slot_offset(index), key, child)

    def set_value_at(self, index: int, child_page_id: int) -> None:
        if index < 0 or index >= self.size():
            raise IndexError(f"internal value index {index}")
        key, _ = _INTERNAL_SLOT.unpack_from(self._page.data, self._slot_offset(index))
        _INTERNAL_SLOT.pack_into(
            self._page.data, self._slot_offset(index), key, child_page_id
        )

    def set_size(self, size: int) -> None:
        if size < 0 or size > self.max_size():
            raise ValueError(f"internal size {size} out of range")
        self._pack_header(size, self.max_size())

    def lookup(self, key: int) -> int:
        """Child page_id for ``key`` (binary search on keys 1..size-1)."""
        size = self.size()
        if size == 0:
            raise RuntimeError("lookup on empty internal page")
        # Find largest index i in 1..size-1 with key_at(i) <= key; else 0.
        lo, hi = 1, size
        while lo < hi:
            mid = (lo + hi) // 2
            if self.key_at(mid) <= key:
                lo = mid + 1
            else:
                hi = mid
        # lo is first index with key_at(lo) > key (or size); child is lo - 1
        return self.value_at(lo - 1)

    def dump(self) -> str:
        size = self.size()
        parts: list[str] = []
        for i in range(size):
            if i == 0:
                parts.append(f"*{self.value_at(i)}")
            else:
                parts.append(f"{self.key_at(i)}->{self.value_at(i)}")
        return f"Internal(size={size}, [{', '.join(parts)}])"

    def _header(self) -> tuple[int, int, int]:
        typ, size, max_size = _INTERNAL_HDR.unpack_from(self._page.data, 0)
        if typ != BPlusPageType.INTERNAL:
            raise ValueError(f"not an internal page (type={typ})")
        return typ, size, max_size

    def _pack_header(self, size: int, max_size: int) -> None:
        _INTERNAL_HDR.pack_into(
            self._page.data, 0, BPlusPageType.INTERNAL, size, max_size
        )

    def _slot_offset(self, index: int) -> int:
        return _INTERNAL_HDR_SIZE + index * _INTERNAL_SLOT_SIZE


def bplus_point_lookup(bpm: BufferPoolManager, root_page_id: int, key: int) -> RID | None:
    """Walk a manually built tree (internal → leaf) and return RID for ``key``."""
    page_id = root_page_id
    while True:
        with bpm.fetch_page_read(page_id) as guard:
            typ = page_type_of(guard.page)
            if typ is BPlusPageType.INTERNAL:
                page_id = BPlusInternalPage(guard.page).lookup(key)
                continue
            if typ is BPlusPageType.LEAF:
                leaf = BPlusLeafPage(guard.page)
                idx = leaf.find_key(key)
                if idx is None:
                    return None
                return leaf.rid_at(idx)
            raise ValueError(f"unknown b+ page type {typ} at page {page_id}")

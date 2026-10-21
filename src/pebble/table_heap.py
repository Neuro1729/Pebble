"""Table heap: unordered rows as a singly linked chain of slotted pages.

Catalog (step 6) will remember first_page_id / last_page_id by table name.
V1: append inserts; full-page → allocate + link. No updates-in-place API yet.
V2: page guards for pin/unpin (no leaked pins after insert/scan/get).
LATER: MVCC deletes/updates, free-space maps.
"""

from __future__ import annotations

from collections.abc import Iterator

from pebble.buffer_pool import BufferPoolManager
from pebble.config import INVALID_PAGE_ID
from pebble.rid import RID
from pebble.schema import Schema
from pebble.slotted_page import SlottedPage
from pebble.tuple import Tuple


class TableHeap:
    def __init__(
        self,
        bpm: BufferPoolManager,
        schema: Schema,
        first_page_id: int,
        last_page_id: int,
    ) -> None:
        if first_page_id == INVALID_PAGE_ID or last_page_id == INVALID_PAGE_ID:
            raise ValueError("table heap requires valid first/last page ids")
        self._bpm = bpm
        self._schema = schema
        self._first_page_id = first_page_id
        self._last_page_id = last_page_id

    @classmethod
    def create(cls, bpm: BufferPoolManager, schema: Schema) -> TableHeap:
        """Allocate and format the first slotted page for a new table."""
        with bpm.new_page_write() as guard:
            page_id = guard.page_id
            SlottedPage.initialize(guard.page)
        return cls(bpm, schema, first_page_id=page_id, last_page_id=page_id)

    @property
    def schema(self) -> Schema:
        return self._schema

    @property
    def first_page_id(self) -> int:
        return self._first_page_id

    @property
    def last_page_id(self) -> int:
        return self._last_page_id

    def insert_tuple(self, tuple_: Tuple) -> RID:
        """Append a tuple; allocate and link a new page if the last page is full."""
        data = tuple_.to_bytes(self._schema)
        with self._bpm.fetch_page_write(self._last_page_id) as guard:
            slotted = SlottedPage(guard.page)
            try:
                slot_num = slotted.insert_tuple(data)
            except MemoryError:
                guard.mark_clean()
                overflow = True
            else:
                overflow = False
                rid = RID(page_id=self._last_page_id, slot_num=slot_num)

        if overflow:
            return self._insert_on_new_page(data)
        return rid

    def get_tuple(self, rid: RID) -> Tuple:
        with self._bpm.fetch_page_read(rid.page_id) as guard:
            data = SlottedPage(guard.page).get_tuple(rid.slot_num)
            return Tuple.from_bytes(self._schema, data)

    def scan(self) -> Iterator[tuple[RID, Tuple]]:
        """Yield (RID, Tuple) for every non-deleted slot in page-chain order."""
        page_id = self._first_page_id
        while page_id != INVALID_PAGE_ID:
            with self._bpm.fetch_page_read(page_id) as guard:
                slotted = SlottedPage(guard.page)
                next_page_id = slotted.get_next_page_id()
                slots = list(slotted.iter_slots())

            for slot_num, data in slots:
                yield RID(page_id=page_id, slot_num=slot_num), Tuple.from_bytes(
                    self._schema, data
                )
            page_id = next_page_id

    def _insert_on_new_page(self, data: bytes) -> RID:
        with self._bpm.new_page_write() as new_guard:
            new_page_id = new_guard.page_id
            SlottedPage.initialize(new_guard.page)

            with self._bpm.fetch_page_write(self._last_page_id) as old_guard:
                SlottedPage(old_guard.page).set_next_page_id(new_page_id)

            slotted = SlottedPage(new_guard.page)
            try:
                slot_num = slotted.insert_tuple(data)
            except MemoryError as exc:
                raise ValueError("tuple larger than an empty page") from exc

        self._last_page_id = new_page_id
        return RID(page_id=new_page_id, slot_num=slot_num)

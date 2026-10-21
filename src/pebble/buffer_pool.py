"""Buffer pool: cache of pages in memory with pin/dirty + ARC eviction.

V1: sync DiskManager I/O, FIFO replacer.
V2 step 1: page guards (fetch_page_read / fetch_page_write / new_page_write).
V2 step 2: ArcReplacer (BusTub P1-style).
V2 step 3: DiskScheduler (all page I/O via background worker).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pebble.arc_replacer import ArcReplacer
from pebble.config import INVALID_PAGE_ID
from pebble.disk_manager import DiskManager
from pebble.disk_scheduler import DiskScheduler
from pebble.page import Page
from pebble.page_guard import ReadPageGuard, WritePageGuard


@dataclass
class Frame:
    page: Page = field(default_factory=Page)
    pin_count: int = 0
    is_dirty: bool = False


class BufferPoolManager:
    def __init__(self, pool_size: int, disk_manager: DiskManager) -> None:
        if pool_size <= 0:
            raise ValueError("pool_size must be positive")
        self._pool_size = pool_size
        self._scheduler = DiskScheduler(disk_manager)
        self._frames = [Frame() for _ in range(pool_size)]
        self._page_table: dict[int, int] = {}  # page_id -> frame_id
        self._free_list = list(range(pool_size))
        self._replacer = ArcReplacer(pool_size)
        self._closed = False

    @property
    def pool_size(self) -> int:
        return self._pool_size

    def close(self) -> None:
        """Stop the disk scheduler worker (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._scheduler.close()

    def __enter__(self) -> BufferPoolManager:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def new_page(self) -> Page:
        """Allocate a new disk page, load it into a frame, return pinned Page."""
        frame_id = self._get_frame()
        page_id = self._scheduler.allocate_page()
        frame = self._frames[frame_id]
        frame.page = Page(page_id=page_id)
        frame.pin_count = 1
        frame.is_dirty = False
        self._page_table[page_id] = frame_id
        self._replacer.record_access(frame_id, page_id)
        self._replacer.pin(frame_id)
        return frame.page

    def new_page_write(self) -> WritePageGuard:
        """Allocate a new page and return a write guard (caller must drop / ``with``)."""
        return WritePageGuard(self, self.new_page())

    def fetch_page(self, page_id: int) -> Page:
        """Return a pinned Page for page_id (load from disk on miss)."""
        if page_id < 0:
            raise ValueError(f"invalid page_id: {page_id}")

        if page_id in self._page_table:
            frame_id = self._page_table[page_id]
            frame = self._frames[frame_id]
            frame.pin_count += 1
            self._replacer.record_access(frame_id, page_id)
            self._replacer.pin(frame_id)
            return frame.page

        frame_id = self._get_frame()
        page = self._scheduler.read_page(page_id)
        frame = self._frames[frame_id]
        frame.page = page
        frame.pin_count = 1
        frame.is_dirty = False
        self._page_table[page_id] = frame_id
        self._replacer.record_access(frame_id, page_id)
        self._replacer.pin(frame_id)
        return frame.page

    def fetch_page_read(self, page_id: int) -> ReadPageGuard:
        """Fetch and pin for read; unpin on guard drop."""
        return ReadPageGuard(self, self.fetch_page(page_id))

    def fetch_page_write(self, page_id: int) -> WritePageGuard:
        """Fetch and pin for write; unpin dirty on guard drop."""
        return WritePageGuard(self, self.fetch_page(page_id))

    def get_pin_count(self, page_id: int) -> int:
        if page_id not in self._page_table:
            return 0
        frame_id = self._page_table[page_id]
        return self._frames[frame_id].pin_count

    def unpin_page(self, page_id: int, is_dirty: bool) -> None:
        if page_id not in self._page_table:
            raise KeyError(f"page_id {page_id} is not in the buffer pool")
        frame_id = self._page_table[page_id]
        frame = self._frames[frame_id]
        if frame.pin_count <= 0:
            raise RuntimeError(f"page_id {page_id} pin_count is already 0")
        if is_dirty:
            frame.is_dirty = True
        frame.pin_count -= 1
        if frame.pin_count == 0:
            self._replacer.unpin(frame_id)

    def flush_page(self, page_id: int) -> None:
        if page_id not in self._page_table:
            raise KeyError(f"page_id {page_id} is not in the buffer pool")
        frame_id = self._page_table[page_id]
        frame = self._frames[frame_id]
        self._scheduler.write_page(frame.page)
        frame.is_dirty = False

    def flush_all_pages(self) -> None:
        for page_id in list(self._page_table.keys()):
            self.flush_page(page_id)

    def _get_frame(self) -> int:
        if self._free_list:
            return self._free_list.pop()

        frame_id = self._replacer.victim()
        if frame_id is None:
            raise RuntimeError("buffer pool has no evictable frames (all pinned)")

        frame = self._frames[frame_id]
        old_page_id = frame.page.page_id
        if old_page_id != INVALID_PAGE_ID and old_page_id in self._page_table:
            if frame.is_dirty:
                self._scheduler.write_page(frame.page)
            del self._page_table[old_page_id]

        frame.page = Page()
        frame.pin_count = 0
        frame.is_dirty = False
        return frame_id

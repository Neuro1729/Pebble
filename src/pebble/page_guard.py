"""RAII page guards: pin on acquire, unpin on drop / ``with`` exit.

V2 step 1 (BusTub-style). Single-threaded: no RW latches yet.
LATER: shared/exclusive page latches for concurrent B+Tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pebble.page import Page

if TYPE_CHECKING:
    from pebble.buffer_pool import BufferPoolManager


class ReadPageGuard:
    """Pinned page for read; unpins with ``is_dirty=False`` on drop."""

    def __init__(self, bpm: BufferPoolManager, page: Page) -> None:
        self._bpm = bpm
        self._page = page
        self._dropped = False

    @property
    def page(self) -> Page:
        self._ensure_held()
        return self._page

    @property
    def page_id(self) -> int:
        return self.page.page_id

    def drop(self) -> None:
        if self._dropped:
            return
        self._bpm.unpin_page(self._page.page_id, is_dirty=False)
        self._dropped = True

    def __enter__(self) -> ReadPageGuard:
        self._ensure_held()
        return self

    def __exit__(self, *args: object) -> None:
        self.drop()

    def _ensure_held(self) -> None:
        if self._dropped:
            raise RuntimeError("ReadPageGuard already dropped")


class WritePageGuard:
    """Pinned page for mutation; unpins with ``is_dirty=True`` on drop."""

    def __init__(self, bpm: BufferPoolManager, page: Page) -> None:
        self._bpm = bpm
        self._page = page
        self._dropped = False
        self._dirty = True

    @property
    def page(self) -> Page:
        self._ensure_held()
        return self._page

    @property
    def page_id(self) -> int:
        return self.page.page_id

    def mark_clean(self) -> None:
        """Unpin without marking dirty (e.g. insert failed, no bytes changed)."""
        self._ensure_held()
        self._dirty = False

    def drop(self) -> None:
        if self._dropped:
            return
        self._bpm.unpin_page(self._page.page_id, is_dirty=self._dirty)
        self._dropped = True

    def __enter__(self) -> WritePageGuard:
        self._ensure_held()
        return self

    def __exit__(self, *args: object) -> None:
        self.drop()

    def _ensure_held(self) -> None:
        if self._dropped:
            raise RuntimeError("WritePageGuard already dropped")

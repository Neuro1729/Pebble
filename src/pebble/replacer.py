"""FIFO frame replacer for the buffer pool.

V1 used this. V2 step 2: BufferPoolManager uses ArcReplacer instead.
Kept for comparison / tests.
"""

from __future__ import annotations

from collections import deque


class FifoReplacer:
    def __init__(self) -> None:
        # frame_ids that are currently evictable (pin_count == 0), oldest at left.
        self._queue: deque[int] = deque()
        self._in_queue: set[int] = set()

    def pin(self, frame_id: int) -> None:
        """Frame is in use; must not be a victim."""
        if frame_id in self._in_queue:
            self._queue.remove(frame_id)
            self._in_queue.remove(frame_id)

    def unpin(self, frame_id: int) -> None:
        """Frame became unused; make it evictable (FIFO order)."""
        if frame_id not in self._in_queue:
            self._queue.append(frame_id)
            self._in_queue.add(frame_id)

    def victim(self) -> int | None:
        """Return oldest evictable frame_id, or None if none."""
        if not self._queue:
            return None
        frame_id = self._queue.popleft()
        self._in_queue.remove(frame_id)
        return frame_id

    def remove(self, frame_id: int) -> None:
        """Drop frame from replacer (e.g. page deleted / frame cleared)."""
        if frame_id in self._in_queue:
            self._queue.remove(frame_id)
            self._in_queue.remove(frame_id)

    def size(self) -> int:
        return len(self._queue)

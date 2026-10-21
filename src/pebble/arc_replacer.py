"""ARC (Adaptive Replacement Cache) frame replacer (BusTub P1 variant).

List orientation (pages closer to the MRU/MFU boundary ``!`` are fresher):

  [<- mru_ghost -][<- mru -] ! [- mfu ->][-> mfu_ghost ->]

- MRU / MRU-ghost: left = LRU (evict / kill), right = fresh (append)
- MFU / MFU-ghost: left = fresh (appendleft), right = LRU (evict / kill)

Ghost lists track ``page_id`` after eviction. Target ``p`` adapts on ghost hits.

API: ``record_access`` + ``pin`` / ``unpin`` / ``victim`` (FifoReplacer-shaped).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum, auto


class _AliveStatus(Enum):
    MRU = auto()
    MFU = auto()


@dataclass
class _AliveEntry:
    page_id: int
    frame_id: int
    evictable: bool
    status: _AliveStatus


class ArcReplacer:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._p = 0  # target |mru|
        self._evictable_count = 0

        self._mru: deque[int] = deque()  # frame_ids; left=LRU, right=fresh
        self._mfu: deque[int] = deque()  # frame_ids; left=fresh, right=LRU
        self._mru_ghost: deque[int] = deque()  # page_ids; left=LRU
        self._mfu_ghost: deque[int] = deque()  # page_ids; right=LRU

        self._alive: dict[int, _AliveEntry] = {}
        self._ghost: dict[int, str] = {}  # page_id -> "mru" | "mfu"

    def size(self) -> int:
        return self._evictable_count

    def record_access(self, frame_id: int, page_id: int) -> None:
        """BusTub RecordAccess cases 1–4."""
        if frame_id in self._alive:
            # Case 1: hit in MRU/MFU → front of MFU
            self._move_alive_to_mfu_front(frame_id)
            self._alive[frame_id].page_id = page_id
            return

        if page_id in self._ghost:
            which = self._ghost[page_id]
            b1 = len(self._mru_ghost)
            b2 = len(self._mfu_ghost)
            if which == "mru":
                # Case 2: MRU ghost hit → grow p, place at MFU front
                delta = 1 if b1 >= b2 else max(b2 // b1, 1)
                self._p = min(self._capacity, self._p + delta)
            else:
                # Case 3: MFU ghost hit → shrink p, place at MFU front
                delta = 1 if b2 >= b1 else max(b1 // b2, 1)
                self._p = max(0, self._p - delta)
            self._remove_ghost(page_id)
            self._add_alive(frame_id, page_id, _AliveStatus.MFU, evictable=False)
            return

        # Case 4: complete miss → front of MRU
        self._case4_miss(frame_id, page_id)

    def pin(self, frame_id: int) -> None:
        self._set_evictable(frame_id, False)

    def unpin(self, frame_id: int) -> None:
        self._set_evictable(frame_id, True)

    def victim(self) -> int | None:
        """Evict into the matching ghost list; None if nothing evictable."""
        prefer_mru = len(self._mru) >= self._p
        if prefer_mru:
            frame_id = self._evict_from_mru()
            if frame_id is None:
                frame_id = self._evict_from_mfu()
        else:
            frame_id = self._evict_from_mfu()
            if frame_id is None:
                frame_id = self._evict_from_mru()
        return frame_id

    def remove(self, frame_id: int) -> None:
        """Drop alive frame without creating a ghost (unlike victim)."""
        entry = self._alive.get(frame_id)
        if entry is None:
            return
        if not entry.evictable:
            raise RuntimeError(f"cannot remove non-evictable frame {frame_id}")
        self._unlink_alive(frame_id)
        self._evictable_count -= 1
        del self._alive[frame_id]

    def _set_evictable(self, frame_id: int, evictable: bool) -> None:
        entry = self._alive.get(frame_id)
        if entry is None or entry.evictable == evictable:
            return
        entry.evictable = evictable
        self._evictable_count += 1 if evictable else -1

    def _case4_miss(self, frame_id: int, page_id: int) -> None:
        mru_side = len(self._mru) + len(self._mru_ghost)
        if mru_side == self._capacity:
            # 4a: kill LRU of MRU ghost
            if self._mru_ghost:
                self._remove_ghost(self._mru_ghost[0])
            self._add_alive(frame_id, page_id, _AliveStatus.MRU, evictable=False)
            return

        total = (
            len(self._mru)
            + len(self._mfu)
            + len(self._mru_ghost)
            + len(self._mfu_ghost)
        )
        if total == 2 * self._capacity and self._mfu_ghost:
            # 4b: directory full → kill LRU of MFU ghost (right end)
            self._remove_ghost(self._mfu_ghost[-1])
        self._add_alive(frame_id, page_id, _AliveStatus.MRU, evictable=False)

    def _add_alive(
        self,
        frame_id: int,
        page_id: int,
        status: _AliveStatus,
        *,
        evictable: bool,
    ) -> None:
        if frame_id in self._alive:
            raise RuntimeError(f"frame {frame_id} already alive in ARC")
        self._alive[frame_id] = _AliveEntry(page_id, frame_id, evictable, status)
        if status is _AliveStatus.MRU:
            self._mru.append(frame_id)  # fresh at right
        else:
            self._mfu.appendleft(frame_id)  # fresh at left
        if evictable:
            self._evictable_count += 1

    def _move_alive_to_mfu_front(self, frame_id: int) -> None:
        entry = self._alive[frame_id]
        self._unlink_alive(frame_id)
        entry.status = _AliveStatus.MFU
        self._mfu.appendleft(frame_id)

    def _unlink_alive(self, frame_id: int) -> None:
        entry = self._alive[frame_id]
        if entry.status is _AliveStatus.MRU:
            self._mru.remove(frame_id)
        else:
            self._mfu.remove(frame_id)

    def _remove_ghost(self, page_id: int) -> None:
        which = self._ghost.pop(page_id)
        if which == "mru":
            self._mru_ghost.remove(page_id)
        else:
            self._mfu_ghost.remove(page_id)

    def _evict_from_mru(self) -> int | None:
        for frame_id in self._mru:  # LRU → fresh
            entry = self._alive[frame_id]
            if not entry.evictable:
                continue
            self._mru.remove(frame_id)
            del self._alive[frame_id]
            self._evictable_count -= 1
            self._mru_ghost.append(entry.page_id)  # fresh ghost at right
            self._ghost[entry.page_id] = "mru"
            return frame_id
        return None

    def _evict_from_mfu(self) -> int | None:
        for frame_id in reversed(self._mfu):  # LRU → fresh
            entry = self._alive[frame_id]
            if not entry.evictable:
                continue
            self._mfu.remove(frame_id)
            del self._alive[frame_id]
            self._evictable_count -= 1
            self._mfu_ghost.appendleft(entry.page_id)  # fresh ghost at left
            self._ghost[entry.page_id] = "mfu"
            return frame_id
        return None

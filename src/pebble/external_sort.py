"""V3 Person B — sort tuples by key columns (in-memory first; external runs if large).

PREREQUISITES (must already work):
  - pebble.tuple.Tuple
  - pebble.schema.Schema (optional; mostly need column indexes)
  - pebble.buffer_pool.BufferPoolManager + page_guard  (only if you spill runs to pages)
  - pebble.config.PAGE_SIZE

USED BY:
  - pebble.sort_executor.SortExecutor
  - (optional) sort-based aggregation later
  - tests/test_external_sort.py

NOT IN THIS FILE:
  - SQL ORDER BY parsing (database.py, Person B patch)
  - Volcano Executor wrapper (sort_executor.py)

PSEUDOCODE
==========
def tuple_sort_key(tup, key_indexes, descending_flags) -> tuple:
    # build comparable key; negate / reverse for DESC if needed

def sort_in_memory(tuples, key_indexes, descending=None) -> list[Tuple]:
    # return sorted(tuples, key=...)

class ExternalSorter:
    def __init__(self, bpm=None, memory_tuple_limit=1024):
        # if len(input) <= limit: pure in-memory sort
        # else: write sorted runs to temp pages / temp file, then k-way merge

    def sort(self, tuples_iter, key_indexes, descending=None) -> Iterator[Tuple]:
        # 1. fill buffer until memory_tuple_limit
        # 2. sort buffer → write_run()
        # 3. repeat until input exhausted
        # 4. if one run: yield from that run
        # 5. else: k-way merge with heapq.merge (decorate with sort keys)

    def write_run(self, sorted_tuples) -> RunHandle:
        # STRETCH: serialize tuples into slotted pages via BPM
        # V3 MVP OK: keep runs as list[list[Tuple]] in memory if spill is hard
        #   (still structure the API as if runs were external)

DONE WHEN:
  - Asc / desc multi-key sort matches Python sorted()
  - Input larger than memory_tuple_limit still returns fully sorted stream
  - Stable enough for tests (document stability)
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Iterator

from pebble.tuple import Tuple


def tuple_sort_key(
    tup: Tuple,
    key_indexes: list[int],
    descending: list[bool] | None = None,
) -> tuple:
    """Comparable key for one tuple."""
    flags = _descending_flags(key_indexes, descending)
    return tuple(
        _Descending(tup.get_value(index)) if reverse else tup.get_value(index)
        for index, reverse in zip(key_indexes, flags)
    )


class _Descending:
    """Reverse ordering for a single comparable value, without negating strings."""

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value

    def __lt__(self, other: _Descending) -> bool:
        return self.value > other.value  # type: ignore[operator]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Descending) and self.value == other.value


def _descending_flags(key_indexes: list[int], descending: list[bool] | None) -> list[bool]:
    if descending is None:
        return [False] * len(key_indexes)
    if len(descending) != len(key_indexes):
        raise ValueError("descending must have one flag per key column")
    return list(descending)


def sort_in_memory(
    tuples: list[Tuple],
    key_indexes: list[int],
    descending: list[bool] | None = None,
) -> list[Tuple]:
    """Sort a list that fits in memory."""
    _descending_flags(key_indexes, descending)
    return sorted(tuples, key=lambda tup: tuple_sort_key(tup, key_indexes, descending))


class ExternalSorter:
    """Sort a stream; spill to runs when over memory_tuple_limit."""

    def __init__(
        self,
        memory_tuple_limit: int = 1024,
        bpm: object | None = None,
    ) -> None:
        if memory_tuple_limit < 1:
            raise ValueError("memory_tuple_limit must be positive")
        self._limit = memory_tuple_limit

    def sort(
        self,
        tuples: Iterable[Tuple],
        key_indexes: list[int],
        descending: list[bool] | None = None,
    ) -> Iterator[Tuple]:
        _descending_flags(key_indexes, descending)
        runs: list[list[Tuple]] = []
        chunk: list[Tuple] = []
        for tup in tuples:
            chunk.append(tup)
            if len(chunk) == self._limit:
                runs.append(sort_in_memory(chunk, key_indexes, descending))
                chunk = []
        if not runs:
            yield from sort_in_memory(chunk, key_indexes, descending)
            return
        if chunk:
            runs.append(sort_in_memory(chunk, key_indexes, descending))

        # Runs are retained in memory in this MVP; merge them in key order.
        heap: list[tuple[tuple, int, int, Tuple]] = []
        for run_no, run in enumerate(runs):
            if run:
                heapq.heappush(
                    heap, (tuple_sort_key(run[0], key_indexes, descending), run_no, 0, run[0])
                )
        while heap:
            _key, run_no, pos, tup = heapq.heappop(heap)
            yield tup
            next_pos = pos + 1
            if next_pos < len(runs[run_no]):
                next_tuple = runs[run_no][next_pos]
                heapq.heappush(
                    heap,
                    (
                        tuple_sort_key(next_tuple, key_indexes, descending),
                        run_no,
                        next_pos,
                        next_tuple,
                    ),
                )

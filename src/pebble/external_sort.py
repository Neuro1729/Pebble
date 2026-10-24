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

from collections.abc import Iterable, Iterator

from pebble.tuple import Tuple


def tuple_sort_key(
    tup: Tuple,
    key_indexes: list[int],
    descending: list[bool] | None = None,
) -> tuple:
    """Comparable key for one tuple."""
    # PSEUDO: extract values; for DESC wrap in a reverse-aware marker or sort twice
    raise NotImplementedError("V3 Person B: implement tuple_sort_key")


def sort_in_memory(
    tuples: list[Tuple],
    key_indexes: list[int],
    descending: list[bool] | None = None,
) -> list[Tuple]:
    """Sort a list that fits in memory."""
    # PSEUDO: return sorted(tuples, key=lambda t: tuple_sort_key(t, key_indexes, descending))
    raise NotImplementedError("V3 Person B: implement sort_in_memory")


class ExternalSorter:
    """Sort a stream; spill to runs when over memory_tuple_limit."""

    def __init__(
        self,
        memory_tuple_limit: int = 1024,
        bpm: object | None = None,
    ) -> None:
        # PSEUDO: store limit; bpm optional for true page spills
        raise NotImplementedError("V3 Person B: implement ExternalSorter.__init__")

    def sort(
        self,
        tuples: Iterable[Tuple],
        key_indexes: list[int],
        descending: list[bool] | None = None,
    ) -> Iterator[Tuple]:
        # PSEUDO: see module docstring
        raise NotImplementedError("V3 Person B: implement ExternalSorter.sort")

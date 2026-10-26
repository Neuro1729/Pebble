"""V3 Person B — SortExecutor: materialize child, sort, then yield.

PREREQUISITES (must already work):
  - pebble.executor.Executor
  - pebble.external_sort.ExternalSorter (or sort_in_memory)
  - pebble.tuple.Tuple

USED BY:
  - database.py ORDER BY planning (Person B)
  - LimitExecutor for Top-N patterns (Sort then Limit)
  - tests/test_sort_limit.py

PSEUDOCODE
==========
class SortExecutor(Executor):
    def __init__(self, child, key_indexes, descending=None, sorter=None):
        ...

    def init(self):
        # child.init(); drain all child tuples into a list / sorter
        # self._sorted = list(ExternalSorter(...).sort(...))
        # self._i = 0

    def next(self):
        # if self._i >= len(self._sorted): return None
        # tup = self._sorted[self._i]; self._i += 1; return tup

DONE WHEN:
  - ORDER BY one/multiple columns matches expected order
  - Empty child → empty output
  - Re-init() re-sorts from child again
"""

from __future__ import annotations

from pebble.executor import Executor
from pebble.external_sort import ExternalSorter
from pebble.tuple import Tuple


class SortExecutor(Executor):
    """Blocking sort operator."""

    def __init__(
        self,
        child: Executor,
        key_indexes: list[int],
        descending: list[bool] | None = None,
    ) -> None:
        if not key_indexes:
            raise ValueError("key_indexes must be non-empty")
        if descending is not None and len(descending) != len(key_indexes):
            raise ValueError("descending must have one flag per key column")
        self._child = child
        self._key_indexes = list(key_indexes)
        self._descending = None if descending is None else list(descending)
        self._sorter = ExternalSorter()
        self._rows: list[Tuple] = []
        self._index = 0

    def init(self) -> None:
        self._child.init()
        self._rows = list(self._sorter.sort(iter(self._child_rows()), self._key_indexes, self._descending))
        self._index = 0

    def _child_rows(self):
        while True:
            tup = self._child.next()
            if tup is None:
                return
            yield tup

    def next(self) -> Tuple | None:
        if self._index >= len(self._rows):
            return None
        tup = self._rows[self._index]
        self._index += 1
        return tup

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
from pebble.tuple import Tuple


class SortExecutor(Executor):
    """Blocking sort operator."""

    def __init__(
        self,
        child: Executor,
        key_indexes: list[int],
        descending: list[bool] | None = None,
    ) -> None:
        raise NotImplementedError("V3 Person B: implement SortExecutor.__init__")

    def init(self) -> None:
        raise NotImplementedError("V3 Person B: implement SortExecutor.init")

    def next(self) -> Tuple | None:
        raise NotImplementedError("V3 Person B: implement SortExecutor.next")

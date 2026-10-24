"""V3 Person B — LimitExecutor: stop after N rows (optional OFFSET).

PREREQUISITES (must already work):
  - pebble.executor.Executor
  - pebble.tuple.Tuple

USED BY:
  - database.py LIMIT planning (Person B)
  - Top-N: SortExecutor → LimitExecutor
  - tests/test_sort_limit.py

PSEUDOCODE
==========
class LimitExecutor(Executor):
    def __init__(self, child, limit: int, offset: int = 0):
        # reject negative limit/offset

    def init(self):
        # child.init()
        # skip `offset` tuples from child
        # self._emitted = 0

    def next(self):
        # if self._emitted >= limit: return None
        # tup = child.next(); if None: return None
        # self._emitted += 1; return tup

DONE WHEN:
  - LIMIT 0 → no rows
  - OFFSET skips correctly
  - Works on top of SortExecutor for Top-N
"""

from __future__ import annotations

from pebble.executor import Executor
from pebble.tuple import Tuple


class LimitExecutor(Executor):
    """Truncating operator: OFFSET then LIMIT."""

    def __init__(self, child: Executor, limit: int, offset: int = 0) -> None:
        raise NotImplementedError("V3 Person B: implement LimitExecutor.__init__")

    def init(self) -> None:
        raise NotImplementedError("V3 Person B: implement LimitExecutor.init")

    def next(self) -> Tuple | None:
        raise NotImplementedError("V3 Person B: implement LimitExecutor.next")

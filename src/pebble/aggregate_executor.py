"""V3 Person B — AggregateExecutor: hash aggregate over child stream.

PREREQUISITES (must already work):
  - pebble.executor.Executor
  - pebble.aggregation.AggregationHash, AggCall, AggOp
  - pebble.tuple.Tuple

USED BY:
  - database.py GROUP BY / SELECT agg planning (Person B)
  - tests/test_aggregation.py

PSEUDOCODE
==========
class AggregateExecutor(Executor):
    def __init__(self, child, group_indexes, agg_calls):
        ...

    def init(self):
        # child.init()
        # agg = AggregationHash(group_indexes, agg_calls)
        # while tup := child.next(): agg.add_tuple(tup)
        # self._out = agg.finalize()
        # self._i = 0

    def next(self):
        # yield from self._out

DONE WHEN:
  - GROUP BY + aggs match hand-checked results
  - No GROUP BY (empty group_indexes) → single output row of global aggs
  - Empty child: zero rows if GROUP BY present; one row of zero-ish aggs if global
    (document the chosen SQL-like behavior in the class docstring)
"""

from __future__ import annotations

from pebble.aggregation import AggCall
from pebble.executor import Executor
from pebble.tuple import Tuple


class AggregateExecutor(Executor):
    """Blocking hash aggregate. Empty global input yields one SQL-like row."""

    def __init__(
        self,
        child: Executor,
        group_indexes: list[int],
        agg_calls: list[AggCall],
    ) -> None:
        self._child = child
        self._group_indexes = list(group_indexes)
        self._agg_calls = list(agg_calls)
        self._rows: list[Tuple] = []
        self._index = 0

    def init(self) -> None:
        from pebble.aggregation import AggregationHash

        self._child.init()
        aggregation = AggregationHash(self._group_indexes, self._agg_calls)
        while (tup := self._child.next()) is not None:
            aggregation.add_tuple(tup)
        self._rows = aggregation.finalize()
        self._index = 0

    def next(self) -> Tuple | None:
        if self._index >= len(self._rows):
            return None
        tup = self._rows[self._index]
        self._index += 1
        return tup

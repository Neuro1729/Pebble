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
    """Blocking hash-aggregation operator."""

    def __init__(
        self,
        child: Executor,
        group_indexes: list[int],
        agg_calls: list[AggCall],
    ) -> None:
        raise NotImplementedError("V3 Person B: implement AggregateExecutor.__init__")

    def init(self) -> None:
        raise NotImplementedError("V3 Person B: implement AggregateExecutor.init")

    def next(self) -> Tuple | None:
        raise NotImplementedError("V3 Person B: implement AggregateExecutor.next")

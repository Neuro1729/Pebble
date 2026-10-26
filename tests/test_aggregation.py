from __future__ import annotations

from pebble.aggregation import AggCall, AggOp, AggregationHash
from pebble.aggregate_executor import AggregateExecutor
from pebble.executor import Executor, poll
from pebble.tuple import Tuple


class Rows(Executor):
    def __init__(self, rows): self.rows, self.i = rows, 0
    def init(self): self.i = 0
    def next(self):
        if self.i >= len(self.rows): return None
        row = self.rows[self.i]; self.i += 1; return row


def test_count_star_global() -> None:
    out = AggregateExecutor(Rows([Tuple([1]), Tuple([2]), Tuple([3])]), [], [AggCall(AggOp.COUNT, None)])
    assert [r.values for r in poll(out)] == [[3]]


def test_group_by_count() -> None:
    agg = AggregationHash([0], [AggCall(AggOp.COUNT, None)])
    for row in [Tuple(["a"]), Tuple(["b"]), Tuple(["a"])]: agg.add_tuple(row)
    assert sorted((r.values for r in agg.finalize())) == [["a", 2], ["b", 1]]


def test_sum_min_max_avg() -> None:
    agg = AggregationHash([], [AggCall(AggOp.SUM, 0), AggCall(AggOp.MIN, 0), AggCall(AggOp.MAX, 0), AggCall(AggOp.AVG, 0)])
    for value in [2, 4, 6]: agg.add_tuple(Tuple([value]))
    assert agg.finalize()[0].values == [12, 2, 6, 4.0]

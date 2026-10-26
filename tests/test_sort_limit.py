from __future__ import annotations

from pebble.executor import Executor, poll
from pebble.limit_executor import LimitExecutor
from pebble.sort_executor import SortExecutor
from pebble.tuple import Tuple


class Rows(Executor):
    def __init__(self, rows): self.rows, self.i = rows, 0
    def init(self): self.i = 0
    def next(self):
        if self.i >= len(self.rows): return None
        row = self.rows[self.i]; self.i += 1; return row


def test_sort_executor_order() -> None:
    assert [r.values for r in poll(SortExecutor(Rows([Tuple([2]), Tuple([1])]), [0]))] == [[1], [2]]


def test_limit_and_offset() -> None:
    rows = [Tuple([i]) for i in range(5)]
    assert [r.values for r in poll(LimitExecutor(Rows(rows), 2, 2))] == [[2], [3]]
    assert poll(LimitExecutor(Rows(rows), 0)) == []


def test_top_n_sort_then_limit() -> None:
    rows = [Tuple([3]), Tuple([1]), Tuple([2])]
    assert [r.values for r in poll(LimitExecutor(SortExecutor(Rows(rows), [0]), 2))] == [[1], [2]]

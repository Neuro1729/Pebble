"""Volcano-style executors: Init / Next pull model.

V1: SeqScan, Insert, Filter, Project, NestedLoopJoin.
LATER: hash join, external sort, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator

from pebble.catalog import TableInfo
from pebble.rid import RID
from pebble.tuple import Tuple


class Executor(ABC):
    """Base operator: call init(), then next() until None."""

    @abstractmethod
    def init(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def next(self) -> Tuple | None:
        """Return the next output tuple, or None when exhausted."""
        raise NotImplementedError


def poll(executor: Executor) -> list[Tuple]:
    """Run an executor to completion and collect all tuples."""
    executor.init()
    out: list[Tuple] = []
    while True:
        tup = executor.next()
        if tup is None:
            break
        out.append(tup)
    return out


class SeqScanExecutor(Executor):
    """Full table scan: yield every tuple from a table heap."""

    def __init__(self, table: TableInfo) -> None:
        self._table = table
        self._iter: Iterator[tuple[RID, Tuple]] | None = None

    def init(self) -> None:
        self._iter = self._table.heap.scan()

    def next(self) -> Tuple | None:
        if self._iter is None:
            raise RuntimeError("SeqScanExecutor.next called before init")
        try:
            _rid, tup = next(self._iter)
        except StopIteration:
            return None
        return tup


class InsertExecutor(Executor):
    """Insert a fixed list of tuples into a table; yield each inserted row.

    V1: values provided up front (no child producer yet).
    LATER: optional child executor that produces rows to insert.
    """

    def __init__(self, table: TableInfo, tuples: list[Tuple]) -> None:
        self._table = table
        self._tuples = list(tuples)
        self._index = 0

    def init(self) -> None:
        self._index = 0

    def next(self) -> Tuple | None:
        if self._index >= len(self._tuples):
            return None
        tup = self._tuples[self._index]
        self._index += 1
        self._table.heap.insert_tuple(tup)
        return tup


class FilterExecutor(Executor):
    """WHERE: pull from child, keep tuples where predicate is True."""

    def __init__(self, child: Executor, predicate: Callable[[Tuple], bool]) -> None:
        self._child = child
        self._predicate = predicate

    def init(self) -> None:
        self._child.init()

    def next(self) -> Tuple | None:
        while True:
            tup = self._child.next()
            if tup is None:
                return None
            if self._predicate(tup):
                return tup


class ProjectExecutor(Executor):
    """SELECT columns: pull from child, emit a tuple with only chosen column indexes."""

    def __init__(self, child: Executor, column_indexes: list[int]) -> None:
        if not column_indexes:
            raise ValueError("column_indexes must be non-empty")
        self._child = child
        self._column_indexes = list(column_indexes)

    def init(self) -> None:
        self._child.init()

    def next(self) -> Tuple | None:
        tup = self._child.next()
        if tup is None:
            return None
        values = [tup.get_value(i) for i in self._column_indexes]
        return Tuple(values=values)


class NestedLoopJoinExecutor(Executor):
    """Nested-loop join: for each left tuple, rescan right and emit matches.

    Output tuple = left values concatenated with right values.
    LATER: hash join for equality predicates.
    """

    def __init__(
        self,
        left: Executor,
        right: Executor,
        predicate: Callable[[Tuple, Tuple], bool],
    ) -> None:
        self._left = left
        self._right = right
        self._predicate = predicate
        self._left_tuple: Tuple | None = None

    def init(self) -> None:
        self._left.init()
        self._left_tuple = None

    def next(self) -> Tuple | None:
        while True:
            if self._left_tuple is None:
                self._left_tuple = self._left.next()
                if self._left_tuple is None:
                    return None
                # Restart right side for this left tuple.
                self._right.init()

            right_tuple = self._right.next()
            if right_tuple is None:
                self._left_tuple = None
                continue

            if self._predicate(self._left_tuple, right_tuple):
                return Tuple(
                    values=list(self._left_tuple.values) + list(right_tuple.values)
                )

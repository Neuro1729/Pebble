"""Volcano-style executors: Init / Next pull model.

V1: SeqScan + Insert only.
LATER: Filter, Project, NestedLoopJoin, hash join, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

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

"""V3 Person B — aggregation state helpers (COUNT / SUM / MIN / MAX / AVG).

PREREQUISITES (must already work):
  - pebble.tuple.Tuple
  - pebble.types.TypeId, Value
  - Optional: pebble.hash_table.SimpleHashTable (Person A). If A1 not ready,
    use a plain dict[HashableKey, AggState] here and swap later.

USED BY:
  - pebble.aggregate_executor.AggregateExecutor
  - tests/test_aggregation.py

NOT IN THIS FILE:
  - Volcano Executor (aggregate_executor.py)
  - SQL parsing of GROUP BY (database.py)

PSEUDOCODE
==========
class AggOp(Enum):
    COUNT, SUM, MIN, MAX, AVG

@dataclass
class AggCall:
    op: AggOp
    child_index: int | None   # None for COUNT(*) 

@dataclass
class AggState:
    # per-group mutable state for one AggCall
    count: int = 0
    sum: int | float = 0
    min_v / max_v: ...

    def update(self, value): ...
    def finalize(self) -> Value: ...

def make_group_key(tup, group_indexes) -> HashableKey:
    # same idea as make_join_key

class AggregationHash:
    def __init__(self, group_indexes, agg_calls: list[AggCall]):
        self._groups = {}  # key → list[AggState] aligned with agg_calls

    def add_tuple(self, tup):
        # key = make_group_key(...)
        # create states if new group; update each AggState from tup

    def finalize(self) -> list[Tuple]:
        # for each group: output = group_key_values + finalized aggs
        # (define column order clearly for Project / schema)

DONE WHEN:
  - COUNT(*) / COUNT(col), SUM, MIN, MAX, AVG correct on ints
  - Empty input → no groups (or one group for global agg without GROUP BY — pick & document)
  - Multiple agg calls in one pass work
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Hashable

from pebble.tuple import Tuple
from pebble.types import Value

HashableKey = Hashable


class AggOp(Enum):
    COUNT = auto()
    SUM = auto()
    MIN = auto()
    MAX = auto()
    AVG = auto()


@dataclass(frozen=True)
class AggCall:
    """One aggregate in the SELECT list."""

    op: AggOp
    child_index: int | None  # None means COUNT(*); else column index in child tuple


@dataclass
class AggState:
    """Mutable per-group state for a single AggCall."""

    def update(self, value: Value | None) -> None:
        raise NotImplementedError("V3 Person B: implement AggState.update")

    def finalize(self) -> Value:
        raise NotImplementedError("V3 Person B: implement AggState.finalize")


def make_group_key(tup: Tuple, group_indexes: list[int]) -> HashableKey:
    """Hashable GROUP BY key."""
    # PSEUDO: empty group_indexes → a constant key (global aggregation)
    raise NotImplementedError("V3 Person B: implement make_group_key")


class AggregationHash:
    """Hash-based grouping: one pass over child tuples."""

    def __init__(self, group_indexes: list[int], agg_calls: list[AggCall]) -> None:
        raise NotImplementedError("V3 Person B: implement AggregationHash.__init__")

    def add_tuple(self, tup: Tuple) -> None:
        raise NotImplementedError("V3 Person B: implement AggregationHash.add_tuple")

    def finalize(self) -> list[Tuple]:
        """Return one output tuple per group: group cols + agg results."""
        raise NotImplementedError("V3 Person B: implement AggregationHash.finalize")

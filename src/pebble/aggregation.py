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

    op: AggOp
    count: int = 0
    total: int | float = 0
    min_value: Value | None = None
    max_value: Value | None = None

    def update(self, value: Value | None) -> None:
        if self.op is AggOp.COUNT:
            if value is not None:
                self.count += 1
            return
        if value is None:
            return
        if self.op in (AggOp.SUM, AggOp.AVG):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"{self.op.name} requires numeric values")
            self.total += value
        if self.op is AggOp.MIN:
            self.min_value = value if self.min_value is None else min(self.min_value, value)  # type: ignore[type-var]
        elif self.op is AggOp.MAX:
            self.max_value = value if self.max_value is None else max(self.max_value, value)  # type: ignore[type-var]
        self.count += 1

    def finalize(self) -> Value:
        if self.op is AggOp.COUNT:
            return self.count
        if self.op is AggOp.SUM:
            return self.total  # type: ignore[return-value]
        if self.op is AggOp.MIN:
            return self.min_value  # type: ignore[return-value]
        if self.op is AggOp.MAX:
            return self.max_value  # type: ignore[return-value]
        if self.op is AggOp.AVG:
            return None if self.count == 0 else self.total / self.count  # type: ignore[return-value]
        raise ValueError(f"unsupported aggregate: {self.op}")


def make_group_key(tup: Tuple, group_indexes: list[int]) -> HashableKey:
    """Hashable GROUP BY key."""
    return tuple(tup.get_value(index) for index in group_indexes)


class AggregationHash:
    """Hash-based grouping: one pass over child tuples."""

    def __init__(self, group_indexes: list[int], agg_calls: list[AggCall]) -> None:
        if not agg_calls:
            raise ValueError("at least one aggregate call is required")
        self._group_indexes = list(group_indexes)
        self._agg_calls = list(agg_calls)
        self._groups: dict[HashableKey, list[AggState]] = {}
        self._group_values: dict[HashableKey, tuple[Value, ...]] = {}
        self._seen = False

    def add_tuple(self, tup: Tuple) -> None:
        self._seen = True
        key = make_group_key(tup, self._group_indexes)
        states = self._groups.setdefault(
            key, [AggState(call.op) for call in self._agg_calls]
        )
        self._group_values.setdefault(
            key, tuple(tup.get_value(i) for i in self._group_indexes)
        )
        for state, call in zip(states, self._agg_calls):
            if call.op is AggOp.COUNT and call.child_index is None:
                value = 1
            else:
                value = (
                    None
                    if call.child_index is None
                    else tup.get_value(call.child_index)
                )
            state.update(value)

    def finalize(self) -> list[Tuple]:
        """Return one output tuple per group: group cols + agg results."""
        if not self._group_indexes and not self._seen and () not in self._groups:
            self._groups[()] = [AggState(call.op) for call in self._agg_calls]
            self._group_values[()] = ()
        return [
            Tuple(
                values=list(self._group_values[key])
                + [state.finalize() for state in states]
            )
            for key, states in self._groups.items()
        ]

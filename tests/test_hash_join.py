"""V3 Person A — tests for HashJoinExecutor.

PREREQUISITES:
  - hash_table.py
  - hash_join.py
  - Existing NestedLoopJoinExecutor (for equivalence checks)

PSEUDOCODE CASES
================
1. Equality join small tables → same multiset of rows as NLJ
2. Empty build (right) → no output
3. Empty probe (left) → no output
4. Multi-column keys
5. Re-init() produces same results again
"""



from __future__ import annotations

from collections import Counter

from pebble.executor import (
    Executor,
    NestedLoopJoinExecutor,
    poll,
)
from pebble.hash_join import HashJoinExecutor
from pebble.tuple import Tuple


class ListExecutor(Executor):
    """Small in-memory executor for tests."""

    def __init__(self, rows: list[list[object]]) -> None:
        self._rows = [Tuple(values=list(row)) for row in rows]
        self._index = 0

    def init(self) -> None:
        self._index = 0

    def next(self) -> Tuple | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row


def values_multiset(rows: list[Tuple]) -> Counter[tuple[object, ...]]:
    return Counter(tuple(row.values) for row in rows)


def test_hash_join_matches_nlj_equality() -> None:
    left_rows = [[1, "a"], [2, "b"], [1, "c"]]
    right_rows = [[1, "x"], [1, "y"], [3, "z"]]

    hash_join = HashJoinExecutor(
        ListExecutor(left_rows),
        ListExecutor(right_rows),
        left_key_indexes=[0],
        right_key_indexes=[0],
    )
    nested_loop = NestedLoopJoinExecutor(
        ListExecutor(left_rows),
        ListExecutor(right_rows),
        predicate=lambda left, right: left.get_value(0) == right.get_value(0),
    )

    assert values_multiset(poll(hash_join)) == values_multiset(poll(nested_loop))


def test_hash_join_empty_right() -> None:
    join = HashJoinExecutor(
        ListExecutor([[1, "a"]]),
        ListExecutor([]),
        left_key_indexes=[0],
        right_key_indexes=[0],
    )

    assert poll(join) == []


def test_hash_join_empty_left() -> None:
    join = HashJoinExecutor(
        ListExecutor([]),
        ListExecutor([[1, "x"]]),
        left_key_indexes=[0],
        right_key_indexes=[0],
    )

    assert poll(join) == []


def test_hash_join_multi_column_keys() -> None:
    join = HashJoinExecutor(
        ListExecutor([[1, "a", "left"], [1, "b", "miss"]]),
        ListExecutor([[1, "a", "right"], [1, "c", "miss"]]),
        left_key_indexes=[0, 1],
        right_key_indexes=[0, 1],
    )

    result = poll(join)

    assert [row.values for row in result] == [[1, "a", "left", 1, "a", "right"]]


def test_hash_join_can_be_reinitialized() -> None:
    join = HashJoinExecutor(
        ListExecutor([[1, "a"]]),
        ListExecutor([[1, "x"]]),
        left_key_indexes=[0],
        right_key_indexes=[0],
    )

    first_result = poll(join)
    second_result = poll(join)

    assert [row.values for row in first_result] == [[1, "a", 1, "x"]]
    assert [row.values for row in second_result] == [[1, "a", 1, "x"]]
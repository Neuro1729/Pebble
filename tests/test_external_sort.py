from __future__ import annotations

from pebble.external_sort import ExternalSorter, sort_in_memory
from pebble.tuple import Tuple


def test_sort_in_memory_asc() -> None:
    rows = [Tuple([3, "c"]), Tuple([1, "a"]), Tuple([2, "b"])]
    assert [r.values for r in sort_in_memory(rows, [0])] == [[1, "a"], [2, "b"], [3, "c"]]


def test_external_sorter_over_limit() -> None:
    rows = [Tuple([1, "b"]), Tuple([1, "c"]), Tuple([2, "a"]), Tuple([1, "a"])]
    got = ExternalSorter(memory_tuple_limit=2).sort(rows, [0, 1], [True, False])
    assert [r.values for r in got] == [[2, "a"], [1, "a"], [1, "b"], [1, "c"]]


def test_empty_input() -> None:
    assert list(ExternalSorter(memory_tuple_limit=1).sort([], [0])) == []

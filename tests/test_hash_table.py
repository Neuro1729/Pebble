"""V3 Person A — tests for SimpleHashTable.

PREREQUISITES: implement src/pebble/hash_table.py first.

PSEUDOCODE CASES
================
1. insert one key → probe returns that tuple
2. insert two tuples same key → probe returns both (order documented)
3. probe missing key → []
4. make_join_key single + multi column
5. clear() then probe → []
6. len() == distinct keys
"""

from __future__ import annotations

from pebble.hash_table import SimpleHashTable, make_join_key
from pebble.tuple import Tuple


def test_insert_and_probe_single() -> None:
    table = SimpleHashTable()
    tup = Tuple(values=[1, "a"])

    table.insert(1, tup)

    assert table.probe(1) == [tup]


def test_probe_returns_all_values_for_key() -> None:
    table = SimpleHashTable()
    first = Tuple(values=[1, "a"])
    second = Tuple(values=[1, "b"])

    table.insert(1, first)
    table.insert(1, second)

    assert table.probe(1) == [first, second]


def test_probe_miss_empty() -> None:
    table = SimpleHashTable()

    assert table.probe(99) == []


def test_make_join_key() -> None:
    tup = Tuple(values=[7, "blue", 42])

    assert make_join_key(tup, [0]) == 7
    assert make_join_key(tup, [1, 2]) == ("blue", 42)


def test_make_join_key_requires_column() -> None:
    tup = Tuple(values=[7])

    try:
        make_join_key(tup, [])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an empty key")


def test_clear() -> None:
    table = SimpleHashTable()
    table.insert(1, Tuple(values=[1, "a"]))

    table.clear()

    assert table.probe(1) == []
    assert len(table) == 0


def test_len_counts_distinct_keys() -> None:
    table = SimpleHashTable()
    table.insert(1, Tuple(values=[1, "a"]))
    table.insert(1, Tuple(values=[1, "b"]))
    table.insert(2, Tuple(values=[2, "c"]))

    assert len(table) == 2
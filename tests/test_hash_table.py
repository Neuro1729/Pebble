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

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person A: unskip when hash_table.py is implemented")


def test_insert_and_probe_single() -> None:
    # from pebble.hash_table import SimpleHashTable
    # from pebble.tuple import Tuple
    # t = SimpleHashTable()
    # tup = Tuple(values=[1, "a"])
    # t.insert(1, tup)
    # assert t.probe(1) == [tup]
    raise NotImplementedError


def test_probe_miss_empty() -> None:
    raise NotImplementedError


def test_make_join_key() -> None:
    raise NotImplementedError


def test_clear() -> None:
    raise NotImplementedError

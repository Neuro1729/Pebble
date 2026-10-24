"""V3 Person A — in-memory hash table for hash join build/probe and (optional) agg.

PREREQUISITES (must already work):
  - pebble.tuple.Tuple
  - pebble.types.Value
  - (optional) pebble.schema.Schema if you want typed key extract helpers

USED BY (implement those after this file):
  - pebble.hash_join.HashJoinExecutor
  - pebble.aggregation (optional: reuse for grouping)
  - tests/test_hash_table.py

NOT IN THIS FILE:
  - Disk-spilling hash table (V3 keeps build side in memory)
  - Concurrent access

PSEUDOCODE
==========
class SimpleHashTable:
    # key: hashable Value or tuple of Values
    # value: list of Tuples that share that key

    def __init__(self):
        self._buckets = {}   # dict[HashableKey, list[Tuple]]

    def insert(self, key, tup):
        # append tup to self._buckets[key] (create list if missing)

    def probe(self, key) -> list[Tuple]:
        # return list(self._buckets.get(key, []))  # copy so callers cannot mutate buckets

    def keys(self):
        # iterate group keys (useful for aggregation)

    def clear(self):
        # empty the table (reuse between queries)

    def __len__(self):
        # number of distinct keys (document this choice in the docstring)

HELPER (recommended):
    def make_join_key(tup: Tuple, key_indexes: list[int]) -> HashableKey:
        # if one col: return tup.get_value(i)
        # if many: return tuple(tup.get_value(i) for i in key_indexes)

DONE WHEN:
  - insert + probe round-trip works for int and multi-column keys
  - probe miss returns empty list
  - clear() resets state
"""

from __future__ import annotations

from typing import Hashable, Iterator

from pebble.tuple import Tuple

HashableKey = Hashable


class SimpleHashTable:
    """In-memory key-to-tuples multimap.

    ``len(table)`` returns the number of distinct keys.
    """

    def __init__(self) -> None:
        self._buckets: dict[HashableKey, list[Tuple]] = {}

    def insert(self, key: HashableKey, tup: Tuple) -> None:
        """Add a tuple under ``key``."""
        self._buckets.setdefault(key, []).append(tup)

    def probe(self, key: HashableKey) -> list[Tuple]:
        """Return a copy of the tuples stored under ``key``."""
        return list(self._buckets.get(key, []))

    def keys(self) -> Iterator[HashableKey]:
        """Iterate over the distinct keys in insertion order."""
        return iter(self._buckets)

    def clear(self) -> None:
        """Remove all keys and tuples."""
        self._buckets.clear()

    def __len__(self) -> int:
        """Return the number of distinct keys."""
        return len(self._buckets)


def make_join_key(tup: Tuple, key_indexes: list[int]) -> HashableKey:
    """Extract a hashable join key from the tuple's selected columns."""
    if not key_indexes:
        raise ValueError("key_indexes must contain at least one column index")

    if len(key_indexes) == 1:
        return tup.get_value(key_indexes[0])

    return tuple(tup.get_value(index) for index in key_indexes)
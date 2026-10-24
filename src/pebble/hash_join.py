"""V3 Person A — HashJoinExecutor (Volcano): build hash table on right, probe with left.

PREREQUISITES (must already work):
  - pebble.executor.Executor  (Init / Next base)
  - pebble.hash_table.SimpleHashTable + make_join_key
  - pebble.tuple.Tuple

USED BY:
  - pebble.optimizer (prefer HashJoin for equality joins)
  - database.py JOIN planning (Person A patch)
  - tests/test_hash_join.py

CONFLICT NOTE:
  - Do not edit NestedLoopJoinExecutor behavior; keep NLJ as fallback.
  - Person B does not own this file.

PSEUDOCODE
==========
class HashJoinExecutor(Executor):
    def __init__(self, left, right, left_key_indexes, right_key_indexes):
        # left / right: child Executors
        # key indexes: which columns form the equality key on each side
        # output = left.values + right.values  (same as NLJ)

    def init(self):
        # 1. right.init(); drain right into SimpleHashTable keyed by right_key
        # 2. left.init()
        # 3. self._current_left = None
        # 4. self._probe_matches = []  # queue of right tuples for current left
        # 5. self._probe_i = 0

    def next(self):
        # loop:
        #   if probe_i < len(probe_matches):
        #       emit concat(current_left, probe_matches[probe_i]); probe_i += 1
        #   else:
        #       current_left = left.next()
        #       if None: return None
        #       probe_matches = table.probe(make_join_key(current_left, left_key_indexes))
        #       probe_i = 0
        #       continue

DONE WHEN:
  - Same equality join results as NestedLoopJoinExecutor (order may differ)
  - Empty left or empty right → no rows
  - init() can be called again (re-build table) for rescan if needed
"""

from __future__ import annotations

from pebble.executor import Executor
from pebble.tuple import Tuple


class HashJoinExecutor(Executor):
    """Equality hash join: build on right, probe with left."""

    def __init__(
        self,
        left: Executor,
        right: Executor,
        left_key_indexes: list[int],
        right_key_indexes: list[int],
    ) -> None:
        # PSEUDO: store children + key indexes; validate non-empty key lists
        raise NotImplementedError("V3 Person A: implement HashJoinExecutor.__init__")

    def init(self) -> None:
        # PSEUDO: build SimpleHashTable from right; then left.init()
        raise NotImplementedError("V3 Person A: implement HashJoinExecutor.init")

    def next(self) -> Tuple | None:
        # PSEUDO: probe-loop as in module docstring
        raise NotImplementedError("V3 Person A: implement HashJoinExecutor.next")

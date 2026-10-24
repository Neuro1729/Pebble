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
from pebble.hash_table import SimpleHashTable, make_join_key
from pebble.tuple import Tuple


class HashJoinExecutor(Executor):
    """Equality hash join; output columns are left values followed by right values."""

    def __init__(
        self,
        left: Executor,
        right: Executor,
        left_key_indexes: list[int],
        right_key_indexes: list[int],
    ) -> None:
        if not left_key_indexes or not right_key_indexes:
            raise ValueError("join key indexes must be non-empty")
        if len(left_key_indexes) != len(right_key_indexes):
            raise ValueError("left and right join keys must have the same length")

        self._left = left
        self._right = right
        self._left_key_indexes = list(left_key_indexes)
        self._right_key_indexes = list(right_key_indexes)

        self._table = SimpleHashTable()
        self._current_left: Tuple | None = None
        self._probe_matches: list[Tuple] = []
        self._probe_index = 0
        self._initialized = False

    def init(self) -> None:
        """Rebuild the right-side hash table and reset the left-side probe."""
        self._table.clear()
        self._current_left = None
        self._probe_matches = []
        self._probe_index = 0

        self._right.init()
        while True:
            right_tuple = self._right.next()
            if right_tuple is None:
                break
            key = make_join_key(right_tuple, self._right_key_indexes)
            self._table.insert(key, right_tuple)

        self._left.init()
        self._initialized = True

    def next(self) -> Tuple | None:
        if not self._initialized:
            raise RuntimeError("HashJoinExecutor.next called before init")

        while True:
            if self._probe_index < len(self._probe_matches):
                right_tuple = self._probe_matches[self._probe_index]
                self._probe_index += 1
                assert self._current_left is not None
                return Tuple(
                    values=list(self._current_left.values) + list(right_tuple.values)
                )

            self._current_left = self._left.next()
            if self._current_left is None:
                return None

            key = make_join_key(self._current_left, self._left_key_indexes)
            self._probe_matches = self._table.probe(key)
            self._probe_index = 0
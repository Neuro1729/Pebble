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

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person A: unskip when hash_join.py is implemented")


def test_hash_join_matches_nlj_equality() -> None:
    # Build two tiny child executors (or SeqScan on temp tables).
    # Compare poll(HashJoin...) multiset to poll(NLJ...).
    raise NotImplementedError


def test_hash_join_empty_right() -> None:
    raise NotImplementedError


def test_hash_join_empty_left() -> None:
    raise NotImplementedError

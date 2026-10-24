"""V3 Person A — tests for rule-based optimizer helpers.

PREREQUISITES: optimizer.py (+ catalog with an index for prefer_index_scan).

PSEUDOCODE CASES
================
1. choose_join_algorithm(is_equality=True) == \"hash\"
2. choose_join_algorithm(is_equality=False) == \"nlj\"
3. prefer_index_scan returns IndexInfo when indexed INTEGER col
4. prefer_index_scan returns None when no index
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person A: unskip when optimizer.py is implemented")


def test_choose_join_hash_for_equality() -> None:
    raise NotImplementedError


def test_prefer_index_scan_hit_and_miss() -> None:
    raise NotImplementedError

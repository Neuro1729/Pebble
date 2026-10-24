"""V3 Person B — tests for SortExecutor + LimitExecutor (incl. Top-N).

PREREQUISITES:
  - sort_executor.py
  - limit_executor.py
  - external_sort.py

PSEUDOCODE CASES
================
1. SortExecutor orders child rows
2. LimitExecutor LIMIT n
3. LimitExecutor OFFSET + LIMIT
4. Sort then Limit → Top-N
5. LIMIT 0 → []
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person B: unskip when sort/limit executors are implemented")


def test_sort_executor_order() -> None:
    raise NotImplementedError


def test_limit_and_offset() -> None:
    raise NotImplementedError


def test_top_n_sort_then_limit() -> None:
    raise NotImplementedError

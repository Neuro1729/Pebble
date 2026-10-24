"""V3 Person B — tests for aggregation helpers + AggregateExecutor.

PREREQUISITES:
  - aggregation.py
  - aggregate_executor.py

PSEUDOCODE CASES
================
1. COUNT(*) global (no GROUP BY) on N rows → 1 row with N
2. GROUP BY col → correct counts per group
3. SUM / MIN / MAX / AVG on integers
4. Empty child with GROUP BY → no rows
5. Multiple AggCalls in one AggregationHash
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person B: unskip when aggregation modules are implemented")


def test_count_star_global() -> None:
    raise NotImplementedError


def test_group_by_count() -> None:
    raise NotImplementedError


def test_sum_min_max_avg() -> None:
    raise NotImplementedError

"""V3 Person B — tests for external_sort.

PREREQUISITES: implement src/pebble/external_sort.py first.

PSEUDOCODE CASES
================
1. sort_in_memory ascending by col 0
2. multi-key + DESC flags
3. ExternalSorter with memory_tuple_limit < n still fully sorted
4. Empty input → empty iterator
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person B: unskip when external_sort.py is implemented")


def test_sort_in_memory_asc() -> None:
    raise NotImplementedError


def test_external_sorter_over_limit() -> None:
    raise NotImplementedError


def test_empty_input() -> None:
    raise NotImplementedError

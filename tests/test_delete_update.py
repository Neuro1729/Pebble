"""V3 Person B — DeleteExecutor + UpdateExecutor tests.

PREREQUISITES:
  - delete_executor.py, update_executor.py
  - undo_log.py
  - Prefer also transaction_manager for abort restore test
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="V3 Person B: unskip when delete/update executors are implemented"
)


def test_delete_removes_from_seqscan() -> None:
    raise NotImplementedError


def test_update_changes_values() -> None:
    raise NotImplementedError


def test_update_maintains_index() -> None:
    raise NotImplementedError


def test_abort_restores_deleted_row() -> None:
    # begin; delete; abort; row visible again
    raise NotImplementedError

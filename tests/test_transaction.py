"""V3 Person A — Transaction + TransactionManager tests.

PREREQUISITES: transaction.py, transaction_manager.py
Optional: wal.py for commit flush behavior.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="V3 Person A: unskip when transaction modules are implemented"
)


def test_begin_commit_assigns_commit_ts() -> None:
    # tm = TransactionManager()
    # txn = tm.begin()
    # assert txn.is_active()
    # tm.commit(txn)
    # assert txn.state == COMMITTED and txn.commit_ts is not None
    raise NotImplementedError


def test_abort_marks_aborted() -> None:
    raise NotImplementedError


def test_double_commit_raises() -> None:
    raise NotImplementedError

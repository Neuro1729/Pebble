"""V3 Person A — Transaction + TransactionManager tests.

PREREQUISITES: transaction.py, transaction_manager.py
Optional: wal.py for commit flush behavior.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="V3 Person A: unskip when transaction modules are implemented"
)


from pebble.transaction import TransactionState
from pebble.transaction_manager import TransactionManager



def test_begin_commit_assigns_commit_ts() -> None:
    manager = TransactionManager()

    first = manager.begin()
    second = manager.begin()

    assert first.is_active()
    manager.commit(first)

    assert first.state is TransactionState.COMMITTED
    assert first.commit_ts is not None

    manager.commit(second)
    assert second.commit_ts is not None
    assert second.commit_ts > first.commit_ts
    assert manager.get(first.txn_id) is None


def test_abort_marks_aborted_and_removes_transaction() -> None:
    manager = TransactionManager()
    txn = manager.begin()

    manager.abort(txn)

    assert txn.state is TransactionState.ABORTED
    assert manager.get(txn.txn_id) is None


def test_double_commit_raises() -> None:
    manager = TransactionManager()
    txn = manager.begin()

    manager.commit(txn)

    with pytest.raises(ValueError, match="not active"):
        manager.commit(txn)


def test_commit_after_abort_raises() -> None:
    manager = TransactionManager()
    txn = manager.begin()

    manager.abort(txn)

    with pytest.raises(ValueError, match="not active"):
        manager.commit(txn)
"""V3 Person B — UndoLog + visibility tests.

PREREQUISITES: undo_log.py
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person B: unskip when undo_log.py is implemented")


def test_record_and_list_for_txn() -> None:
    raise NotImplementedError


def test_visible_snapshot_rules() -> None:
    # alive version with begin_ts <= read_ts visible
    # version with begin_ts > read_ts invisible
    # uncommitted writer invisible to others
    raise NotImplementedError

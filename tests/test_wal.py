"""V3 Person A — WAL LogRecord + LogManager tests.

PREREQUISITES: log_record.py, wal.py
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person A: unskip when wal modules are implemented")


def test_log_record_round_trip() -> None:
    raise NotImplementedError


def test_append_flush_reopen_iter() -> None:
    # append BEGIN/INSERT/COMMIT; flush; reopen LogManager; list(iter_records())
    raise NotImplementedError


def test_analyze_committed_vs_losers() -> None:
    # from pebble.recovery import analyze
    # build fixture records; assert committed/losers sets
    raise NotImplementedError

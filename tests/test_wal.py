"""V3 Person A — WAL LogRecord + LogManager tests.

PREREQUISITES: log_record.py, wal.py
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="V3 Person A: unskip when wal modules are implemented")



from pathlib import Path

from pebble.log_record import LogRecord, LogRecordType
from pebble.recovery import analyze
from pebble.wal import LogManager


def test_log_record_round_trip() -> None:
    record = LogRecord(
        lsn=7,
        txn_id=3,
        prev_lsn=5,
        rtype=LogRecordType.INSERT,
        payload=b"row data",
    )

    assert LogRecord.from_bytes(record.to_bytes()) == record


def test_append_flush_reopen_iter(tmp_path: Path) -> None:
    log_path = tmp_path / "database.wal"
    manager = LogManager(log_path)

    try:
        begin_lsn = manager.append(1, LogRecordType.BEGIN)
        insert_lsn = manager.append(1, LogRecordType.INSERT, b"new row")
        commit_lsn = manager.append(1, LogRecordType.COMMIT)
        manager.flush(commit_lsn)

        assert manager.durable_lsn() == commit_lsn
        assert begin_lsn < insert_lsn < commit_lsn
    finally:
        manager.close()

    reopened = LogManager(log_path)
    try:
        records = list(reopened.iter_records())
    finally:
        reopened.close()

    assert [record.rtype for record in records] == [
        LogRecordType.BEGIN,
        LogRecordType.INSERT,
        LogRecordType.COMMIT,
    ]
    assert [record.lsn for record in records] == [
        begin_lsn,
        insert_lsn,
        commit_lsn,
    ]
    assert records[1].payload == b"new row"
    assert records[1].prev_lsn == begin_lsn
    assert records[2].prev_lsn == insert_lsn


def test_analyze_committed_vs_losers() -> None:
    records = [
        LogRecord(1, 1, 0, LogRecordType.BEGIN),
        LogRecord(2, 2, 0, LogRecordType.BEGIN),
        LogRecord(3, 1, 1, LogRecordType.COMMIT),
        LogRecord(4, 3, 0, LogRecordType.BEGIN),
        LogRecord(5, 2, 2, LogRecordType.ABORT),
    ]

    result = analyze(records)

    assert result.committed == {1}
    assert result.losers == {3}
"""V3 Person A (from V4) — LogManager: append records, flush, durable LSN.

PREREQUISITES:
  - pebble.log_record.LogRecord, LogRecordType
  - pathlib file I/O (or DiskManager-style append file)
  - Optional: BufferPoolManager.flush coordination (WAL-before-data rule)

USED BY:
  - TransactionManager.commit/abort
  - Insert/Delete/Update (log before applying, or same critical section)
  - V4: Recovery uses read path / iterate records
  - tests/test_wal.py

NOT FULLY IN V3 (finish in V4):
  - Crash recovery analysis / redo / undo passes
  - Fuzzy checkpoint with DPT (dirty page table)

PSEUDOCODE
==========
class LogManager:
    def __init__(self, log_path: Path):
        # open append file; self._next_lsn = 1; self._flushed_lsn = 0
        # self._txn_last_lsn: dict[int, int] = {}

    def append(self, txn_id, rtype, payload=b\"\") -> int:
        # prev = self._txn_last_lsn.get(txn_id, 0)
        # rec = LogRecord(lsn=next_lsn++, txn_id, prev, rtype, payload)
        # write rec.to_bytes() to buffer; update _txn_last_lsn
        # return lsn

    def flush(self, up_to_lsn: int | None = None) -> None:
        # fsync log file; set _flushed_lsn

    def durable_lsn(self) -> int:
        # return _flushed_lsn

    def iter_records(self) -> Iterator[LogRecord]:
        # V3: enough to unit-test round-trip; V4 recovery uses this

DONE WHEN:
  - append + flush survives reopen; iter_records returns same sequence
  - COMMIT path can flush up to commit LSN
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pebble.log_record import LogRecord, LogRecordType


class LogManager:
    """Append-only WAL with explicit flush."""

    def __init__(self, log_path: Path | str) -> None:
        raise NotImplementedError("V3 Person A: implement LogManager.__init__")

    def append(
        self,
        txn_id: int,
        rtype: LogRecordType,
        payload: bytes = b"",
    ) -> int:
        """Append a record; return its LSN. Does not fsync by itself."""
        raise NotImplementedError("V3 Person A: implement LogManager.append")

    def flush(self, up_to_lsn: int | None = None) -> None:
        raise NotImplementedError("V3 Person A: implement LogManager.flush")

    def durable_lsn(self) -> int:
        raise NotImplementedError("V3 Person A: implement LogManager.durable_lsn")

    def iter_records(self) -> Iterator[LogRecord]:
        raise NotImplementedError("V3 Person A: implement LogManager.iter_records")

    def close(self) -> None:
        raise NotImplementedError("V3 Person A: implement LogManager.close")

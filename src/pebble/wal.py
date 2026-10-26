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


"""Append-only write-ahead log with explicit flushing."""

from __future__ import annotations

import os
import struct
from collections.abc import Iterator
from pathlib import Path

from pebble.log_record import LogRecord, LogRecordType


# Each serialized record is prefixed by its byte length, allowing records
# with variable-size payloads to be read back from the WAL.
_LENGTH_PREFIX = struct.Struct("<I")


class LogManager:
    """Append-only WAL with explicit flush and per-transaction LSN chains."""

    def __init__(self, log_path: Path | str) -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

        self._txn_last_lsn: dict[int, int] = {}
        records = list(self.iter_records())
        self._next_lsn = records[-1].lsn + 1 if records else 1
        self._flushed_lsn = records[-1].lsn if records else 0
        self._file = self._path.open("ab")

        for record in records:
            self._txn_last_lsn[record.txn_id] = record.lsn

    def append(
        self,
        txn_id: int,
        rtype: LogRecordType,
        payload: bytes = b"",
    ) -> int:
        if txn_id < 0:
            raise ValueError("txn_id must be non-negative")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")

        lsn = self._next_lsn
        record = LogRecord(
            lsn=lsn,
            txn_id=txn_id,
            prev_lsn=self._txn_last_lsn.get(txn_id, 0),
            rtype=rtype,
            payload=payload,
        )
        encoded = record.to_bytes()
        if len(encoded) > 0xFFFFFFFF:
            raise ValueError("serialized log record is too large")

        self._file.write(_LENGTH_PREFIX.pack(len(encoded)))
        self._file.write(encoded)
        self._next_lsn += 1
        self._txn_last_lsn[txn_id] = lsn
        return lsn

    def flush(self, up_to_lsn: int | None = None) -> None:
        if up_to_lsn is None:
            up_to_lsn = self._next_lsn - 1
        if up_to_lsn < 0 or up_to_lsn >= self._next_lsn:
            raise ValueError(f"unknown LSN: {up_to_lsn}")

        self._file.flush()
        os.fsync(self._file.fileno())
        self._flushed_lsn = max(self._flushed_lsn, up_to_lsn)

    def durable_lsn(self) -> int:
        return self._flushed_lsn

    def iter_records(self) -> Iterator[LogRecord]:
        """Read complete records from the WAL file in LSN order."""
        with self._path.open("rb") as source:
            while True:
                prefix = source.read(_LENGTH_PREFIX.size)
                if not prefix:
                    return
                if len(prefix) != _LENGTH_PREFIX.size:
                    raise ValueError("truncated WAL record length prefix")

                (record_length,) = _LENGTH_PREFIX.unpack(prefix)
                encoded = source.read(record_length)
                if len(encoded) != record_length:
                    raise ValueError("truncated WAL record")
                yield LogRecord.from_bytes(encoded)

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
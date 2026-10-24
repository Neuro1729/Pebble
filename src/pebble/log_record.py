"""V3 Person A (from V4) — WAL log record types + serialize/deserialize.

PREREQUISITES:
  - pebble.rid.RID
  - pebble.types.Value (payload bytes for BEFORE/AFTER images)

USED BY:
  - pebble.wal.LogManager
  - V4 recovery (redo/undo readers)
  - tests/test_wal.py

PSEUDOCODE
==========
class LogRecordType(Enum):
    BEGIN, COMMIT, ABORT, INSERT, DELETE, UPDATE, CHECKPOINT

@dataclass
class LogRecord:
    lsn: int
    txn_id: int
    prev_lsn: int          # per-txn chain
    rtype: LogRecordType
    # optional payload:
    #   table/page/slot, before_image bytes, after_image bytes

    def to_bytes(self) -> bytes: ...
    @classmethod
    def from_bytes(cls, data: bytes) -> LogRecord: ...

DONE WHEN:
  - Round-trip to_bytes/from_bytes for BEGIN/COMMIT/INSERT at least
  - LSN / prev_lsn fields present for ARIES-style chains
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class LogRecordType(Enum):
    BEGIN = auto()
    COMMIT = auto()
    ABORT = auto()
    INSERT = auto()
    DELETE = auto()
    UPDATE = auto()
    CHECKPOINT = auto()


@dataclass
class LogRecord:
    """One WAL entry (header + optional payload)."""

    lsn: int
    txn_id: int
    prev_lsn: int
    rtype: LogRecordType
    payload: bytes = b""

    def to_bytes(self) -> bytes:
        # PSEUDO: pack header (lsn, txn_id, prev_lsn, type, len) + payload
        raise NotImplementedError("V3 Person A: implement LogRecord.to_bytes")

    @classmethod
    def from_bytes(cls, data: bytes) -> LogRecord:
        # PSEUDO: unpack header; slice payload; return LogRecord(...)
        raise NotImplementedError("V3 Person A: implement LogRecord.from_bytes")

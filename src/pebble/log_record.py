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

"""WAL log record types and serialization."""

from __future__ import annotations

import struct
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


# Header stores: lsn, txn_id, prev_lsn, record type, payload length.
_HEADER = struct.Struct("<QQQII")


@dataclass
class LogRecord:
    """One WAL entry containing a header and optional byte payload."""

    lsn: int
    txn_id: int
    prev_lsn: int
    rtype: LogRecordType
    payload: bytes = b""

    def to_bytes(self) -> bytes:
        """Serialize this record into a fixed header followed by its payload."""
        if min(self.lsn, self.txn_id, self.prev_lsn) < 0:
            raise ValueError("LSN and transaction IDs must be non-negative")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be bytes")

        header = _HEADER.pack(
            self.lsn,
            self.txn_id,
            self.prev_lsn,
            self.rtype.value,
            len(self.payload),
        )
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> LogRecord:
        """Deserialize one complete record; reject truncated or trailing data."""
        if len(data) < _HEADER.size:
            raise ValueError("truncated log record header")

        lsn, txn_id, prev_lsn, type_value, payload_length = _HEADER.unpack_from(data)
        expected_length = _HEADER.size + payload_length
        if len(data) != expected_length:
            raise ValueError(
                f"log record length mismatch: expected {expected_length}, got {len(data)}"
            )

        try:
            rtype = LogRecordType(type_value)
        except ValueError as exc:
            raise ValueError(f"unknown log record type: {type_value}") from exc

        payload = data[_HEADER.size:]
        return cls(
            lsn=lsn,
            txn_id=txn_id,
            prev_lsn=prev_lsn,
            rtype=rtype,
            payload=payload,
        )
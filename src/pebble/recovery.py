"""V3 Person A stub / V4 finish — ARIES-style recovery from WAL.

PREREQUISITES:
  - pebble.wal.LogManager.iter_records
  - pebble.log_record.LogRecordType
  - BufferPoolManager + DiskManager for redo into pages
  - UndoLog / heap apply for undo of loser txns

V3 SCOPE (do in V3 if time; otherwise skeleton only):
  - Parse full log; classify COMMITTED vs loser txn_ids
  - Unit-testable Analysis pass on an in-memory record list

V4 SCOPE (must finish project):
  - Redo committed changes missing from data file
  - Undo loser txns
  - Checkpoint record + truncate/logic
  - database.recover() on open if log present

PSEUDOCODE
==========
@dataclass
class AnalysisResult:
    committed: set[int]
    losers: set[int]
    dirty_pages: dict[page_id, rec_lsn]  # optional V3

def analyze(records: Iterable[LogRecord]) -> AnalysisResult:
    # ATTACH txn on BEGIN; move to committed on COMMIT; else loser
    ...

def redo(records, bpm, catalog) -> None:
    # for each record of committed txn in LSN order: re-apply if needed
    raise NotImplementedError  # V4

def undo(losers, records, bpm, catalog) -> None:
    # walk losers backward via prev_lsn chains
    raise NotImplementedError  # V4

class RecoveryManager:
    def __init__(self, wal, bpm, catalog): ...
    def recover(self) -> None:
        # analyze → redo → undo; flush

DONE WHEN (V3):
  - analyze() correctly splits commit vs abort vs in-flight on a fixture log
DONE WHEN (V4):
  - kill process after COMMIT flush → reopen → data present
  - kill after INSERT before COMMIT → reopen → row absent
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from pebble.log_record import LogRecord


@dataclass
class AnalysisResult:
    committed: set[int] = field(default_factory=set)
    losers: set[int] = field(default_factory=set)


def analyze(records: Iterable[LogRecord]) -> AnalysisResult:
    """V3 Person A: implement analysis pass (no disk redo yet)."""
    # PSEUDO:
    #   active = set()
    #   committed = set()
    #   for rec in records:
    #       if BEGIN: active.add(txn)
    #       if COMMIT: active.discard; committed.add
    #       if ABORT: active.discard
    #   losers = active
    #   return AnalysisResult(committed, losers)
    raise NotImplementedError("V3 Person A: implement analyze()")


class RecoveryManager:
    """Full recover() is V4; wire analyze in V3."""

    def __init__(
        self,
        wal: object,
        bpm: object,
        catalog: object,
    ) -> None:
        raise NotImplementedError("V3/V4: implement RecoveryManager.__init__")

    def recover(self) -> None:
        # V4: analyze(wal.iter_records()); redo; undo; flush
        raise NotImplementedError("V4: implement RecoveryManager.recover")

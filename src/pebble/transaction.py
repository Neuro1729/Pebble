"""V3 Person A (from V4) — Transaction object: id, timestamps, state.

PREREQUISITES (must already work):
  - None beyond stdlib (pure metadata). Later: catalog / heap call sites.

USED BY:
  - pebble.transaction_manager
  - pebble.wal (log records carry txn_id)
  - delete/update/insert executors (stamp rows with txn ids)
  - tests/test_transaction.py

NOT IN THIS FILE:
  - Lock table / 2PL (stretch; optimistic MVCC first)
  - Recovery orchestration (V4 finish)

PSEUDOCODE
==========
class TransactionState(Enum):
    GROWING, SHRINKING, COMMITTED, ABORTED  # or: ACTIVE, COMMITTED, ABORTED

class IsolationLevel(Enum):
    READ_COMMITTED, SNAPSHOT  # V3 MVP: SNAPSHOT / optimistic read view only

@dataclass
class Transaction:
    txn_id: int
    read_ts: int          # snapshot: see versions with begin_ts <= read_ts
    commit_ts: int | None
    state: TransactionState
    undo_link: int | None # optional: head of undo chain for this txn
    # write_set: list[RID]  # for commit validation / abort rollback

DONE WHEN:
  - Can construct a txn and flip state ACTIVE → COMMITTED / ABORTED
  - Fields needed by TM + WAL exist and are typed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from pebble.rid import RID


class TransactionState(Enum):
    ACTIVE = auto()
    COMMITTED = auto()
    ABORTED = auto()


class IsolationLevel(Enum):
    READ_COMMITTED = auto()
    SNAPSHOT = auto()


@dataclass
class Transaction:
    """One logical transaction (single-threaded V3)."""

    txn_id: int
    read_ts: int
    isolation: IsolationLevel = IsolationLevel.SNAPSHOT
    state: TransactionState = TransactionState.ACTIVE
    commit_ts: int | None = None
    write_set: list[RID] = field(default_factory=list)

    def is_active(self) -> bool:
        # PSEUDO: return self.state == TransactionState.ACTIVE
        raise NotImplementedError("V3 Person A: implement Transaction.is_active")

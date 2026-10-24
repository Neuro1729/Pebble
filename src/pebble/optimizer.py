"""V3 Person A — tiny rule-based optimizer (no cost model / stats).

PREREQUISITES (must already work):
  - pebble.catalog.Catalog / TableInfo / IndexInfo
  - pebble.hash_join.HashJoinExecutor
  - Existing IndexScan rule knowledge (see database._plan_single_table_scan)
  - pebble.executor.* operators

USED BY:
  - database.py planning (Person A wires JOIN; Person B may call helpers for scans)
  - tests/test_optimizer.py

NOT IN THIS FILE:
  - Real cost-based optimizer, histograms, join reordering search
  - SQL parsing (stays in database.py)

PSEUDOCODE
==========
# Keep this module about PLAN SHAPE decisions, not string parsing.

def prefer_index_scan(table, where_equality_col, literal) -> bool:
    # True if catalog has an index on that INTEGER column

def choose_join(left_plan, right_plan, is_equality: bool) -> str:
    # if is_equality: return "hash"
    # else: return "nlj"

def push_filter_below_project(plan): ...  # optional stretch

# Optional richer API (if you want structured plans):
#   @dataclass
#   class Plan: ...
#   def optimize(plan: Plan) -> Plan: apply rules bottom-up

DONE WHEN:
  - Equality joins select HashJoin
  - Non-equality (if any) stay NLJ
  - Indexed equality still prefers IndexScan (reuse / call into existing logic)
  - Unit tests assert operator choice without needing full SQL
"""



from __future__ import annotations

from pebble.catalog import IndexInfo, TableInfo
from pebble.types import Value


def prefer_index_scan(
    table: TableInfo,
    column_name: str,
    literal: Value,
) -> IndexInfo | None:
    """Return an index for an equality lookup on an indexed INTEGER column."""
    if not isinstance(literal, int) or isinstance(literal, bool):
        return None

    for index in table.indexes:
        if index.key_columns == [column_name]:
            return index

    return None


def choose_join_algorithm(*, is_equality: bool) -> str:
    """Return ``"hash"`` for equality joins; otherwise return ``"nlj"``."""
    return "hash" if is_equality else "nlj"
"""V3 Person A — tests for rule-based optimizer helpers.

PREREQUISITES: optimizer.py (+ catalog with an index for prefer_index_scan).

PSEUDOCODE CASES
================
1. choose_join_algorithm(is_equality=True) == \"hash\"
2. choose_join_algorithm(is_equality=False) == \"nlj\"
3. prefer_index_scan returns IndexInfo when indexed INTEGER col
4. prefer_index_scan returns None when no index
"""
"""Tests for rule-based optimizer helpers."""

from __future__ import annotations

from pathlib import Path

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.disk_manager import DiskManager
from pebble.optimizer import choose_join_algorithm, prefer_index_scan
from pebble.schema import Column, Schema
from pebble.types import TypeId


def test_choose_join_hash_for_equality() -> None:
    assert choose_join_algorithm(is_equality=True) == "hash"
    assert choose_join_algorithm(is_equality=False) == "nlj"


def test_prefer_index_scan_hit_and_miss(tmp_path: Path) -> None:
    schema = Schema(
        [
            Column("id", TypeId.INTEGER),
            Column("name", TypeId.VARCHAR),
        ]
    )

    with DiskManager(tmp_path / "optimizer.db") as disk:
        with BufferPoolManager(pool_size=8, disk_manager=disk) as bpm:
            catalog = Catalog(bpm)
            table = catalog.create_table("users", schema)
            index = catalog.create_index("users_id", "users", ["id"])

            assert prefer_index_scan(table, "id", 42) is index
            assert prefer_index_scan(table, "name", "Alice") is None
            assert prefer_index_scan(table, "missing", 42) is None
            assert prefer_index_scan(table, "id", "42") is None
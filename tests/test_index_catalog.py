"""V2 step 7: catalog indexes + maintain on insert."""

from __future__ import annotations

from pathlib import Path

import pytest

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.disk_manager import DiskManager
from pebble.executor import InsertExecutor, poll
from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId


def _users_schema() -> Schema:
    return Schema(
        [
            Column("id", TypeId.INTEGER),
            Column("name", TypeId.VARCHAR),
        ]
    )


def test_create_index_backfill_and_search(tmp_path: Path) -> None:
    db_file = tmp_path / "idx.db"
    schema = _users_schema()
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=32, disk_manager=disk) as bpm:
            catalog = Catalog(bpm)
            users = catalog.create_table("users", schema)
            users.heap.insert_tuple(Tuple.from_values(schema, [1, "a"]))
            users.heap.insert_tuple(Tuple.from_values(schema, [2, "b"]))

            idx = catalog.create_index("users_id", "users", ["id"])
            assert catalog.list_indexes("users") == ["users_id"]
            assert catalog.get_index("users_id") is idx

            rid1 = idx.tree.search(1)
            rid2 = idx.tree.search(2)
            assert rid1 is not None and rid2 is not None
            assert users.heap.get_tuple(rid1).values == [1, "a"]
            assert users.heap.get_tuple(rid2).values == [2, "b"]


def test_insert_updates_index(tmp_path: Path) -> None:
    db_file = tmp_path / "ins.db"
    schema = _users_schema()
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=32, disk_manager=disk) as bpm:
            catalog = Catalog(bpm)
            users = catalog.create_table("users", schema)
            idx = catalog.create_index("users_id", "users", ["id"])

            poll(
                InsertExecutor(
                    users,
                    [
                        Tuple.from_values(schema, [10, "x"]),
                        Tuple.from_values(schema, [20, "y"]),
                    ],
                )
            )

            rid = idx.tree.search(20)
            assert rid is not None
            assert users.heap.get_tuple(rid).values == [20, "y"]
            assert idx.tree.search(99) is None


def test_create_index_rejects_bad_keys(tmp_path: Path) -> None:
    db_file = tmp_path / "bad.db"
    schema = _users_schema()
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=8, disk_manager=disk) as bpm:
            catalog = Catalog(bpm)
            catalog.create_table("users", schema)
            with pytest.raises(ValueError, match="INTEGER"):
                catalog.create_index("by_name", "users", ["name"])
            with pytest.raises(NotImplementedError):
                catalog.create_index("multi", "users", ["id", "name"])

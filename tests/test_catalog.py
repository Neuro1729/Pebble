"""Step 6: catalog create/get tables by name."""

from __future__ import annotations

from pathlib import Path

import pytest

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.disk_manager import DiskManager
from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId


def test_two_tables_insert_and_lookup(tmp_path: Path) -> None:
    db_file = tmp_path / "catalog.db"
    users_schema = Schema(
        [Column("id", TypeId.INTEGER), Column("name", TypeId.VARCHAR)]
    )
    orders_schema = Schema(
        [Column("oid", TypeId.INTEGER), Column("uid", TypeId.INTEGER)]
    )

    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=8, disk_manager=disk)
        catalog = Catalog(bpm)

        users = catalog.create_table("users", users_schema)
        orders = catalog.create_table("orders", orders_schema)

        users.heap.insert_tuple(Tuple.from_values(users_schema, [1, "a"]))
        users.heap.insert_tuple(Tuple.from_values(users_schema, [2, "b"]))
        orders.heap.insert_tuple(Tuple.from_values(orders_schema, [10, 1]))

        got_users = catalog.get_table("users")
        got_orders = catalog.get_table("orders")

        assert got_users is users
        assert got_orders is orders
        assert [t.values for _, t in got_users.heap.scan()] == [[1, "a"], [2, "b"]]
        assert [t.values for _, t in got_orders.heap.scan()] == [[10, 1]]
        assert catalog.list_tables() == ["orders", "users"]


def test_duplicate_and_missing(tmp_path: Path) -> None:
    db_file = tmp_path / "dup.db"
    schema = Schema([Column("id", TypeId.INTEGER)])
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=4, disk_manager=disk)
        catalog = Catalog(bpm)
        catalog.create_table("t", schema)
        with pytest.raises(ValueError, match="already exists"):
            catalog.create_table("t", schema)
        with pytest.raises(KeyError, match="not found"):
            catalog.get_table("nope")

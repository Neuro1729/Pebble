"""Step 9: NestedLoopJoinExecutor."""

from __future__ import annotations

from pathlib import Path

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.disk_manager import DiskManager
from pebble.executor import (
    InsertExecutor,
    NestedLoopJoinExecutor,
    SeqScanExecutor,
    poll,
)
from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId


def test_join_users_and_orders(tmp_path: Path) -> None:
    db_file = tmp_path / "join.db"
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

        poll(
            InsertExecutor(
                users,
                [
                    Tuple.from_values(users_schema, [1, "ann"]),
                    Tuple.from_values(users_schema, [2, "bob"]),
                    Tuple.from_values(users_schema, [3, "cara"]),
                ],
            )
        )
        poll(
            InsertExecutor(
                orders,
                [
                    Tuple.from_values(orders_schema, [10, 1]),
                    Tuple.from_values(orders_schema, [11, 1]),
                    Tuple.from_values(orders_schema, [20, 2]),
                ],
            )
        )

        # users.id == orders.uid
        plan = NestedLoopJoinExecutor(
            SeqScanExecutor(users),
            SeqScanExecutor(orders),
            predicate=lambda u, o: u.get_value(0) == o.get_value(1),
        )
        result = [t.values for t in poll(plan)]
        assert result == [
            [1, "ann", 10, 1],
            [1, "ann", 11, 1],
            [2, "bob", 20, 2],
        ]

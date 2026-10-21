"""V2 step 8: IndexScanExecutor matches SeqScan + Filter."""

from __future__ import annotations

from pathlib import Path

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.disk_manager import DiskManager
from pebble.executor import (
    FilterExecutor,
    IndexScanExecutor,
    InsertExecutor,
    SeqScanExecutor,
    poll,
)
from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId


def _schema() -> Schema:
    return Schema(
        [
            Column("id", TypeId.INTEGER),
            Column("name", TypeId.VARCHAR),
        ]
    )


def test_point_index_scan_matches_seqscan_filter(tmp_path: Path) -> None:
    db_file = tmp_path / "point.db"
    schema = _schema()
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=32, disk_manager=disk) as bpm:
            catalog = Catalog(bpm)
            users = catalog.create_table("users", schema)
            idx = catalog.create_index("users_id", "users", ["id"])
            poll(
                InsertExecutor(
                    users,
                    [
                        Tuple.from_values(schema, [1, "a"]),
                        Tuple.from_values(schema, [2, "b"]),
                        Tuple.from_values(schema, [3, "c"]),
                    ],
                )
            )

            id_col = schema.column_index("id")
            via_filter = poll(
                FilterExecutor(
                    SeqScanExecutor(users),
                    lambda t: t.get_value(id_col) == 2,
                )
            )
            via_index = poll(
                IndexScanExecutor(users, idx, equals_key=2)
            )
            assert [t.values for t in via_index] == [t.values for t in via_filter]
            assert via_index[0].values == [2, "b"]

            assert poll(IndexScanExecutor(users, idx, equals_key=99)) == []


def test_range_index_scan_matches_seqscan_filter(tmp_path: Path) -> None:
    db_file = tmp_path / "range.db"
    schema = _schema()
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=32, disk_manager=disk) as bpm:
            catalog = Catalog(bpm)
            users = catalog.create_table("users", schema)
            idx = catalog.create_index("users_id", "users", ["id"])
            rows = [
                Tuple.from_values(schema, [i, f"n{i}"]) for i in (1, 3, 5, 7, 9)
            ]
            poll(InsertExecutor(users, rows))

            id_col = schema.column_index("id")
            via_filter = poll(
                FilterExecutor(
                    SeqScanExecutor(users),
                    lambda t: 3 <= t.get_value(id_col) <= 7,  # type: ignore[operator]
                )
            )
            via_index = poll(
                IndexScanExecutor(users, idx, low_key=3, high_key=7)
            )
            assert sorted(t.values for t in via_index) == sorted(
                t.values for t in via_filter
            )
            assert [t.values[0] for t in via_index] == [3, 5, 7]

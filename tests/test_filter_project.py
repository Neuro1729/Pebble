"""Step 8: Filter + Project on top of SeqScan."""

from __future__ import annotations

from pathlib import Path

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.disk_manager import DiskManager
from pebble.executor import (
    FilterExecutor,
    InsertExecutor,
    ProjectExecutor,
    SeqScanExecutor,
    poll,
)
from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId


def test_scan_filter_project(tmp_path: Path) -> None:
    db_file = tmp_path / "fp.db"
    schema = Schema(
        [
            Column("id", TypeId.INTEGER),
            Column("name", TypeId.VARCHAR),
            Column("age", TypeId.INTEGER),
        ]
    )

    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=8, disk_manager=disk)
        catalog = Catalog(bpm)
        table = catalog.create_table("people", schema)

        rows = [
            Tuple.from_values(schema, [1, "ann", 17]),
            Tuple.from_values(schema, [2, "bob", 30]),
            Tuple.from_values(schema, [3, "cara", 25]),
            Tuple.from_values(schema, [4, "dan", 10]),
        ]
        poll(InsertExecutor(table, rows))

        # SELECT name FROM people WHERE age >= 18
        plan = ProjectExecutor(
            FilterExecutor(
                SeqScanExecutor(table),
                predicate=lambda t: int(t.get_value(2)) >= 18,
            ),
            column_indexes=[1],  # name
        )
        result = poll(plan)
        assert [t.values for t in result] == [["bob"], ["cara"]]

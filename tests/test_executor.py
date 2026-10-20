"""Step 7: Insert + SeqScan executors (Volcano Init/Next)."""

from __future__ import annotations

from pathlib import Path

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.disk_manager import DiskManager
from pebble.executor import InsertExecutor, SeqScanExecutor, poll
from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId


def test_insert_then_seqscan_via_executors(tmp_path: Path) -> None:
    db_file = tmp_path / "exec.db"
    schema = Schema(
        [Column("id", TypeId.INTEGER), Column("name", TypeId.VARCHAR)]
    )

    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=8, disk_manager=disk)
        catalog = Catalog(bpm)
        table = catalog.create_table("t", schema)

        to_insert = [
            Tuple.from_values(schema, [i, f"n{i}"]) for i in range(25)
        ]
        inserted = poll(InsertExecutor(table, to_insert))
        assert [t.values for t in inserted] == [[i, f"n{i}"] for i in range(25)]

        scanned = poll(SeqScanExecutor(table))
        assert [t.values for t in scanned] == [[i, f"n{i}"] for i in range(25)]

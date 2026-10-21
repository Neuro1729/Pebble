"""In-memory catalog: table name → schema + heap.

V1: not persisted across process restart (page data on disk still is;
 you would need to recreate catalog metadata or add a catalog page later).
LATER: persist catalog pages; indexes; oid assignment like BusTub.
"""

from __future__ import annotations

from dataclasses import dataclass

from pebble.buffer_pool import BufferPoolManager
from pebble.schema import Schema
from pebble.table_heap import TableHeap


@dataclass
class TableInfo:
    name: str
    schema: Schema
    heap: TableHeap

    @property
    def first_page_id(self) -> int:
        return self.heap.first_page_id

    @property
    def last_page_id(self) -> int:
        return self.heap.last_page_id


class Catalog:
    def __init__(self, bpm: BufferPoolManager) -> None:
        self._bpm = bpm
        self._tables: dict[str, TableInfo] = {}

    def create_table(self, name: str, schema: Schema) -> TableInfo:
        if not name:
            raise ValueError("table name must be non-empty")
        if name in self._tables:
            raise ValueError(f"table already exists: {name}")
        heap = TableHeap.create(self._bpm, schema)
        info = TableInfo(name=name, schema=schema, heap=heap)
        self._tables[name] = info
        return info

    def get_table(self, name: str) -> TableInfo:
        try:
            return self._tables[name]
        except KeyError as exc:
            raise KeyError(f"table not found: {name}") from exc

    def list_tables(self) -> list[str]:
        return sorted(self._tables.keys())

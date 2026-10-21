"""In-memory catalog: tables + secondary indexes.

V1: tables only (schema + heap). Not persisted across process restart.
V2 step 7: create_index, IndexInfo, maintain B+Tree on insert (backfill on create).
LATER: persist catalog pages; oid assignment like BusTub; multi-column keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pebble.bplus_tree import BPlusTree
from pebble.buffer_pool import BufferPoolManager
from pebble.schema import Column, Schema
from pebble.table_heap import TableHeap
from pebble.tuple import Tuple
from pebble.types import TypeId, Value


@dataclass
class IndexInfo:
    """Secondary index metadata + live B+Tree (unique int32 key for V2)."""

    name: str
    table_name: str
    key_columns: list[str]
    key_col_indexes: list[int]
    tree: BPlusTree
    is_unique: bool = True

    @property
    def root_page_id(self) -> int:
        return self.tree.root_page_id

    @property
    def key_schema(self) -> Schema:
        # Single INTEGER key for V2 B+Tree.
        return Schema([Column(self.key_columns[0], TypeId.INTEGER)])

    def key_from_tuple(self, tup: Tuple) -> int:
        if len(self.key_col_indexes) != 1:
            raise NotImplementedError("V2 indexes support a single INTEGER key column")
        value: Value = tup.get_value(self.key_col_indexes[0])
        if not isinstance(value, int):
            raise TypeError(
                f"index {self.name} key must be int, got {type(value).__name__}"
            )
        return value


@dataclass
class TableInfo:
    name: str
    schema: Schema
    heap: TableHeap
    indexes: list[IndexInfo] = field(default_factory=list)

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
        self._indexes: dict[str, IndexInfo] = {}

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

    def create_index(
        self,
        name: str,
        table_name: str,
        key_columns: list[str],
        *,
        is_unique: bool = True,
    ) -> IndexInfo:
        """Create a unique B+Tree index on one INTEGER column; backfill existing rows."""
        if not name:
            raise ValueError("index name must be non-empty")
        if name in self._indexes:
            raise ValueError(f"index already exists: {name}")
        if not key_columns:
            raise ValueError("key_columns must be non-empty")
        if len(key_columns) != 1:
            raise NotImplementedError("V2 supports a single key column only")

        table = self.get_table(table_name)
        col_name = key_columns[0]
        try:
            col_index = table.schema.column_index(col_name)
        except KeyError as exc:
            raise ValueError(f"column not found: {col_name}") from exc
        if table.schema.columns[col_index].type_id is not TypeId.INTEGER:
            raise ValueError(
                f"index key column {col_name} must be INTEGER (got "
                f"{table.schema.columns[col_index].type_id.name})"
            )

        tree = BPlusTree.create(self._bpm)
        index = IndexInfo(
            name=name,
            table_name=table_name,
            key_columns=list(key_columns),
            key_col_indexes=[col_index],
            tree=tree,
            is_unique=is_unique,
        )

        # Backfill rows already on the heap.
        for rid, tup in table.heap.scan():
            key = index.key_from_tuple(tup)
            tree.insert(key, rid)

        self._indexes[name] = index
        table.indexes.append(index)
        return index

    def get_index(self, name: str) -> IndexInfo:
        try:
            return self._indexes[name]
        except KeyError as exc:
            raise KeyError(f"index not found: {name}") from exc

    def list_indexes(self, table_name: str | None = None) -> list[str]:
        if table_name is None:
            return sorted(self._indexes.keys())
        table = self.get_table(table_name)
        return sorted(idx.name for idx in table.indexes)

    def insert_tuple(self, table: TableInfo, tup: Tuple) -> None:
        """Heap insert + maintain every secondary index on the table."""
        rid = table.heap.insert_tuple(tup)
        for index in table.indexes:
            index.tree.insert(index.key_from_tuple(tup), rid)

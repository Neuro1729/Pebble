"""Tiny Database front end + dumb planner (no optimizer).

Supported SQL (very limited, case-insensitive keywords):
  CREATE TABLE name (col TYPE, ...)
  INSERT INTO name VALUES (v1, v2), (v3, v4)
  SELECT *|col,... FROM t [WHERE col OP value]
  SELECT *|col,... FROM t1 JOIN t2 ON t1.col = t2.col [WHERE ...]

OP: = != < <= > >=
TYPE: INTEGER | INT | VARCHAR
Strings: 'single quotes' (use '' for a literal quote).

LATER: real binder/parser/optimizer (BusTub-style).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from pebble.buffer_pool import BufferPoolManager
from pebble.catalog import Catalog
from pebble.disk_manager import DiskManager
from pebble.executor import (
    Executor,
    FilterExecutor,
    InsertExecutor,
    NestedLoopJoinExecutor,
    ProjectExecutor,
    SeqScanExecutor,
    poll,
)
from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId, Value

_TYPE_MAP = {
    "INTEGER": TypeId.INTEGER,
    "INT": TypeId.INTEGER,
    "VARCHAR": TypeId.VARCHAR,
}


class Database:
    def __init__(self, db_path: Path | str, pool_size: int = 64) -> None:
        self._disk = DiskManager(db_path)
        self._bpm = BufferPoolManager(pool_size, self._disk)
        self._catalog = Catalog(self._bpm)

    def close(self) -> None:
        self._bpm.flush_all_pages()
        self._disk.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    def execute(self, sql: str) -> list[list[Value]]:
        """Parse + plan + run. Returns rows as list of value lists (empty for DDL)."""
        statement = sql.strip().rstrip(";")
        if not statement:
            raise ValueError("empty SQL")

        upper = statement.upper()
        if upper.startswith("CREATE TABLE"):
            self._exec_create(statement)
            return []
        if upper.startswith("INSERT INTO"):
            return self._exec_insert(statement)
        if upper.startswith("SELECT"):
            return self._exec_select(statement)
        raise ValueError(f"unsupported SQL: {statement[:40]}...")

    def _exec_create(self, sql: str) -> None:
        match = re.match(
            r"CREATE\s+TABLE\s+(\w+)\s*\((.+)\)\s*$",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise ValueError(f"bad CREATE TABLE: {sql}")
        name, body = match.group(1), match.group(2)
        columns: list[Column] = []
        for part in _split_commas(body):
            tokens = part.split()
            if len(tokens) != 2:
                raise ValueError(f"bad column def: {part}")
            col_name, type_name = tokens[0], tokens[1].upper()
            if type_name not in _TYPE_MAP:
                raise ValueError(f"unsupported type: {type_name}")
            columns.append(Column(col_name, _TYPE_MAP[type_name]))
        self._catalog.create_table(name, Schema(columns))

    def _exec_insert(self, sql: str) -> list[list[Value]]:
        match = re.match(
            r"INSERT\s+INTO\s+(\w+)\s+VALUES\s*(.+)$",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise ValueError(f"bad INSERT: {sql}")
        table_name, values_sql = match.group(1), match.group(2).strip()
        table = self._catalog.get_table(table_name)
        row_groups = _parse_value_groups(values_sql)
        tuples = [Tuple.from_values(table.schema, values) for values in row_groups]
        inserted = poll(InsertExecutor(table, tuples))
        return [t.values for t in inserted]

    def _exec_select(self, sql: str) -> list[list[Value]]:
        match = re.match(
            r"SELECT\s+(.+?)\s+FROM\s+(\w+)"
            r"(?:\s+JOIN\s+(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+))?"
            r"(?:\s+WHERE\s+(.+))?\s*$",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise ValueError(f"bad SELECT: {sql}")

        cols_sql = match.group(1).strip()
        left_name = match.group(2)
        right_name = match.group(3)
        where_sql = match.group(8)

        left = self._catalog.get_table(left_name)
        plan: Executor = SeqScanExecutor(left)

        if right_name is None:
            name_to_idx = {c.name: i for i, c in enumerate(left.schema.columns)}
        else:
            right = self._catalog.get_table(right_name)
            left_idx, right_idx = _resolve_join_indexes(
                left_name,
                left.schema,
                right_name,
                right.schema,
                match.group(4),
                match.group(5),
                match.group(6),
                match.group(7),
            )
            plan = NestedLoopJoinExecutor(
                plan,
                SeqScanExecutor(right),
                predicate=lambda l, r, li=left_idx, ri=right_idx: l.get_value(li)
                == r.get_value(ri),
            )
            name_to_idx = _join_column_map(left_name, left.schema, right_name, right.schema)

        if where_sql is not None:
            plan = FilterExecutor(plan, _compile_where(where_sql.strip(), name_to_idx))

        if cols_sql != "*":
            col_names = [c.strip() for c in _split_commas(cols_sql)]
            indexes = []
            for col_name in col_names:
                if col_name not in name_to_idx:
                    raise ValueError(f"unknown column: {col_name}")
                indexes.append(name_to_idx[col_name])
            plan = ProjectExecutor(plan, indexes)

        return [t.values for t in poll(plan)]


def _join_column_map(
    left_name: str,
    left_schema: Schema,
    right_name: str,
    right_schema: Schema,
) -> dict[str, int]:
    """Map SELECT/WHERE names to indexes in concatenated join tuples."""
    name_to_idx: dict[str, int] = {}
    left_names = {c.name for c in left_schema.columns}
    right_names = {c.name for c in right_schema.columns}

    for i, col in enumerate(left_schema.columns):
        name_to_idx[f"{left_name}.{col.name}"] = i
        if col.name not in right_names:
            name_to_idx[col.name] = i

    offset = left_schema.column_count()
    for i, col in enumerate(right_schema.columns):
        name_to_idx[f"{right_name}.{col.name}"] = offset + i
        if col.name not in left_names:
            name_to_idx[col.name] = offset + i
    return name_to_idx


def _resolve_join_indexes(
    left_name: str,
    left_schema: Schema,
    right_name: str,
    right_schema: Schema,
    on_left_table: str,
    on_left_col: str,
    on_right_table: str,
    on_right_col: str,
) -> tuple[int, int]:
    """Return (left_tuple_col_idx, right_tuple_col_idx) for NLJ predicate."""
    mapping = {
        left_name.lower(): ("left", left_schema),
        right_name.lower(): ("right", right_schema),
    }
    if on_left_table.lower() not in mapping or on_right_table.lower() not in mapping:
        raise ValueError("JOIN ON tables must match FROM/JOIN table names")

    side_a, schema_a = mapping[on_left_table.lower()]
    side_b, schema_b = mapping[on_right_table.lower()]
    idx_a = schema_a.column_index(on_left_col)
    idx_b = schema_b.column_index(on_right_col)

    if side_a == "left" and side_b == "right":
        return idx_a, idx_b
    if side_a == "right" and side_b == "left":
        return idx_b, idx_a
    raise ValueError("JOIN ON must reference both tables once")


def _compile_where(
    where_sql: str, name_to_idx: dict[str, int]
) -> Callable[[Tuple], bool]:
    match = re.match(
        r"([A-Za-z_][\w.]*)\s*(=|!=|<=|>=|<|>)\s*(.+)$",
        where_sql.strip(),
    )
    if not match:
        raise ValueError(f"bad WHERE: {where_sql}")
    col, op, literal_sql = match.group(1), match.group(2), match.group(3).strip()
    if col not in name_to_idx:
        raise ValueError(f"unknown column in WHERE: {col}")
    idx = name_to_idx[col]
    literal = _parse_literal(literal_sql)

    def predicate(
        tup: Tuple, i: int = idx, operator: str = op, lit: Value = literal
    ) -> bool:
        left = tup.get_value(i)
        if operator == "=":
            return left == lit
        if operator == "!=":
            return left != lit
        if operator == "<":
            return left < lit  # type: ignore[operator]
        if operator == "<=":
            return left <= lit  # type: ignore[operator]
        if operator == ">":
            return left > lit  # type: ignore[operator]
        if operator == ">=":
            return left >= lit  # type: ignore[operator]
        raise ValueError(f"bad operator: {operator}")

    return predicate


def _split_commas(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_str = False
    for ch in text:
        if ch == "'":
            in_str = not in_str
            buf.append(ch)
        elif ch == "," and not in_str:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_value_groups(values_sql: str) -> list[list[Value]]:
    """Parse `(1, 'a'), (2, 'b')` into lists of Values."""
    text = values_sql.strip()
    groups: list[list[Value]] = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        if text[i] != "(":
            raise ValueError(f"expected '(' in VALUES near: {text[i : i + 20]}")
        i += 1
        depth = 1
        start = i
        in_str = False
        while i < len(text) and depth:
            ch = text[i]
            if ch == "'":
                in_str = not in_str
            elif not in_str:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            i += 1
        inner = text[start : i - 1]
        groups.append([_parse_literal(p.strip()) for p in _split_commas(inner)])
        while i < len(text) and (text[i].isspace() or text[i] == ","):
            i += 1
    if not groups:
        raise ValueError("INSERT VALUES needs at least one row")
    return groups


def _parse_literal(text: str) -> Value:
    text = text.strip()
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"bad literal: {text}") from exc

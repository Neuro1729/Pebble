"""Table schema: ordered columns with names and types."""

from __future__ import annotations

from dataclasses import dataclass

from pebble.types import TypeId


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type_id: TypeId


class Schema:
    """Ordered list of columns. Used to encode/decode tuples."""

    def __init__(self, columns: list[Column]) -> None:
        if not columns:
            raise ValueError("schema must have at least one column")
        names = [c.name for c in columns]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate column names: {names}")
        self._columns = list(columns)
        self._name_to_idx = {c.name: i for i, c in enumerate(self._columns)}

    @property
    def columns(self) -> list[Column]:
        return list(self._columns)

    def column_count(self) -> int:
        return len(self._columns)

    def get_column(self, idx: int) -> Column:
        return self._columns[idx]

    def column_index(self, name: str) -> int:
        try:
            return self._name_to_idx[name]
        except KeyError as exc:
            raise KeyError(f"unknown column: {name}") from exc

    def __repr__(self) -> str:
        cols = ", ".join(f"{c.name}:{c.type_id.name}" for c in self._columns)
        return f"Schema({cols})"

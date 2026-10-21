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


#Explantion of the above code - 


# This Python code defines a basic structural model for a database or tabular data system. It provides two core classes—**`Column`** (representing an individual column) and **`Schema`** (representing the complete, ordered layout of a table)—to enforce validity and support fast lookups.

# ---

# ### 1. The `Column` Class

# ```python
# @dataclass(frozen=True, slots=True)
# class Column:
#     name: str
#     type_id: TypeId

# ```

# * **Purpose:** Represents a single column definition containing its `name` (e.g., `"age"`) and `type_id` (data type, e.g., integer, string).
# * **`frozen=True`:** Makes instances immutable so column definitions cannot be modified after creation.
# * **`slots=True`:** Optimizes memory usage and speeds up attribute access by suppressing the default per-instance `__dict__`.

# ---

# ### 2. The `Schema` Class

# The `Schema` class acts as a container for an ordered list of `Column` objects, providing input validation and efficient lookups.

# #### Initialization (`__init__`)

# When a `Schema` is instantiated, it automatically validates and indexes the provided columns:

# 1. **Empty Check:** Raises a `ValueError` if no columns are passed (`columns` cannot be empty).
# 2. **Duplicate Check:** Compares the number of column names against a set of unique names. If duplicates exist, it raises a `ValueError`.
# 3. **Internal Storage (`_columns`):** Stores a copy of the column list to maintain order.
# 4. **Index Mapping (`_name_to_idx`):** Builds a dictionary mapping column names to their positional index (e.g., `{"id": 0, "name": 1}`). This allows $O(1)$ constant-time lookup of column indices by name.

# ---

# ### 3. `Schema` Methods & Properties

# * **`columns` (property):** Returns a copy of the list of `Column` objects, preventing external code from directly mutating the internal `_columns` list.
# * **`column_count()`:** Returns the total number of columns in the schema.
# * **`get_column(idx)`:** Retrieves a `Column` by its numerical index position (e.g., index `0` for the first column).
# * **`column_index(name)`:** Looks up a column's positional index by its name using the `_name_to_idx` map. Raises a clear `KeyError` if the column name doesn't exist.
# * **`__repr__()`:** Custom string representation for debugging (e.g., rendering as `Schema(id:INT, name:VARCHAR)`).

# ---

# ### Example Usage

# ```python
# # Creating columns
# col1 = Column(name="id", type_id=TypeId.INT)
# col2 = Column(name="email", type_id=TypeId.STRING)

# # Creating the schema
# schema = Schema([col1, col2])

# # Operations
# print(schema.column_count())      # Output: 2
# print(schema.column_index("email")) # Output: 1
# print(schema.get_column(0))       # Output: Column(name='id', type_id=...)
# print(schema)                     # Output: Schema(id:INT, email:STRING)

# ```
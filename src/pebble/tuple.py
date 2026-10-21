"""Tuple: in-memory values + byte serialization for a Schema.

On-disk layout (no nulls in V1), fields in schema order:
  INTEGER : 4-byte signed little-endian
  VARCHAR : 4-byte unsigned length (little-endian) + UTF-8 bytes

LATER: null bitmap, compression, alignment packing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from pebble.schema import Schema
from pebble.types import TypeId, Value

_INT_STRUCT = struct.Struct("<i")
_LEN_STRUCT = struct.Struct("<I")


@dataclass(slots=True)
class Tuple:
    values: list[Value]

    def get_value(self, idx: int) -> Value:
        return self.values[idx]

    def to_bytes(self, schema: Schema) -> bytes:
        if len(self.values) != schema.column_count():
            raise ValueError(
                f"value count {len(self.values)} != schema width {schema.column_count()}"
            )
        out = bytearray()
        for i, col in enumerate(schema.columns):
            value = self.values[i]
            out.extend(_encode_value(col.type_id, value))
        return bytes(out)

    @classmethod
    def from_bytes(cls, schema: Schema, data: bytes) -> Tuple:
        values: list[Value] = []
        offset = 0
        for col in schema.columns:
            value, offset = _decode_value(col.type_id, data, offset)
            values.append(value)
        if offset != len(data):
            raise ValueError(f"trailing bytes after tuple decode: {len(data) - offset}")
        return cls(values=values)

    @classmethod
    def from_values(cls, schema: Schema, values: list[Value]) -> Tuple:
        """Validate types against schema, then wrap."""
        if len(values) != schema.column_count():
            raise ValueError(
                f"value count {len(values)} != schema width {schema.column_count()}"
            )
        for i, col in enumerate(schema.columns):
            _check_type(col.type_id, values[i], col.name)
        return cls(values=list(values))


def _check_type(type_id: TypeId, value: Value, col_name: str) -> None:
    if type_id is TypeId.INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"column {col_name}: expected int, got {type(value).__name__}")
        if value < -2_147_483_648 or value > 2_147_483_647:
            raise OverflowError(f"column {col_name}: int out of int32 range: {value}")
    elif type_id is TypeId.VARCHAR:
        if not isinstance(value, str):
            raise TypeError(f"column {col_name}: expected str, got {type(value).__name__}")


def _encode_value(type_id: TypeId, value: Value) -> bytes:
    if type_id is TypeId.INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"expected int, got {type(value).__name__}")
        if value < -2_147_483_648 or value > 2_147_483_647:
            raise OverflowError(f"int out of int32 range: {value}")
        return _INT_STRUCT.pack(value)

    if type_id is TypeId.VARCHAR:
        if not isinstance(value, str):
            raise TypeError(f"expected str, got {type(value).__name__}")
        encoded = value.encode("utf-8")
        return _LEN_STRUCT.pack(len(encoded)) + encoded

    raise ValueError(f"unsupported type: {type_id}")


def _decode_value(type_id: TypeId, data: bytes, offset: int) -> tuple[Value, int]:
    if type_id is TypeId.INTEGER:
        end = offset + _INT_STRUCT.size
        if end > len(data):
            raise ValueError("truncated INTEGER")
        (value,) = _INT_STRUCT.unpack_from(data, offset)
        return value, end

    if type_id is TypeId.VARCHAR:
        end_len = offset + _LEN_STRUCT.size
        if end_len > len(data):
            raise ValueError("truncated VARCHAR length")
        (length,) = _LEN_STRUCT.unpack_from(data, offset)
        start = end_len
        end = start + length
        if end > len(data):
            raise ValueError("truncated VARCHAR payload")
        return data[start:end].decode("utf-8"), end

    raise ValueError(f"unsupported type: {type_id}")


# High level working if this code 

# Think of this code as a **translator** for a database system.

# In a database, a **Tuple** represents a single row of data (like a row in an Excel spreadsheet). 
# While Python prefers working with clean objects like numbers (`42`) and text (`"Alice"`), 
# a hard drive or storage system can only read and write **raw binary bytes** (`0`s and `1`s).

# This module bridges that gap.
# It takes a row of Python values and converts it into bytes to save to disk, 
# and reads raw bytes back into Python values when you want to look at them.

# --- The 3 Big Jobs of This Code

# 1. Holding Data in Memory

#     The `Tuple` class acts as a container. 
#     It simply holds a list of Python values (e.g., `[101, "Alice"]`) and 
#     lets you look up a value by its column index using `get_value(idx)`.

# 2. Translation (Encoding & Decoding)

#   * Packing (`to_bytes`): Takes every value in the row and 
#     translates it into raw binary data according to a defined rulebook (the `Schema`).

#   * Unpacking (`from_bytes`): Reads a stream of binary data, cuts it into pieces using the `Schema` 
#     as a guide, and turns those pieces back into human-readable Python numbers and text.

# 3. Safety Checks (Validation)

#     Before letting bad data into the system, the code makes sure:

#     * You provided the exact number of values the table schema expects.
#     * Numbers are actually integers and fit within standard limits (32-bit integer limits).
#     * Text columns actually contain strings.

# --- How Data Types Are Translated

# The code handles two main database types:

# | Data Type            How It Is Saved in Bytes |

# | INTEGER              Converted into a fixed 4-byte block. |

# | VARCHAR (Text)       First writes a 4-byte number indicating text length, 
#                        immediately followed by the actual text bytes. |

# Because strings can be short or long, storing the length first acts like a bookmark 
# so the reader knows exactly where the string ends and where the next column begins!

# --- Summary

# This file is the core **serialization engine** for a row of data. 
# It ensures that data remains strictly valid, translates memory objects into flat byte streams for 
# storage, and seamlessly reconstructs those byte streams back into Python objects.
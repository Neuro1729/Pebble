"""Step 1: Schema + Tuple round-trip in memory."""

from __future__ import annotations

import pytest

from pebble.schema import Column, Schema
from pebble.tuple import Tuple
from pebble.types import TypeId


def test_tuple_round_trip() -> None:
    schema = Schema(
        [
            Column("id", TypeId.INTEGER),
            Column("name", TypeId.VARCHAR),
        ]
    )
    original = Tuple.from_values(schema, [42, "pebble"])
    raw = original.to_bytes(schema)
    restored = Tuple.from_bytes(schema, raw)

    assert restored.values == [42, "pebble"]
    assert restored.get_value(0) == 42
    assert restored.get_value(1) == "pebble"


def test_empty_string_and_negative_int() -> None:
    schema = Schema(
        [
            Column("n", TypeId.INTEGER),
            Column("s", TypeId.VARCHAR),
        ]
    )
    original = Tuple.from_values(schema, [-1, ""])
    restored = Tuple.from_bytes(schema, original.to_bytes(schema))
    assert restored.values == [-1, ""]


def test_schema_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Schema([Column("a", TypeId.INTEGER), Column("a", TypeId.VARCHAR)])


def test_wrong_type_rejected() -> None:
    schema = Schema([Column("id", TypeId.INTEGER)])
    with pytest.raises(TypeError):
        Tuple.from_values(schema, ["not-an-int"])

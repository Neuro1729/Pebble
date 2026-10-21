"""Column types and runtime values for V1.

V1 supports INTEGER and VARCHAR only.
LATER: BOOLEAN, FLOAT, NULL bitmap, etc.
"""

from __future__ import annotations

from enum import Enum, auto


class TypeId(Enum):
    INTEGER = auto()
    VARCHAR = auto()


# Decoded cell value in memory.
Value = int | str

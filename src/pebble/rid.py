"""Record identifier: (page_id, slot_num) into a table heap page."""

from __future__ import annotations

from dataclasses import dataclass

from pebble.config import INVALID_PAGE_ID


@dataclass(frozen=True, slots=True)
class RID:
    page_id: int = INVALID_PAGE_ID
    slot_num: int = 0

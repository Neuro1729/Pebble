"""Record identifier: (page_id, slot_num) into a table heap page."""

from __future__ import annotations

from dataclasses import dataclass

from pebble.config import INVALID_PAGE_ID


@dataclass(frozen=True, slots=True)
class RID:
    page_id: int = INVALID_PAGE_ID
    slot_num: int = 0



# Hight level overview of the rid.py 

# Think of this code as generating a physical address or
# GPS coordinates for a specific row of data in a database.

# In a database engine, data isn't stored in one giant file. 
# Instead, it is broken up into chunks called Pages (like chapters in a book), 
# and inside each page, records are placed into 
# specific Slots (like line numbers on a page).

# --- What does RID mean ?

# RID stands for Record Identifier.

# If the database needs to find a specific row instantly without scanning through everything,
# it uses an RID to pinpoint the exact location:

# 1. page_id  : Which page/block is the data in ? (e.g., Building #5)
# 2. slot_num : Which slot inside that page holds the record ? (e.g., Apartment #12)

# Together, (page_id, slot_num) give every single record a unique location tag.

# --- Key Design Features

# Lightweight Container      : It uses Python's `@dataclass` 
#                              to cleanly hold these two numbers without extra clutter.

# Unchangeable (frozen=True) : Once a record's address is created, it is "frozen." 
#                              This prevents accidental changes to where a record lives in memory.

# Safe Defaults              : If you create an RID without giving it specific values,
#                              it defaults to an INVALID_PAGE_ID — a safe placeholder showing that it hasn't been
#                              assigned a real location yet.

# --- Summary

# While tuple.py (the previous file) handles what the data actually contains,
# rid.py handles  where that data is physically stored in the database!
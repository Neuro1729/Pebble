"""B+Tree index operations on buffer-pool pages (V2 step 5).

Unique int32 keys. Insert splits full leaves/internals (copy-up on leaf,
push-up on internal). Delete is naive: remove from leaf only (no merge /
redistribute yet; lookup stays correct; nodes may be underfull).
"""

from __future__ import annotations

from pebble.bplus_page import (
    BPlusInternalPage,
    BPlusLeafPage,
    BPlusPageType,
    INTERNAL_MAX_SIZE,
    LEAF_MAX_SIZE,
    page_type_of,
)
from pebble.buffer_pool import BufferPoolManager
from pebble.config import INVALID_PAGE_ID
from pebble.rid import RID


class BPlusTree:
    def __init__(
        self,
        bpm: BufferPoolManager,
        root_page_id: int,
        *,
        leaf_max_size: int = LEAF_MAX_SIZE,
        internal_max_size: int = INTERNAL_MAX_SIZE,
    ) -> None:
        if leaf_max_size < 2:
            raise ValueError("leaf_max_size must be >= 2 for splits")
        if internal_max_size < 3:
            raise ValueError("internal_max_size must be >= 3 for splits")
        self._bpm = bpm
        self._root_page_id = root_page_id
        self._leaf_max = leaf_max_size
        self._internal_max = internal_max_size

    @classmethod
    def create(
        cls,
        bpm: BufferPoolManager,
        *,
        leaf_max_size: int = LEAF_MAX_SIZE,
        internal_max_size: int = INTERNAL_MAX_SIZE,
    ) -> BPlusTree:
        with bpm.new_page_write() as guard:
            BPlusLeafPage.initialize(guard.page, max_size=leaf_max_size)
            root_id = guard.page_id
        return cls(
            bpm,
            root_id,
            leaf_max_size=leaf_max_size,
            internal_max_size=internal_max_size,
        )

    @property
    def root_page_id(self) -> int:
        return self._root_page_id

    def search(self, key: int) -> RID | None:
        """Point lookup; None if key is absent."""
        page_id = self._root_page_id
        while True:
            with self._bpm.fetch_page_read(page_id) as guard:
                typ = page_type_of(guard.page)
                if typ is BPlusPageType.INTERNAL:
                    page_id = BPlusInternalPage(guard.page).lookup(key)
                    continue
                if typ is BPlusPageType.LEAF:
                    leaf = BPlusLeafPage(guard.page)
                    idx = leaf.find_key(key)
                    return None if idx is None else leaf.rid_at(idx)
                raise ValueError(f"bad b+ page type {typ} at {page_id}")

    def insert(self, key: int, rid: RID) -> None:
        """Insert unique (key, rid); splits on overflow."""
        if self.search(key) is not None:
            raise ValueError(f"duplicate key: {key}")

        leaf_id = self._find_leaf_page_id(key)
        with self._bpm.fetch_page_write(leaf_id) as guard:
            leaf = BPlusLeafPage(guard.page)
            if leaf.size() < leaf.max_size():
                leaf.insert_at(leaf.lower_bound(key), key, rid)
                return

        # Leaf full: split (includes the new key), then insert separator upward.
        sep_key, right_id = self._split_leaf_and_insert(leaf_id, key, rid)
        self._insert_into_parent(leaf_id, sep_key, right_id)

    def delete(self, key: int) -> bool:
        """Naive delete: remove from leaf only. Returns False if missing."""
        leaf_id = self._find_leaf_page_id(key)
        with self._bpm.fetch_page_write(leaf_id) as guard:
            leaf = BPlusLeafPage(guard.page)
            idx = leaf.find_key(key)
            if idx is None:
                return False
            leaf.remove_at(idx)
            return True

    def _find_leaf_page_id(self, key: int) -> int:
        page_id = self._root_page_id
        while True:
            with self._bpm.fetch_page_read(page_id) as guard:
                typ = page_type_of(guard.page)
                if typ is BPlusPageType.LEAF:
                    return page_id
                if typ is BPlusPageType.INTERNAL:
                    page_id = BPlusInternalPage(guard.page).lookup(key)
                    continue
                raise ValueError(f"bad b+ page type {typ} at {page_id}")

    def _split_leaf_and_insert(
        self, leaf_id: int, key: int, rid: RID
    ) -> tuple[int, int]:
        """Split full leaf; place ``key``; return (separator, right_page_id)."""
        with self._bpm.fetch_page_write(leaf_id) as left_guard:
            left = BPlusLeafPage(left_guard.page)
            entries = [(left.key_at(i), left.rid_at(i)) for i in range(left.size())]
            entries.append((key, rid))
            entries.sort(key=lambda kv: kv[0])
            mid = len(entries) // 2
            left_entries, right_entries = entries[:mid], entries[mid:]
            old_next = left.next_page_id()
            left.set_size(len(left_entries))
            for i, (k, r) in enumerate(left_entries):
                left.set_at(i, k, r)

        with self._bpm.new_page_write() as right_guard:
            right_id = right_guard.page_id
            right = BPlusLeafPage.initialize(
                right_guard.page, max_size=self._leaf_max, next_page_id=old_next
            )
            right.set_size(len(right_entries))
            for i, (k, r) in enumerate(right_entries):
                right.set_at(i, k, r)
            sep_key = right_entries[0][0]

        with self._bpm.fetch_page_write(leaf_id) as left_guard:
            BPlusLeafPage(left_guard.page).set_next_page_id(right_id)

        return sep_key, right_id

    def _insert_into_parent(
        self, left_id: int, key: int, right_id: int
    ) -> None:
        if left_id == self._root_page_id:
            self._grow_root(left_id, key, right_id)
            return

        parent_id = self._find_parent(self._root_page_id, left_id)
        assert parent_id != INVALID_PAGE_ID

        with self._bpm.fetch_page_write(parent_id) as guard:
            parent = BPlusInternalPage(guard.page)
            child_index = parent.value_index(left_id)
            if parent.size() < parent.max_size():
                parent.insert_after_child(child_index, key, right_id)
                return

        # Parent full: split and push middle key up.
        mid_key, new_right_id = self._split_internal_and_insert(
            parent_id, left_id, key, right_id
        )
        self._insert_into_parent(parent_id, mid_key, new_right_id)

    def _grow_root(self, left_id: int, key: int, right_id: int) -> None:
        with self._bpm.new_page_write() as guard:
            new_root_id = guard.page_id
            root = BPlusInternalPage.initialize(
                guard.page, max_size=self._internal_max
            )
            root.set_size(2)
            root.set_value_at(0, left_id)
            root.set_key_at(1, key)
            root.set_value_at(1, right_id)
        self._root_page_id = new_root_id

    def _find_parent(self, page_id: int, child_id: int) -> int:
        """Return parent of ``child_id`` under subtree ``page_id``, or INVALID."""
        with self._bpm.fetch_page_read(page_id) as guard:
            typ = page_type_of(guard.page)
            if typ is BPlusPageType.LEAF:
                return INVALID_PAGE_ID
            node = BPlusInternalPage(guard.page)
            for i in range(node.size()):
                if node.value_at(i) == child_id:
                    return page_id
            # Recurse into the child that may contain child_id in its subtree.
            # We do not know the key; check each child that is internal/leaf path.
            children = [node.value_at(i) for i in range(node.size())]

        for cid in children:
            found = self._find_parent(cid, child_id)
            if found != INVALID_PAGE_ID:
                return found
        return INVALID_PAGE_ID

    def _split_internal_and_insert(
        self,
        node_id: int,
        left_child_id: int,
        insert_key: int,
        insert_right_id: int,
    ) -> tuple[int, int]:
        """Split full internal after placing the new separator; push mid key up."""
        with self._bpm.fetch_page_write(node_id) as guard:
            node = BPlusInternalPage(guard.page)
            # Build expanded child/key lists including the new separator.
            vals = [node.value_at(i) for i in range(node.size())]
            keys = [node.key_at(i) for i in range(node.size())]  # keys[0] unused
            idx = vals.index(left_child_id)
            # Insert key and right child after idx
            vals.insert(idx + 1, insert_right_id)
            keys.insert(idx + 1, insert_key)

            # Push-up middle key (index mid); left keeps children [0, mid), right [mid, end)
            # For N children after insert, mid child index splits around key at mid.
            mid = len(vals) // 2
            mid_key = keys[mid]
            left_vals = vals[:mid]
            right_vals = vals[mid:]
            left_keys = keys[:mid]  # left_keys[0] unused; separators 1..mid-1
            right_keys = [0] + keys[mid + 1 :]  # drop mid_key from right

            node.set_size(len(left_vals))
            for i, v in enumerate(left_vals):
                node.set_value_at(i, v)
                if i > 0:
                    node.set_key_at(i, left_keys[i])

        with self._bpm.new_page_write() as right_guard:
            right_id = right_guard.page_id
            right = BPlusInternalPage.initialize(
                right_guard.page, max_size=self._internal_max
            )
            right.set_size(len(right_vals))
            for i, v in enumerate(right_vals):
                right.set_value_at(i, v)
                if i > 0:
                    right.set_key_at(i, right_keys[i])

        return mid_key, right_id

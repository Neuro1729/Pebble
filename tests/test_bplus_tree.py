"""V2 step 5: B+Tree insert/split, search, naive delete."""

from __future__ import annotations

from pathlib import Path

import pytest

from pebble.bplus_page import page_type_of, BPlusPageType
from pebble.bplus_tree import BPlusTree
from pebble.buffer_pool import BufferPoolManager
from pebble.disk_manager import DiskManager
from pebble.rid import RID


def test_insert_search_delete_with_splits(tmp_path: Path) -> None:
    db_file = tmp_path / "tree.db"
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=32, disk_manager=disk) as bpm:
            tree = BPlusTree.create(bpm, leaf_max_size=3, internal_max_size=4)
            keys = list(range(0, 40, 2))  # 20 keys → forces leaf + internal splits
            for k in keys:
                tree.insert(k, RID(page_id=k, slot_num=k % 7))

            for k in keys:
                rid = tree.search(k)
                assert rid == RID(page_id=k, slot_num=k % 7)

            assert tree.search(1) is None
            with pytest.raises(ValueError, match="duplicate"):
                tree.insert(4, RID(0, 0))

            assert tree.delete(10) is True
            assert tree.search(10) is None
            assert tree.delete(10) is False

            # Root should have grown past a single leaf
            with bpm.fetch_page_read(tree.root_page_id) as guard:
                assert page_type_of(guard.page) is BPlusPageType.INTERNAL

            root_id = tree.root_page_id
            bpm.flush_all_pages()

    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=32, disk_manager=disk) as bpm:
            tree = BPlusTree(
                bpm, root_id, leaf_max_size=3, internal_max_size=4
            )
            assert tree.search(10) is None
            assert tree.search(20) == RID(page_id=20, slot_num=20 % 7)
            assert tree.search(0) == RID(page_id=0, slot_num=0)


def test_sequential_and_reverse_insert(tmp_path: Path) -> None:
    db_file = tmp_path / "order.db"
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=64, disk_manager=disk) as bpm:
            tree = BPlusTree.create(bpm, leaf_max_size=4, internal_max_size=4)
            for k in range(30, 0, -1):
                tree.insert(k, RID(k, 0))
            for k in range(1, 31):
                assert tree.search(k) == RID(k, 0)

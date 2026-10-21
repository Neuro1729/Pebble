"""V2 step 6: B+Tree leaf iterator / ordered scan."""

from __future__ import annotations

from pathlib import Path

from pebble.bplus_tree import BPlusTree
from pebble.buffer_pool import BufferPoolManager
from pebble.disk_manager import DiskManager
from pebble.rid import RID


def test_full_scan_matches_sorted_keys(tmp_path: Path) -> None:
    db_file = tmp_path / "iter.db"
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=32, disk_manager=disk) as bpm:
            tree = BPlusTree.create(bpm, leaf_max_size=3, internal_max_size=4)
            keys = [17, 3, 9, 1, 12, 5, 20, 8, 15, 11]
            for k in keys:
                tree.insert(k, RID(page_id=k, slot_num=0))

            got = list(tree.scan())
            assert [k for k, _ in got] == sorted(keys)
            assert all(rid == RID(page_id=k, slot_num=0) for k, rid in got)


def test_scan_from_start_key(tmp_path: Path) -> None:
    db_file = tmp_path / "range.db"
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=32, disk_manager=disk) as bpm:
            tree = BPlusTree.create(bpm, leaf_max_size=3, internal_max_size=4)
            for k in range(0, 20):
                tree.insert(k, RID(k, 0))

            got = [k for k, _ in tree.scan(start_key=7)]
            assert got == list(range(7, 20))

            # lower_bound: missing key 6.5 → start at 7
            got2 = [k for k, _ in tree.begin(6)]
            # start_key=6 exists
            assert got2[0] == 6
            got3 = [k for k, _ in tree.begin(21)]
            assert got3 == []


def test_iterator_next_item(tmp_path: Path) -> None:
    db_file = tmp_path / "next.db"
    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=16, disk_manager=disk) as bpm:
            tree = BPlusTree.create(bpm, leaf_max_size=2, internal_max_size=3)
            for k in (1, 2, 3, 4, 5):
                tree.insert(k, RID(k, 1))
            it = tree.begin()
            assert it.next_item() == (1, RID(1, 1))
            assert it.next_item() == (2, RID(2, 1))
            rest = list(it)
            assert [k for k, _ in rest] == [3, 4, 5]

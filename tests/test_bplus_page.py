"""V2 step 4: B+Tree leaf/internal page layout + binary search."""

from __future__ import annotations

from pathlib import Path

from pebble.bplus_page import (
    BPlusInternalPage,
    BPlusLeafPage,
    BPlusPageType,
    bplus_point_lookup,
    page_type_of,
)
from pebble.buffer_pool import BufferPoolManager
from pebble.disk_manager import DiskManager
from pebble.rid import RID


def test_leaf_binary_search_and_dump() -> None:
    from pebble.page import Page

    page = Page(page_id=1)
    leaf = BPlusLeafPage.initialize(page, max_size=8)
    assert page_type_of(page) is BPlusPageType.LEAF

    for i, key in enumerate((10, 20, 30, 40)):
        leaf.insert_at(i, key, RID(page_id=100, slot_num=i))

    assert leaf.find_key(30) == 2
    assert leaf.find_key(15) is None
    assert leaf.lower_bound(25) == 2
    assert leaf.rid_at(2) == RID(page_id=100, slot_num=2)
    assert "10, 20, 30, 40" in leaf.dump()


def test_internal_lookup() -> None:
    from pebble.page import Page

    page = Page(page_id=2)
    node = BPlusInternalPage.initialize(page, max_size=8)
    # children: 10 | 20 | 30   separators 20, 30
    # keys < 20 → 10; 20 <= k < 30 → 20; k >= 30 → 30
    node.set_size(3)
    node.set_value_at(0, 10)
    node.set_key_at(1, 20)
    node.set_value_at(1, 20)
    node.set_key_at(2, 30)
    node.set_value_at(2, 30)

    assert node.lookup(5) == 10
    assert node.lookup(20) == 20
    assert node.lookup(25) == 20
    assert node.lookup(30) == 30
    assert node.lookup(100) == 30
    assert "20->20" in node.dump()


def test_manual_tree_point_lookup(tmp_path: Path) -> None:
    """Root internal → two leaves; search finds RIDs after flush/reopen."""
    db_file = tmp_path / "bplus.db"

    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=8, disk_manager=disk) as bpm:
            # leaf A: keys 1,3,5
            with bpm.new_page_write() as ga:
                leaf_a_id = ga.page_id
                leaf_a = BPlusLeafPage.initialize(ga.page)
                leaf_a.insert_at(0, 1, RID(1, 0))
                leaf_a.insert_at(1, 3, RID(1, 1))
                leaf_a.insert_at(2, 5, RID(1, 2))

            # leaf B: keys 7,9
            with bpm.new_page_write() as gb:
                leaf_b_id = gb.page_id
                leaf_b = BPlusLeafPage.initialize(gb.page)
                leaf_b.insert_at(0, 7, RID(2, 0))
                leaf_b.insert_at(1, 9, RID(2, 1))

            with bpm.fetch_page_write(leaf_a_id) as ga:
                BPlusLeafPage(ga.page).set_next_page_id(leaf_b_id)

            # root: *leaf_a | 7 -> leaf_b
            with bpm.new_page_write() as gr:
                root_id = gr.page_id
                root = BPlusInternalPage.initialize(gr.page)
                root.set_size(2)
                root.set_value_at(0, leaf_a_id)
                root.set_key_at(1, 7)
                root.set_value_at(1, leaf_b_id)

            assert bplus_point_lookup(bpm, root_id, 3) == RID(1, 1)
            assert bplus_point_lookup(bpm, root_id, 7) == RID(2, 0)
            assert bplus_point_lookup(bpm, root_id, 9) == RID(2, 1)
            assert bplus_point_lookup(bpm, root_id, 4) is None

            bpm.flush_all_pages()

    with DiskManager(db_file) as disk:
        with BufferPoolManager(pool_size=8, disk_manager=disk) as bpm:
            assert bplus_point_lookup(bpm, root_id, 5) == RID(1, 2)
            assert bplus_point_lookup(bpm, root_id, 7) == RID(2, 0)

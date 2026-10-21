"""V2 step 2: ArcReplacer (ported from BusTub sample scenarios)."""

from __future__ import annotations

from pathlib import Path

from pebble.arc_replacer import ArcReplacer
from pebble.buffer_pool import BufferPoolManager
from pebble.disk_manager import DiskManager


def test_bustub_sample_eviction_order() -> None:
    # Notation from BusTub: [<-mru_ghost-][<-mru-]![-mfu->][->mfu_ghost->]
    arc = ArcReplacer(7)
    for fid in range(1, 7):
        arc.record_access(fid, fid)
    for fid in range(1, 6):
        arc.unpin(fid)
    arc.pin(6)
    assert arc.size() == 5

    arc.record_access(1, 1)  # → MFU
    assert arc.victim() == 2
    assert arc.victim() == 3
    assert arc.victim() == 4
    assert arc.size() == 2

    arc.record_access(2, 7)  # new page → MRU
    arc.unpin(2)
    arc.record_access(3, 2)  # MRU-ghost hit → MFU, p += 1
    arc.unpin(3)
    assert arc.size() == 4

    arc.record_access(4, 3)
    arc.unpin(4)
    arc.record_access(7, 4)
    arc.unpin(7)
    assert arc.size() == 6

    assert arc.victim() == 5  # still prefer MRU (|mru| >= p)
    assert arc.victim() == 1  # |mru| < p → MFU LRU
    # [(5,_)][p(6), (7,f2)]![(4,f7),(3,f4),(2,f3)][(1,_)]

    arc.record_access(5, 1)  # MFU-ghost hit → MFU, p -= 1
    arc.unpin(5)
    assert arc.size() == 5

    assert arc.victim() == 2  # pinned 6 skipped; MRU victim is page 7 on frame 2


def test_bustub_sample_case4_ghost_trim() -> None:
    arc = ArcReplacer(3)
    for fid in (1, 2, 3):
        arc.record_access(fid, fid)
        arc.unpin(fid)
    assert arc.victim() == 1
    assert arc.victim() == 2
    assert arc.victim() == 3
    assert arc.size() == 0

    # Case 4a: kill MRU-ghost LRU (page 1), add page 4
    arc.record_access(3, 4)
    arc.unpin(3)

    # Page 1 was killed from ghost; re-access is a cold miss → MRU (not ghost hit)
    arc.record_access(2, 1)
    arc.unpin(2)
    assert arc.size() == 2

    # Ghost hit on page 3 → MFU, p = 1
    arc.record_access(1, 3)
    arc.unpin(1)
    assert arc.size() == 3


def test_remove_does_not_create_ghost() -> None:
    arc = ArcReplacer(3)
    for fid, pid in ((0, 30), (1, 31), (2, 32)):
        arc.record_access(fid, pid)
        arc.unpin(fid)
    arc.remove(0)
    assert arc.size() == 2

    # Re-access page 30: no ghost → MRU, not MFU
    arc.record_access(0, 30)
    arc.unpin(0)
    assert arc.victim() == 1
    assert arc.victim() == 2
    assert arc.victim() == 0


def test_bpm_still_evicts_and_persists_with_arc(tmp_path: Path) -> None:
    db_file = tmp_path / "arc_pool.db"
    with DiskManager(db_file) as disk:
        bpm = BufferPoolManager(pool_size=2, disk_manager=disk)

        p0 = bpm.new_page()
        id0 = p0.page_id
        p0.data[0:4] = b"AAAA"
        bpm.unpin_page(id0, is_dirty=True)

        p1 = bpm.new_page()
        id1 = p1.page_id
        p1.data[0:4] = b"BBBB"
        bpm.unpin_page(id1, is_dirty=True)

        p2 = bpm.new_page()
        id2 = p2.page_id
        p2.data[0:4] = b"CCCC"
        bpm.unpin_page(id2, is_dirty=True)

        again = bpm.fetch_page(id0)
        assert bytes(again.data[0:4]) == b"AAAA"
        bpm.unpin_page(id0, is_dirty=False)
        bpm.flush_all_pages()

    with DiskManager(db_file) as disk:
        assert bytes(disk.read_page(id0).data[0:4]) == b"AAAA"
        assert bytes(disk.read_page(id1).data[0:4]) == b"BBBB"
        assert bytes(disk.read_page(id2).data[0:4]) == b"CCCC"

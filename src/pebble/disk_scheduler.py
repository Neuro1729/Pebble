"""Background disk I/O scheduler (BusTub P1-style).

BPM submits read/write/allocate jobs; a single worker thread calls DiskManager
so the file handle stays single-threaded. Callers block on a Future until done.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum, auto
from queue import Queue

from pebble.disk_manager import DiskManager
from pebble.page import Page


class _Op(Enum):
    READ = auto()
    WRITE = auto()
    ALLOCATE = auto()


@dataclass
class _Job:
    op: _Op
    future: Future[object]
    page_id: int | None = None
    page: Page | None = None


class DiskScheduler:
    """Queue + worker thread in front of DiskManager."""

    def __init__(self, disk_manager: DiskManager) -> None:
        self._disk = disk_manager
        self._queue: Queue[_Job | None] = Queue()
        self._closed = False
        self._worker = threading.Thread(
            target=self._run_worker,
            name="pebble-disk-scheduler",
            daemon=True,
        )
        self._worker.start()

    def read_page(self, page_id: int) -> Page:
        """Schedule a read and wait for the loaded Page."""
        fut: Future[object] = Future()
        self._submit(_Job(op=_Op.READ, future=fut, page_id=page_id))
        return fut.result()  # type: ignore[return-value]

    def write_page(self, page: Page) -> None:
        """Schedule a write and wait until it hits DiskManager."""
        fut: Future[object] = Future()
        self._submit(_Job(op=_Op.WRITE, future=fut, page=page))
        fut.result()

    def allocate_page(self) -> int:
        """Schedule allocate (extends file) and wait for the new page_id."""
        fut: Future[object] = Future()
        self._submit(_Job(op=_Op.ALLOCATE, future=fut))
        return fut.result()  # type: ignore[return-value]

    def close(self) -> None:
        """Stop the worker (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._queue.put(None)
        self._worker.join(timeout=5.0)

    def __enter__(self) -> DiskScheduler:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _submit(self, job: _Job) -> None:
        if self._closed:
            raise RuntimeError("DiskScheduler is closed")
        self._queue.put(job)

    def _run_worker(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                if job.op is _Op.READ:
                    assert job.page_id is not None
                    job.future.set_result(self._disk.read_page(job.page_id))
                elif job.op is _Op.WRITE:
                    assert job.page is not None
                    self._disk.write_page(job.page)
                    job.future.set_result(True)
                else:
                    job.future.set_result(self._disk.allocate_page())
            except Exception as exc:  # noqa: BLE001 - forward to waiter
                job.future.set_exception(exc)

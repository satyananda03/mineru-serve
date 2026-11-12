"""Antrean job in-memory dengan satu worker.

Sengaja sederhana: job hanya hidup di memori proses ini dan hilang saat restart. Bagian inilah yang
nanti diganti Redis + Celery: ``submit`` menjadi ``task.delay`` dan ``get`` menjadi pembacaan hasil
task. Isi pekerjaannya (``process``) tidak ikut berubah.
"""
import asyncio
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

QUEUED, RUNNING, SUCCEEDED, FAILED = "queued", "running", "succeeded", "failed"


@dataclass
class Job:
    id: str
    payload: Any
    status: str = QUEUED
    result: dict | None = None
    error: str | None = None
    finished_at: float | None = None


class JobQueue:
    """Job dikerjakan satu per satu oleh ``run`` (thread worker), atau seketika oleh ``run_now``.

    Satu per satu karena inferensi model memakai seluruh mesin: dua parse bersamaan hanya berebut
    memori. ``process(payload)`` adalah coroutine yang mengembalikan hasil job.
    """

    def __init__(self, process: Callable[[Any], Awaitable[dict]], ttl_seconds: float = 3600) -> None:
        self._process = process
        self._ttl_seconds = ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pending: queue.Queue[Job | None] = queue.Queue()

    def submit(self, payload: Any) -> Job:
        """Antrekan job untuk worker; kembali seketika."""
        job = self._new_job(payload)
        self._pending.put(job)
        return job

    def run_now(self, payload: Any) -> Job:
        """Kerjakan job di thread pemanggil, untuk pekerjaan ringan yang tidak perlu menunggu antrean."""
        job = self._new_job(payload)
        self._execute(job, asyncio.run)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def pending(self) -> int:
        return self._pending.qsize()

    def run(self) -> None:
        """Loop worker: kerjakan job sampai ``stop``. Blocking; panggil dari thread worker.

        Satu event loop untuk semua job, supaya objek asyncio milik parser (semaphore) tetap berlaku
        dari job ke job.
        """
        loop = asyncio.new_event_loop()
        try:
            while (job := self._pending.get()) is not None:
                self._execute(job, loop.run_until_complete)
        finally:
            loop.close()

    def stop(self) -> None:
        """Hentikan ``run`` setelah job yang sedang berjalan selesai; job yang masih antre ditinggalkan."""
        self._pending.put(None)

    def _new_job(self, payload: Any) -> Job:
        job = Job(id=uuid.uuid4().hex, payload=payload)
        with self._lock:
            self._drop_expired()
            self._jobs[job.id] = job
        return job

    def _drop_expired(self) -> None:
        """Buang job selesai yang lebih tua dari TTL, supaya hasil lama tidak menumpuk di memori."""
        cutoff = time.monotonic() - self._ttl_seconds
        expired = [job_id for job_id, job in self._jobs.items() if job.finished_at is not None and job.finished_at < cutoff]
        for job_id in expired:
            del self._jobs[job_id]

    def _execute(self, job: Job, run_coroutine: Callable[[Awaitable[dict]], dict]) -> None:
        job.status = RUNNING
        try:
            job.result = run_coroutine(self._process(job.payload))
            job.status = SUCCEEDED
        except Exception as error:
            logger.exception("Job %s gagal", job.id)
            job.error = f"{type(error).__name__}: {error}"
            job.status = FAILED
        finally:
            job.payload = None
            job.finished_at = time.monotonic()

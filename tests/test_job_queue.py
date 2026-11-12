"""Cek antrean job dengan pekerjaan palsu (tanpa model, tanpa jaringan).

Jalankan dari root repo: ``python tests/test_job_queue.py`` (atau ``pytest tests``).
"""
import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.jobs.job_queue import FAILED, QUEUED, SUCCEEDED, JobQueue

_gate = asyncio.Semaphore(1)  # seperti semaphore milik parser: dibuat sekali, dipakai tiap job


async def double(payload):
    if payload == "rusak":
        raise ValueError("file rusak")
    async with _gate:
        await asyncio.sleep(0)
    return {"value": payload * 2}


def wait_until_finished(job, timeout=5.0):
    deadline = time.monotonic() + timeout
    while job.finished_at is None:
        assert time.monotonic() < deadline, f"job masih {job.status} setelah {timeout}s"
        time.sleep(0.01)


def running_queue(**kwargs):
    jobs = JobQueue(double, **kwargs)
    worker = threading.Thread(target=jobs.run, daemon=True)
    worker.start()
    return jobs, worker


def test_submitted_jobs_wait_then_run_in_order_on_one_event_loop():
    jobs = JobQueue(double)
    first, second = jobs.submit(1), jobs.submit(2)
    assert (first.status, second.status, jobs.pending()) == (QUEUED, QUEUED, 2)
    worker = threading.Thread(target=jobs.run, daemon=True)
    worker.start()
    wait_until_finished(second)
    assert (first.status, first.result) == (SUCCEEDED, {"value": 2})
    assert (second.status, second.result) == (SUCCEEDED, {"value": 4})
    assert jobs.get(first.id) is first and first.payload is None
    jobs.stop()
    worker.join(5)
    assert not worker.is_alive()


def test_failed_job_reports_its_error_and_the_worker_keeps_going():
    jobs, worker = running_queue()
    broken, healthy = jobs.submit("rusak"), jobs.submit(3)
    wait_until_finished(healthy)
    assert (broken.status, broken.error, broken.result) == (FAILED, "ValueError: file rusak", None)
    assert healthy.status == SUCCEEDED
    jobs.stop()
    worker.join(5)


def test_run_now_finishes_before_returning_without_a_worker():
    job = JobQueue(double).run_now(5)
    assert (job.status, job.result) == (SUCCEEDED, {"value": 10})


def test_finished_jobs_expire_after_ttl():
    jobs = JobQueue(double, ttl_seconds=0)
    old = jobs.run_now(1)
    time.sleep(0.01)
    new = jobs.run_now(2)  # membuat job baru membuang yang kedaluwarsa
    assert jobs.get(old.id) is None and jobs.get(new.id) is new
    assert jobs.get("tidak-ada") is None


if __name__ == "__main__":
    tests = [check for name, check in list(globals().items()) if name.startswith("test_")]
    for check in tests:
        check()
        print("ok", check.__name__)
    print(f"{len(tests)} cek lolos")

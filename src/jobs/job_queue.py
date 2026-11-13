"""Antrean job dari sisi API: serahkan file ke worker, baca status dan hasil job.

Job dikerjakan worker Celery (``src.jobs.tasks``); status dan hasilnya tersimpan di Redis selama
``JOB_TTL_SECONDS``, jadi tetap ada saat API atau worker restart. File berpindah lewat S3, sehingga
API dan worker tidak perlu berbagi disk. Modul ini tidak mengimpor kode worker.
"""
import asyncio
import logging
import uuid
from pathlib import Path

from celery import states

from src.jobs import parse_job
from src.jobs.celery_app import PARSE_TASK, celery_app
from src.jobs.parse_job import ParseRequest
from src.modules.contract import ParseOptions
from src.storage.s3.objects import upload_fileobj, upload_key

logger = logging.getLogger(__name__)

QUEUED, RUNNING, SUCCEEDED, FAILED = "queued", "running", "succeeded", "failed"

# Celery menjawab PENDING untuk job yang masih antre maupun ID yang tidak pernah ada. State ini
# ditulis saat job dibuat, supaya keduanya bisa dibedakan.
_QUEUED_STATE = "QUEUED"
_STATUS = {_QUEUED_STATE: QUEUED, states.STARTED: RUNNING, states.SUCCESS: SUCCEEDED, states.FAILURE: FAILED}


def _job(job_id: str, status: str, *, result: dict | None = None, error: str | None = None) -> dict:
    return {"job_id": job_id, "status": status, "error": error, "result": result}


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def submit(path: Path, options: ParseOptions) -> dict:
    """Unggah ``path`` ke S3 dan antrekan job untuk worker; kembali seketika dengan status ``queued``."""
    job_id = uuid.uuid4().hex
    key = upload_key(job_id, path.name)
    with open(path, "rb") as file:
        upload_fileobj(file, key)
    celery_app.backend.store_result(job_id, None, _QUEUED_STATE)
    celery_app.send_task(PARSE_TASK, args=[key, path.name, options.tier, options.pages], task_id=job_id)
    return _job(job_id, QUEUED)


def run_now(request: ParseRequest) -> dict:
    """Kerjakan job di thread pemanggil, untuk pekerjaan ringan yang tidak perlu worker.

    Hasilnya ikut disimpan, jadi ``get`` menjawab job ini seperti job lainnya.
    """
    job_id = uuid.uuid4().hex
    try:
        result = asyncio.run(parse_job.run(request))
    except Exception as error:
        logger.exception("Job %s gagal", job_id)
        celery_app.backend.store_result(job_id, error, states.FAILURE)
        return _job(job_id, FAILED, error=_describe(error))
    celery_app.backend.store_result(job_id, result, states.SUCCESS)
    return _job(job_id, SUCCEEDED, result=result)


def get(job_id: str) -> dict | None:
    """Status job, atau ``None`` bila ID tidak dikenal atau hasilnya sudah melewati masa simpan."""
    meta = celery_app.backend.get_task_meta(job_id)
    status = _STATUS.get(meta["status"])
    if status is None:
        return None
    if status == FAILED:
        return _job(job_id, FAILED, error=_describe(meta["result"]))
    return _job(job_id, status, result=meta["result"] if status == SUCCEEDED else None)

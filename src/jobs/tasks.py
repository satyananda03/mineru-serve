"""Sisi worker: task parse.

Worker tidak memuat model. Ia mengunduh file dari S3, menjalankan ``parse_job`` (yang memanggil server
MinerU, VLM, atau unoserver sesuai jenis file), lalu menyimpan hasilnya lewat Celery.
"""
import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from src.core.config import settings
from src.jobs import parse_job
from src.jobs.celery_app import PARSE_TASK, celery_app
from src.jobs.parse_job import ParseRequest
from src.modules.contract import ParseOptions, Tier
from src.storage.s3.objects import delete_object, download_file

logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None


def _event_loop() -> asyncio.AbstractEventLoop:
    """Event loop proses worker ini, satu untuk semua job-nya.

    Objek asyncio milik parser (semaphore, klien model) terikat pada loop tempat ia dibuat, jadi
    loop yang sama dipakai dari job ke job.
    """
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
    return _loop


async def _run_within_time_limit(request: ParseRequest) -> dict:
    """Jalankan job; setelah ``JOB_TIME_LIMIT_SECONDS`` job dibatalkan dan dinyatakan gagal.

    Pembatalan ikut sampai ke server MinerU (``analyze_pdf``), jadi server tidak terus mengerjakan
    dokumen yang hasilnya sudah tidak ditunggu.
    """
    limit = settings.job_time_limit_seconds
    try:
        return await asyncio.wait_for(parse_job.run(request), timeout=limit)
    except TimeoutError:
        raise TimeoutError(f"Job dihentikan setelah melewati batas waktu {limit} detik (JOB_TIME_LIMIT_SECONDS).") from None


@celery_app.task(name=PARSE_TASK, bind=True)
def parse_document(self, key: str, filename: str, tier: Tier, pages: str | None) -> dict:
    """Unduh file unggahan dari S3 (``key``), parse, kembalikan hasil ``parse_job.run``.

    Folder kerja dan objek unggahan dihapus setelahnya, berhasil atau gagal.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="parser_job_"))
    try:
        # Redis mengirim ulang job yang worker-nya berhenti sebelum selesai. Tidak dikerjakan lagi:
        # dokumen yang mematikan worker akan mematikannya lagi, tanpa henti.
        if self.request.delivery_info.get("redelivered"):
            raise RuntimeError("Worker berhenti saat mengerjakan job ini; job tidak diulang otomatis. Kirim ulang filenya.")
        path = work_dir / "upload" / filename
        download_file(key, path)
        request = ParseRequest(path=path, work_dir=work_dir, options=ParseOptions(tier=tier, pages=pages))
        return _event_loop().run_until_complete(_run_within_time_limit(request))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        try:
            delete_object(key)
        except Exception:
            logger.warning("Gagal menghapus unggahan %s dari S3", key, exc_info=True)

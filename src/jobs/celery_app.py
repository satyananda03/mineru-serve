"""Aplikasi Celery layanan parser: antrean dan penyimpan hasil job ada di Redis (``REDIS_URL``).

Dipakai dua pihak. API hanya mengirim task lewat namanya dan membaca hasilnya (``job_queue``); worker
menjalankan ``src.jobs.tasks``. Modul ini tidak mengimpor parser, jadi API tetap ringan.

Worker: ``celery -A src.jobs.celery_app worker --loglevel=info``. Worker tidak memuat model: PDF dan
gambar dibaca server MinerU lewat HTTP. Karena itu pool bawaan Celery (prefork) bisa dipakai, dan
proses job yang macet bisa dihentikan.
"""
from celery import Celery

from src.core.config import settings

QUEUE = "parse"
PARSE_TASK = "parse_document"
# Semua key milik layanan ini di Redis diberi awalan, supaya tidak bertabrakan dengan aplikasi lain
# yang memakai Redis yang sama.
_KEY_PREFIX = "mineru-serve:"
# Batas waktu job berlapis, dari yang paling halus. Tiap lapis harus di atas lapis sebelumnya:
#   1. job_time_limit_seconds : task membatalkan job-nya sendiri, termasuk di server MinerU (``tasks.py``).
#   2. + HARD_LIMIT_MARGIN    : Celery membunuh proses job yang tidak bisa dibatalkan (macet total).
#   3. + REDELIVERY_MARGIN    : Redis menganggap job ditinggal worker-nya dan mengirimnya ulang.
HARD_LIMIT_MARGIN_SECONDS = 60
REDELIVERY_MARGIN_SECONDS = 120

celery_app = Celery("mineru-serve", broker=settings.redis_url, backend=settings.redis_url, include=["src.jobs.tasks"])
celery_app.conf.update(
    task_default_queue=QUEUE,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_concurrency=settings.worker_concurrency,
    # Job baru dianggap selesai setelah task-nya selesai, dan tiap proses worker hanya memegang satu
    # job: job yang antre tetap di Redis, bukan di memori worker yang sedang sibuk.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_time_limit=settings.job_time_limit_seconds + HARD_LIMIT_MARGIN_SECONDS,
    # Status "queued"/"running" memakai masa simpan yang sama dengan hasil, jadi masa simpan harus
    # melewati job terlama; hasil job tersimpan sedikitnya JOB_TTL_SECONDS setelah selesai.
    result_expires=settings.job_ttl_seconds + settings.job_time_limit_seconds + REDELIVERY_MARGIN_SECONDS,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": settings.job_time_limit_seconds + REDELIVERY_MARGIN_SECONDS,
        "global_keyprefix": _KEY_PREFIX,
    },
    result_backend_transport_options={"global_keyprefix": _KEY_PREFIX},
)

"""Aplikasi FastAPI layanan parser dokumen.

Jalankan dari root repo: ``uvicorn src.api.main:app`` atau ``python -m src.api.main``.
Satu proses saja: antrean job ada di memori proses ini, dan tiap proses memuat salinan modelnya sendiri.
"""
import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from src.api.routes.parse import router as parse_router
from src.core.config import settings
from src.core.logging import configure_logging
from src.jobs import parse_job
from src.jobs.job_queue import JobQueue
from src.modules.mineru_parser.runtime import loaded_models
from src.modules.router import SUPPORTED_EXTENSIONS

configure_logging()
logger = logging.getLogger(__name__)

WORKER_STOP_TIMEOUT_SECONDS = 30


def _work(app: FastAPI, jobs: JobQueue) -> None:
    """Thread worker: memuat model MinerU, menahannya di memori, lalu mengerjakan job sampai dihentikan.

    Model dimuat di thread ini karena thread inilah yang memakainya.
    """
    try:
        with loaded_models() as status:
            app.state.model_status = status
            jobs.run()
    except Exception as error:
        logger.exception("Worker parse berhenti")
        app.state.model_status = {"ready": False, "error": f"{type(error).__name__}: {error}"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs = JobQueue(parse_job.run, ttl_seconds=settings.job_ttl_seconds)
    app.state.jobs = jobs
    worker = threading.Thread(target=_work, args=(app, jobs), name="parse-worker", daemon=True)
    worker.start()
    yield
    jobs.stop()
    await asyncio.to_thread(worker.join, WORKER_STOP_TIMEOUT_SECONDS)


app = FastAPI(
    title="Document Parser API",
    description="Parser dokumen lokal: file masuk, content list (text / table / image / equation) beserta layout-nya keluar.",
    version="2.0.0",
    lifespan=lifespan,
)
app.include_router(parse_router)


@app.get("/", summary="Status layanan dan model")
@app.get("/health", summary="Health check")
async def health_check() -> dict[str, Any]:
    """``initializing`` selama model masih dimuat; job yang masuk saat itu menunggu di antrean."""
    status = getattr(app.state, "model_status", None) or {"ready": False}
    return {
        "status": "ok" if status.get("ready") else "initializing",
        "service": "document-parser-api",
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        "jobs_pending": app.state.jobs.pending(),
        "model_singleton": status,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=settings.port, reload=False)

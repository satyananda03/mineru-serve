"""Aplikasi FastAPI layanan parser dokumen.

Jalankan dari root repo: ``python run.py``.
API hanya menerima file dan menjawab status job; parsing dikerjakan worker Celery
(``celery -A src.jobs.celery_app worker``), dan model hanya ada di server MinerU (``src/models``).
"""
import json
import urllib.request
from typing import Any

from fastapi import FastAPI

from src.api.routes.parse import router as parse_router
from src.core.config import settings
from src.core.logging import configure_logging
from src.jobs.celery_app import celery_app
from src.modules.router import SUPPORTED_EXTENSIONS

configure_logging()

WORKER_PING_TIMEOUT_SECONDS = 1
MINERU_HEALTH_TIMEOUT_SECONDS = 2

app = FastAPI(
    title="Multi Document Parser API",
    description="Parser dokumen lokal: file masuk, content list (text / table / image / equation) beserta layout-nya keluar.",
    version="2.0.0",
)
app.include_router(parse_router)


def _mineru_health() -> dict[str, Any]:
    """Keadaan server MinerU: ``reachable`` dan ``device`` yang dipakainya (``cpu`` | ``gpu``; kosong sebelum model dimuat)."""
    try:
        with urllib.request.urlopen(f"{settings.mineru_api_url}/v1/health", timeout=MINERU_HEALTH_TIMEOUT_SECONDS) as response:
            runtime = json.load(response).get("runtime") or {}
        return {"reachable": True, "device": runtime.get("device")}
    except Exception as error:
        return {"reachable": False, "error": type(error).__name__}


@app.get("/", summary="Status layanan, worker, dan server MinerU")
@app.get("/health", summary="Health check")
def health_check() -> dict[str, Any]:
    """``ok`` bila ada worker yang menjawab dan server MinerU terjangkau.

    ``no_worker``: job yang masuk menunggu di antrean. ``mineru_unreachable``: job PDF dan gambar akan gagal.
    """
    mineru = _mineru_health()
    try:
        workers = sorted(celery_app.control.inspect(timeout=WORKER_PING_TIMEOUT_SECONDS).ping() or {})
        status = "no_worker" if not workers else "ok" if mineru["reachable"] else "mineru_unreachable"
    except Exception as error:
        workers, status = [], f"redis_unreachable: {type(error).__name__}"
    return {
        "status": status,
        "service": "document-parser-api",
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        "workers": workers,
        "mineru": mineru,
    }


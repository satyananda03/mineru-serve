"""Aplikasi FastAPI layanan parser dokumen lokal (MinerU).

Jalankan dari root repo: ``uvicorn src.api.main:app`` atau ``python -m src.api.main``.
Satu proses saja: tiap worker uvicorn memuat salinan modelnya sendiri.
"""
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.parse import router as parse_router
from src.core.config import settings
from src.core.logging import configure_logging
from src.modules.mineru_parser.runtime import loaded_models

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Model dimuat sekali saat server menyala dan ditahan di memori sampai server mati."""
    with loaded_models() as status:
        app.state.model_status = status
        yield


app = FastAPI(
    title="MinerU Document Parser API",
    description="Parser PDF lokal berbasis MinerU: PDF masuk, content list (text / table / image / equation) keluar.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(parse_router)


@app.get("/", summary="Status layanan dan model")
@app.get("/health", summary="Health check")
async def health_check() -> dict[str, Any]:
    status = getattr(app.state, "model_status", None) or {"ready": False}
    return {
        "status": "ok" if status.get("ready") else "initializing",
        "service": "mineru-document-parser-api",
        "supported_tiers": {
            "basic": "Default. OCR untuk halaman scan, struktur tabel dan rumus dikenali.",
            "flash": "Hanya text layer PDF; halaman scan keluar sebagai gambar tanpa teks.",
        },
        "model_singleton": status,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=settings.port, reload=False)

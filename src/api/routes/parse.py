"""POST /parse: unggah PDF, terima content list."""
import logging
import shutil
import tempfile
import time
from pathlib import Path

import pymupdf
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from src.modules.mineru_parser import parse_pdf, select_pages
from src.storage.s3 import upload_figures_to_s3

logger = logging.getLogger(__name__)
router = APIRouter()

# flash hanya membaca text layer; basic membiarkan MinerU memilih text layer atau OCR per halaman.
OCR_MODE_BY_TIER = {"flash": "txt", "basic": "auto"}


@router.post("/parse", summary="Parse PDF dengan MinerU (tier: basic | flash)")
@router.post("/api/v1/parse", include_in_schema=False)
def parse_pdf_endpoint(
    file: UploadFile = File(..., description="File PDF"),
    tier: str = Form("basic", description="'basic' (default) atau 'flash'"),
    pages: str | None = Form(None, description="Halaman 1-based, mis. '4', '1-3,8' atau 'all'"),
    tier_query: str | None = Query(None, alias="tier", description="Menimpa tier dari form"),
    pages_query: str | None = Query(None, alias="pages", description="Menimpa pages dari form"),
) -> JSONResponse:
    """Content list dokumen: item ``text``, ``table`` (markdown), ``image`` dan ``equation``.

    Figure diunggah ke S3: ``img_path`` tiap item ``image`` adalah URL-nya.

    - **basic**: OCR untuk halaman scan, struktur tabel dan rumus dikenali.
    - **flash**: hanya text layer PDF; halaman scan keluar sebagai gambar tanpa teks.
    """
    filename = Path(file.filename or "uploaded.pdf").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail=f"'{filename}' bukan PDF. Unggah file .pdf.")
    tier = (tier_query or tier or "basic").strip().lower()
    if tier not in OCR_MODE_BY_TIER:
        raise HTTPException(status_code=400, detail=f"tier='{tier}' tidak valid. Gunakan 'basic' atau 'flash'.")
    ocr_mode = OCR_MODE_BY_TIER[tier]
    pages = pages_query if pages_query is not None else pages

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="mineru_api_") as tmp_dir:
        pdf_path = Path(tmp_dir) / filename
        with open(pdf_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            with pymupdf.open(pdf_path) as pdf:
                page_count = len(pdf)
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"File PDF tidak valid atau rusak: {error}") from error
        try:
            selected = select_pages(pages, page_count)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=f"{error} (dokumen: {page_count} halaman)") from error
        try:
            items = parse_pdf(pdf_path, Path(tmp_dir) / "figures", tier=tier, ocr_mode=ocr_mode, pages=pages)
        except Exception as error:
            logger.exception("Gagal memproses '%s' dengan tier='%s'", filename, tier)
            raise HTTPException(status_code=500, detail=f"Gagal memproses dokumen dengan MinerU: {error}") from error
        try:
            # Crop figure ada di tmp_dir yang terhapus setelah blok ini: klien hanya bisa membukanya lewat S3.
            upload_figures_to_s3([item for item in items if item["type"] == "image"])
        except Exception as error:
            logger.exception("Gagal mengunggah figure '%s' ke S3", filename)
            raise HTTPException(status_code=500, detail=f"Gagal mengunggah figure ke S3: {error}") from error

    elapsed = round(time.perf_counter() - started, 3)
    logger.info(
        "[POST /parse] file='%s' tier='%s' halaman=%d item=%d elapsed=%ss",
        filename, tier, len(selected), len(items), elapsed,
    )
    return JSONResponse(
        content=items,
        headers={
            "X-MinerU-Tier": tier,
            "X-MinerU-Parse-Mode": ocr_mode,
            "X-MinerU-Elapsed-Seconds": str(elapsed),
            "X-MinerU-Elements-Count": str(len(items)),
        },
    )

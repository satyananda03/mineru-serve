"""Crop figure dari halaman PDF: buang yang kecil, simpan sisanya sebagai JPEG yang bisa dibaca VLM.

Aturan dan angkanya sama dengan ``hybrid_rag/ingestion/parser/figures.py`` dan crop figure jalur
Textract (``amazon_textract/content_list.py``). Disalin, bukan diimpor, karena layanan ini repo
terpisah; bila batas VLM di sana berubah, ubah juga di sini.
"""
import io
import uuid
from pathlib import Path
from typing import Sequence

import pymupdf
from PIL import Image

from src.core.config import settings

from .geometry import page_rect

# Ambang FIGURE_MIN_*_PX dihitung pada resolusi ini, sama dengan render jalur Textract.
RENDER_DPI = 400
CROP_PAD_PX = 3
# Sisi panjang gambar ke VLM: teks kecil di dalam figure masih terbaca.
MAX_PIXELS = 3840
# Gateway VLM menolak body dari ~2,5 MB file gambar; 2 MB menyisakan ruang untuk base64 dan prompt.
MAX_BYTES = 2_000_000
JPEG_QUALITIES = (90, 80, 70)


def is_large_enough(width_px: float, height_px: float, area_ratio: float) -> bool:
    """Apakah figure melewati ambang ukuran (piksel pada ``RENDER_DPI``, porsi luas halaman)."""
    return (
        width_px >= settings.figure_min_width_px
        and height_px >= settings.figure_min_height_px
        and area_ratio >= settings.figure_min_area_ratio
    )


def save_for_vlm(image: Image.Image, path: Path) -> Path:
    """Tulis ``image`` sebagai JPEG: sisi panjang ≤ ``MAX_PIXELS``, file ≤ ``MAX_BYTES``.

    Kualitas diturunkan dulu, baru ukurannya, sampai muat.
    """
    image = image.convert("RGB")
    if max(image.size) > MAX_PIXELS:
        image.thumbnail((MAX_PIXELS, MAX_PIXELS), Image.Resampling.LANCZOS)
    while True:
        for quality in JPEG_QUALITIES:
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=quality)
            if buffer.tell() <= MAX_BYTES:
                path.write_bytes(buffer.getvalue())
                return path
        image = image.resize(
            (max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)), Image.Resampling.LANCZOS
        )


def crop_figure(page: pymupdf.Page, bbox: Sequence[float], image_dir: str, page_idx: int) -> str | None:
    """Simpan area ``bbox`` halaman sebagai JPEG; path absolutnya, atau None bila terlalu kecil."""
    rect = page_rect(page, bbox)
    scale = RENDER_DPI / 72
    area_ratio = rect.get_area() / page.rect.get_area()
    if not is_large_enough(rect.width * scale, rect.height * scale, area_ratio):
        return None
    pad = CROP_PAD_PX / scale
    clip = pymupdf.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad) & page.rect
    pixmap = page.get_pixmap(clip=clip, dpi=RENDER_DPI, colorspace=pymupdf.csRGB, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    directory = Path(image_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return str(save_for_vlm(image, directory / f"figure_p{page_idx}_{uuid.uuid4().hex[:8]}.jpg"))

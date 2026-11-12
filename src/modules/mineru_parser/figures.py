"""Crop figure dari halaman PDF, sama seperti crop figure jalur Textract (``amazon_textract/content_list.py``).

Aturan ukuran dan penyimpanan ada di ``src/modules/figures.py``, dipakai semua parser.
"""
import uuid
from pathlib import Path
from typing import Sequence

import pymupdf
from PIL import Image

from src.modules.figures import is_large_enough, save_for_vlm

from .geometry import page_rect

# Ambang FIGURE_MIN_*_PX dihitung pada resolusi ini, sama dengan render jalur Textract.
RENDER_DPI = 400
CROP_PAD_PX = 3


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

"""bbox MinerU (ternormalisasi 0-1) dan halaman PDF (PyMuPDF, satuan point)."""
from typing import Iterable, Sequence

import pymupdf


def page_rect(page: pymupdf.Page, bbox: Sequence[float]) -> pymupdf.Rect:
    """bbox ternormalisasi → Rect dalam point pada ``page``."""
    area = page.rect
    return pymupdf.Rect(
        area.x0 + bbox[0] * area.width,
        area.y0 + bbox[1] * area.height,
        area.x0 + bbox[2] * area.width,
        area.y0 + bbox[3] * area.height,
    )


def union_bbox(bboxes: Iterable[Sequence[float] | None]) -> list[float] | None:
    """Kotak terkecil yang memuat semua bbox; None bila tidak ada satu pun."""
    known = [bbox for bbox in bboxes if bbox]
    if not known:
        return None
    return [
        min(bbox[0] for bbox in known),
        min(bbox[1] for bbox in known),
        max(bbox[2] for bbox in known),
        max(bbox[3] for bbox in known),
    ]


def text_in_bbox(page: pymupdf.Page, bbox: Sequence[float] | None) -> str:
    """Teks dari text layer PDF di dalam bbox; "" untuk halaman scan tanpa text layer."""
    if not bbox:
        return ""
    return page.get_text("text", clip=page_rect(page, bbox)).strip()


def has_raster_image(page: pymupdf.Page, bbox: Sequence[float] | None) -> bool:
    """Apakah ada gambar raster yang beririsan dengan bbox."""
    if not bbox:
        return False
    rect = page_rect(page, bbox)
    return any(pymupdf.Rect(info["bbox"]).intersects(rect) for info in page.get_image_info())

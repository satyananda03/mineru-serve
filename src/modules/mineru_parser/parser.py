"""PDF → content list lewat MinerU lokal, dalam dua langkah yang bisa dipakai terpisah.

``analyze_pdf`` memberi blok per halaman dalam urutan baca; ``pages_to_items`` membuang perabot
halaman (``page_furniture``) lalu mengubah tiap blok menjadi item (``blocks``). ``parse_pdf`` adalah
keduanya berurutan. Parser gambar memakai kedua langkah sendiri karena ia juga perlu membaca bloknya.
"""
import logging
import time
from pathlib import Path

import pymupdf

from src.modules.contract import ContentItem

from .blocks import PageContext, block_to_items, join_hyphenated_headings
from .page_furniture import content_blocks
from .runtime import configure_environment

logger = logging.getLogger(__name__)

# flash hanya membaca text layer; basic membiarkan MinerU memilih text layer atau OCR per halaman.
OCR_MODE_BY_TIER = {"basic": "auto", "flash": "txt"}


def analyze_pdf(
    pdf_path: str | Path, *, tier: str = "basic", ocr_mode: str | None = None, pages: str | None = None
) -> list:
    """Halaman hasil MinerU (``page.page_idx``, ``page.blocks``) untuk ``pdf_path``.

    ``tier``: ``basic`` membaca halaman scan lewat OCR dan mengenali struktur tabel serta rumus;
    ``flash`` hanya membaca text layer, jadi halaman scan keluar sebagai gambar tanpa teks.
    ``ocr_mode``: ``auto``, ``txt`` atau ``ocr``; bila kosong mengikuti ``tier`` (``OCR_MODE_BY_TIER``).
    ``pages``: pilihan halaman 1-based seperti ``1-3,8``; kosong atau ``all`` berarti semua.
    """
    configure_environment()
    from mineru import parse

    ocr_mode = ocr_mode or OCR_MODE_BY_TIER[tier]
    started = time.perf_counter()
    result = parse(str(pdf_path), page_range=pages or "", tier=tier, ocr_mode=ocr_mode)
    logger.info(
        "MinerU: %s tier=%s ocr_mode=%s halaman=%d dalam %.1fs",
        Path(pdf_path).name, tier, ocr_mode, len(result.pages), time.perf_counter() - started,
    )
    return result.pages


def pages_to_items(pages: list, pdf_path: str | Path, image_dir: str | Path) -> list[ContentItem]:
    """Content list (lihat ``src/modules/contract.py``) dari halaman ``analyze_pdf``.

    Crop figure ditulis ke ``image_dir``. ``page_idx`` item adalah indeks halaman di PDF asli.
    """
    items: list[ContentItem] = []
    with pymupdf.open(pdf_path) as pdf:
        for page_idx, block in content_blocks(pages):
            items.extend(block_to_items(block, PageContext(page_idx, pdf[page_idx], str(image_dir))))
    return join_hyphenated_headings(items)


def parse_pdf(
    pdf_path: str | Path,
    image_dir: str | Path,
    *,
    tier: str = "basic",
    ocr_mode: str | None = None,
    pages: str | None = None,
) -> list[ContentItem]:
    """Parse ``pdf_path`` menjadi content list; pilihan sama dengan ``analyze_pdf``."""
    return pages_to_items(analyze_pdf(pdf_path, tier=tier, ocr_mode=ocr_mode, pages=pages), pdf_path, image_dir)


def select_pages(pages: str | None, page_count: int) -> list[int]:
    """Indeks halaman 0-based yang dipilih ``pages``; ``ValueError`` bila pilihannya tidak valid atau kosong."""
    configure_environment()
    from mineru.errors import InvalidRequestError
    from mineru.parser.page_range import parse_page_range

    try:
        return parse_page_range(pages or "", page_count)
    except InvalidRequestError as error:
        raise ValueError(str(error)) from error

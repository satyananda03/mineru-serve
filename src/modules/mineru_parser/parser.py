"""PDF → content list lewat MinerU lokal.

Alur: ``mineru.parse`` memberi blok per halaman dalam urutan baca → ``page_furniture`` membuang
header berulang, footer, nomor halaman dan kata sambung → ``blocks`` mengubah tiap blok menjadi item.
"""
import logging
import time
from pathlib import Path

import pymupdf

from .blocks import PageContext, block_to_items, join_hyphenated_headings
from .contract import ContentItem
from .page_furniture import content_blocks
from .runtime import configure_environment

logger = logging.getLogger(__name__)


def parse_pdf(
    pdf_path: str | Path,
    image_dir: str | Path,
    *,
    tier: str = "basic",
    ocr_mode: str = "auto",
    pages: str | None = None,
) -> list[ContentItem]:
    """Parse ``pdf_path`` menjadi content list (lihat ``contract``); crop figure ditulis ke ``image_dir``.

    ``tier``: ``basic`` membaca halaman scan lewat OCR dan mengenali struktur tabel serta rumus;
    ``flash`` hanya membaca text layer, jadi halaman scan keluar sebagai gambar tanpa teks.
    ``pages``: pilihan halaman 1-based seperti ``1-3,8``; kosong atau ``all`` berarti semua.
    ``page_idx`` item selalu indeks halaman di PDF asli.
    """
    configure_environment()
    from mineru import parse

    started = time.perf_counter()
    result = parse(str(pdf_path), page_range=pages or "", tier=tier, ocr_mode=ocr_mode)
    items: list[ContentItem] = []
    with pymupdf.open(pdf_path) as pdf:
        for page_idx, block in content_blocks(result.pages):
            items.extend(block_to_items(block, PageContext(page_idx, pdf[page_idx], str(image_dir))))
    items = join_hyphenated_headings(items)
    logger.info(
        "MinerU: %s tier=%s ocr_mode=%s halaman=%d item=%d dalam %.1fs",
        Path(pdf_path).name, tier, ocr_mode, len(result.pages), len(items), time.perf_counter() - started,
    )
    return items


def select_pages(pages: str | None, page_count: int) -> list[int]:
    """Indeks halaman 0-based yang dipilih ``pages``; ``ValueError`` bila pilihannya tidak valid atau kosong."""
    configure_environment()
    from mineru.errors import InvalidRequestError
    from mineru.parser.page_range import parse_page_range

    try:
        return parse_page_range(pages or "", page_count)
    except InvalidRequestError as error:
        raise ValueError(str(error)) from error

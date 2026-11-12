"""File .pdf → content list.

Dek slide ditranskripsi VLM per slide (``slides``); PDF lainnya dibaca MinerU (``mineru_parser``).
Dari ``_parse_pdf`` di router lama hybrid_rag.
"""
import asyncio
from pathlib import Path

import pymupdf

from src.modules.contract import Layout, ParseOptions
from src.modules.mineru_parser import parse_pdf, select_pages
from src.modules.slides.parser import is_slide_deck, parse_slides


def check(path: Path, options: ParseOptions) -> None:
    """``ValueError`` bila PDF tidak bisa dibuka atau pilihan halamannya tidak valid."""
    try:
        with pymupdf.open(path) as pdf:
            page_count = len(pdf)
    except Exception as error:
        raise ValueError(f"File PDF tidak valid atau rusak: {error}") from error
    try:
        select_pages(options.pages, page_count)
    except ValueError as error:
        raise ValueError(f"{error} (dokumen: {page_count} halaman)") from error


async def parse(path: Path, tmp_dir: Path, options: ParseOptions, slides: bool = False) -> tuple[Layout, list[dict]]:
    """Dek slide → VLM per slide; selain itu parser PDF dokumen. Gambar ditulis di ``tmp_dir``.

    ``slides=True`` memaksa jalur slide: ``is_slide_deck`` hanya mengenali halaman 16:9/16:10.
    """
    if slides or is_slide_deck(path):
        return "slides", await parse_slides(path, tmp_dir)
    items = await asyncio.to_thread(
        parse_pdf, path, tmp_dir / "figures", tier=options.tier, pages=options.pages
    )
    return "document", items

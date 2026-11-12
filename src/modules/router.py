"""Satu file jenis apa pun → ``ParseResult``. Tabel ``PARSERS`` memetakan ekstensi ke folder jenisnya.

Porting ``hybrid_rag/ingestion/parser/router.py``: parser jenis mengembalikan content list, router
mencap ``layout`` pada item teks lalu meng-host figure ke S3.
"""
import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, NamedTuple

from src.modules.contract import Layout, ParseOptions, ParseResult
from src.modules.excel import parser as excel_parser
from src.modules.figures import host_figures
from src.modules.images import parser as image_parser
from src.modules.json import parser as json_parser
from src.modules.markdown import parser as markdown_parser
from src.modules.mineru_parser import OCR_MODE_BY_TIER
from src.modules.offices import parser as office_parser
from src.modules.offices.convert import SUPPORTED_EXTENSIONS as OFFICE_EXTENSIONS
from src.modules.pdf import parser as pdf_parser

logger = logging.getLogger(__name__)


class Parser(NamedTuple):
    """Cara satu ekstensi diparse."""

    parse: Callable[[Path, Path, ParseOptions], Awaitable[tuple[Layout, list[dict]]]]
    """``(file, folder kerja, pilihan) → (layout, content list)``; gambar ditulis di folder kerja."""
    has_local_figures: bool
    """Hasilnya bisa memuat ``img_path`` lokal yang harus di-host."""
    light: bool = False
    """Tidak memakai model dan selesai seketika: dikerjakan langsung, tidak masuk antrean."""
    check: Callable[[Path, ParseOptions], None] | None = None
    """Pemeriksaan murah sebelum antre; ``ValueError`` menolak file."""


PARSERS: dict[str, Parser] = {
    "pdf": Parser(pdf_parser.parse, True, check=pdf_parser.check),
    **{ext: Parser(office_parser.parse, True) for ext in OFFICE_EXTENSIONS},
    "xlsx": Parser(excel_parser.parse, True),
    **{ext: Parser(image_parser.parse, True) for ext in image_parser.IMAGE_EXTENSIONS},
    "md": Parser(markdown_parser.parse, False, light=True),
    "markdown": Parser(markdown_parser.parse, False, light=True),
    "txt": Parser(markdown_parser.parse, False, light=True),
    "json": Parser(json_parser.parse, True, light=True),
}
SUPPORTED_EXTENSIONS = frozenset(PARSERS)


def file_type(filename: str) -> str:
    """Ekstensi ``filename`` tanpa titik, huruf kecil; ``ValueError`` bila tidak didukung."""
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in PARSERS:
        raise ValueError(
            f"Tipe file .{ext} tidak didukung. "
            f"Didukung: {', '.join('.' + e for e in sorted(PARSERS))}"
        )
    return ext


def is_light(ext: str) -> bool:
    """Apakah ekstensi ini dikerjakan langsung tanpa masuk antrean."""
    return PARSERS[ext].light


def check_file(path: Path, options: ParseOptions) -> None:
    """Tolak lebih awal yang pasti gagal: ``ValueError`` untuk tier tak dikenal atau file yang ditolak parsernya."""
    if options.tier not in OCR_MODE_BY_TIER:
        raise ValueError(f"tier='{options.tier}' tidak valid. Gunakan {' atau '.join(sorted(OCR_MODE_BY_TIER))}.")
    check = PARSERS[file_type(path.name)].check
    if check:
        check(path, options)


def _with_layout(content_list: list[dict], layout: str) -> list[dict]:
    """Tandai item teks dengan layout dokumen — kunci ``chunking.parent_child_chunker.CHUNKERS`` di hybrid_rag.

    Nilai yang sudah dibawa content list (prebuilt) dihormati.
    """
    for item in content_list:
        if item.get("type", "text") == "text":
            item.setdefault("layout", layout)
    return content_list


async def parse_file(path: Path, tmp_dir: Path, options: ParseOptions) -> ParseResult:
    """Parse ``path`` sesuai ekstensinya; file kerja dan gambar sementara ditulis di ``tmp_dir``."""
    ext = file_type(path.name)
    parser = PARSERS[ext]
    logger.info(f"[parse] starting file={path.name}")
    layout, content_list = await parser.parse(path, tmp_dir, options)
    _with_layout(content_list, layout)
    if parser.has_local_figures:
        await asyncio.to_thread(host_figures, content_list)
    logger.info(f"[parse] prepared {len(content_list)} items from file={path.name}")
    return ParseResult(ext, layout, content_list)

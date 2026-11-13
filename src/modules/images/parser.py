"""Gambar (.jpg/.jpeg/.png) → content list: halaman selalu dibaca (OCR), VLM hanya untuk gambar visual.

Porting ``hybrid_rag/ingestion/parser/image/parse.py``. Alur dan ambangnya sama: gambar dijadikan
PDF satu halaman, dibaca seperti dokumen, lalu porsi teksnya menentukan apakah ia gambar dokumen
(content list biasa) atau gambar visual (gambar utuh untuk VLM + teks yang terbaca). Yang berbeda
hanya pembaca halamannya: MinerU, bukan Textract.
"""
import asyncio
from pathlib import Path

from PIL import Image, ImageOps

from src.modules.contract import Layout, ParseOptions, Tier
from src.modules.figures import _flatten, save_for_vlm
from src.modules.mineru_parser import analyze_pdf, pages_to_items
from src.modules.mineru_parser.blocks import inline_text
from src.modules.mineru_parser.figures import RENDER_DPI

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png")
# Di bawah porsi teks/tabel ini sebuah gambar dianggap visual. Terukur pada blok MinerU: gambar dokumen
# 39-66 %, halaman berisi figure besar 19-28 %, foto dan chart 0-2 % (di layout Textract dulu: 34-57 % dan 0-3 %).
VISUAL_TEXT_COVERAGE = 0.15
# Blok yang dihitung sebagai teks: padanan LAYOUT_TEXT_TYPES + footer/nomor halaman + LAYOUT_TABLE
# milik Textract. Yang tidak dihitung hanya gambar, chart dan teks pinggir.
_TEXTUAL_TYPES = frozenset({
    "text", "doc_title", "paragraph_title", "list", "index", "ref_text", "page_footnote",
    "equation", "code", "header", "footer", "page_number", "table",
})
# Perabot halaman yang dibuang ``pages_to_items``; pada gambar tunggal itu isi, bukan pengulangan.
_MARGIN_TYPES = frozenset({"footer", "page_number"})


def _upright(img: Image.Image) -> Image.Image:
    """EXIF diterapkan (foto HP tidak sampai miring ke OCR/VLM), mode yang bisa disimpan JPEG."""
    return _flatten(ImageOps.exif_transpose(img))


def image_to_pdf(src: Path, dst: Path) -> Path:
    """PDF satu halaman pada ``RENDER_DPI``, jadi crop figure = piksel gambar itu sendiri."""
    with Image.open(src) as img:
        _upright(img).save(dst, "PDF", resolution=RENDER_DPI)
    return dst


def text_coverage(page) -> float:
    """Porsi luas halaman yang dibaca sebagai teks atau tabel (header/footer termasuk)."""
    return sum(
        (block.bbox[2] - block.bbox[0]) * (block.bbox[3] - block.bbox[1])
        for block in page.blocks
        if str(block.type) in _TEXTUAL_TYPES and block.bbox
    )


def margin_items(page) -> tuple[list, list]:
    """Footer dan nomor halaman yang dibuang ``pages_to_items``, sebagai item ``text``.

    Header tidak perlu: satu halaman tidak punya header yang berulang, jadi sudah ikut content
    list. Letaknya, bukan tipenya, yang menentukan tempatnya: di atas tengah halaman ke awal
    content list, di bawah ke akhir.
    """
    top, bottom = [], []
    for block in page.blocks:
        if str(block.type) in _MARGIN_TYPES and block.bbox and (text := inline_text(block.content)):
            item = {"type": "text", "text": text, "page_idx": 0, "bbox": [round(value, 4) for value in block.bbox]}
            (top if block.bbox[1] < 0.5 else bottom).append(item)
    return top, bottom


def _whole_image(src: Path, tmp_dir: Path) -> dict:
    with Image.open(src) as img:
        path = save_for_vlm(_upright(img), tmp_dir / "whole_image.jpg")
    return {"type": "image", "img_path": str(path.resolve()), "image_caption": None,
            "image_footnote": None, "page_idx": 0}


def _content_list(page, src: Path, pdf: Path, tmp_dir: Path) -> list[dict]:
    """Content list dari halaman yang sudah dibaca: OCR untuk gambar dokumen; gambar utuh + kata OCR untuk gambar visual."""
    top, bottom = margin_items(page)
    content_list = [*top, *pages_to_items([page], pdf, tmp_dir / "figures"), *bottom]
    if text_coverage(page) >= VISUAL_TEXT_COVERAGE:
        return content_list
    # Crop figure tergantikan gambar utuh; teks dan tabel tetap — itu data yang sudah terbaca.
    return [_whole_image(src, tmp_dir), *(item for item in content_list if item.get("type") != "image")]


async def parse_image(path: Path, tmp_dir: Path, tier: Tier = "basic") -> list[dict]:
    """Gambar → content list: dijadikan PDF satu halaman, dibaca server MinerU, lalu disusun ``_content_list``."""
    pdf = await asyncio.to_thread(image_to_pdf, path, tmp_dir / f"{path.stem}.pdf")
    (page,) = await analyze_pdf(pdf, tier=tier)
    return await asyncio.to_thread(_content_list, page, path, pdf, tmp_dir)


async def parse(path: Path, tmp_dir: Path, options: ParseOptions) -> tuple[Layout, list[dict]]:
    return "document", await parse_image(path, tmp_dir, options.tier)

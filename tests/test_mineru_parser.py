"""Cek aturan parser MinerU pada blok docvortex asli (tanpa menjalankan model).

Jalankan dari root repo: ``python tests/test_mineru_parser.py`` (atau ``pytest tests``).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
from docvortex import schema
from PIL import Image

from src.modules.mineru_parser import figures
from src.modules.mineru_parser.blocks import PageContext, block_to_items, inline_text, join_hyphenated_headings
from src.modules.mineru_parser.page_furniture import content_blocks
from src.modules.mineru_parser.tables import table_markdown

BODY = (0.1, 0.3, 0.9, 0.4)
TOP = (0.3, 0.05, 0.7, 0.08)
FOOT = (0.7, 0.89, 0.9, 0.91)


def span(text):
    return schema.TextSpan(type="text", content=text)


def text(content, index, bbox=BODY):
    return schema.TextBlock(type="text", index=index, bbox=bbox, content=[span(content)])


def aux(kind, content, index, bbox=TOP):
    return schema.PageAuxTextBlock(type=kind, index=index, bbox=bbox, content=[span(content)])


def page(page_idx, *blocks):
    return schema.PageInfo(page_idx=page_idx, blocks=list(blocks))


def kept_texts(pages):
    return [(page_idx, inline_text(block.content)) for page_idx, block in content_blocks(pages)]


def context(tmp_dir):
    pdf = pymupdf.open()
    return PageContext(0, pdf.new_page(width=600, height=800), tmp_dir)


def test_running_header_dropped_single_header_kept():
    pages = [
        page(0, aux("header", "PRESIDEN REPUBLIK INDONESIA", 0), text("isi satu", 1), aux("page_number", "- 1 -", 2)),
        page(1, aux("header", "PRESIDEN REPUBLIK INDONESIA", 0), aux("header", "FORMULIR 2.0 KONTEKS RISIKO", 1),
             aux("header", "￥", 2), text("isi dua", 3), aux("footer", "SK No 123 A", 4)),
        page(2, aux("header", "PRESIDEN REPUBLIK INDONESIA", 0), text("isi tiga", 1), aux("aside_text", "arXiv:1", 2)),
    ]
    assert kept_texts(pages) == [(0, "isi satu"), (1, "FORMULIR 2.0 KONTEKS RISIKO"), (1, "isi dua"), (2, "isi tiga")]


def test_header_repeated_as_body_text_or_with_other_digits_is_dropped():
    as_title = [
        page(0, schema.DocTitleBlock(type="doc_title", index=0, bbox=TOP, level=1, content=[span("Judul Laporan")])),
        page(1, aux("header", "Judul Laporan", 0), text("isi", 1)),
    ]
    assert kept_texts(as_title) == [(0, "Judul Laporan"), (1, "isi")]
    numbered = [page(0, aux("header", "Hal. 2", 0)), page(1, aux("header", "Hal. 3", 0))]
    assert kept_texts(numbered) == []


def test_catchword_dropped_only_at_page_bottom():
    pages = [page(0, text("(3) Dalam . . .", 0, BODY), text("Pasal 1", 1, FOOT), text("8. Rencana .. .", 2, FOOT))]
    assert kept_texts(pages) == [(0, "(3) Dalam . . ."), (0, "Pasal 1")]


def test_inline_spans_join_without_added_spaces():
    spans = [
        span("install the "),
        schema.HyperlinkSpan(type="hyperlink", url="https://example.org", content=[span("docling")]),
        span(" package, lalu "),
        schema.EquationInlineSpan(type="equation_inline", content="x^2"),
    ]
    assert inline_text(spans) == "install the docling package, lalu $x^2$"


def test_index_is_one_item_and_list_is_one_item_per_entry():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ctx = context(tmp_dir)
        index = schema.IndexBlock(type="index", index=0, bbox=BODY, content=[text("2.3.1 Proyeksi", 0), text("Tahun 2045 .... 56", 1)])
        assert [item["text"] for item in block_to_items(index, ctx)] == ["2.3.1 Proyeksi\nTahun 2045 .... 56"]
        nested = schema.ListBlock(type="list", index=1, bbox=BODY, content=[text("b. kedua", 0)])
        listing = schema.ListBlock(type="list", index=0, bbox=BODY, content=[text("a. pertama", 0), nested])
        assert [item["text"] for item in block_to_items(listing, ctx)] == ["a. pertama", "b. kedua"]


def test_table_keeps_every_caption_and_separates_footnotes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        table = schema.TableBlock(type="table", index=0, bbox=BODY, content=[
            schema.TableAnnotationBlock(type="table_caption", bbox=BODY, content=[span("Tabel 1")]),
            schema.TableAnnotationBlock(type="table_caption", bbox=BODY, content=[span("Contoh Pengisian")]),
            schema.TableBodyBlock(type="table_body", index=0, bbox=BODY, content='<table><tr><td colspan="2">A|B</td></tr><tr><td>1</td><td>2</td></tr></table>'),
            schema.TableAnnotationBlock(type="table_footnote", bbox=BODY, content=[span("*CI: Confidence Interval")]),
        ])
        (item,) = block_to_items(table, context(tmp_dir))
    assert item["table_caption"] == ["Tabel 1", "Contoh Pengisian"]
    assert item["table_footnote"] == ["*CI: Confidence Interval"]
    assert item["table_body"] == "| A/B | A/B |\n| --- | --- |\n| 1 | 2 |"


def test_text_table_becomes_markdown():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ctx = context(tmp_dir)
        body = "No  Sasaran  Target\n1  Layanan  90%"
        assert table_markdown(body, ctx.pdf_page, ctx.pdf_page.rect) == "| No | Sasaran | Target |\n| --- | --- | --- |\n| 1 | Layanan | 90% |"


def figure_block(bbox):
    return schema.ImageBlock(type="image", index=0, bbox=bbox, content=[
        schema.ImageBodyBlock(type="image_body", index=0, bbox=bbox, content=""),
        schema.ImageAnnotationBlock(type="image_caption", bbox=bbox, content=[span("Gambar 3. Alur")]),
    ])


def test_large_figure_is_jpeg_with_list_caption_and_small_one_keeps_its_caption_as_text():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ctx = context(tmp_dir)
        (image,) = block_to_items(figure_block((0.1, 0.1, 0.9, 0.9)), ctx)
        assert image["type"] == "image" and image["image_caption"] == ["Gambar 3. Alur"] and image["image_footnote"] is None
        path = Path(image["img_path"])
        assert path.is_absolute() and path.suffix == ".jpg" and path.stat().st_size <= figures.MAX_BYTES
        with Image.open(path) as saved:
            assert max(saved.size) <= figures.MAX_PIXELS
        (caption,) = block_to_items(figure_block((0.1, 0.1, 0.15, 0.15)), ctx)  # ±0,4 inci: logo
        assert caption["type"] == "text" and caption["text"] == "Gambar 3. Alur"


def test_oversized_image_is_shrunk_to_vlm_limits():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = figures.save_for_vlm(Image.effect_noise((5000, 3000), 80), Path(tmp_dir) / "big.jpg")
        assert path.stat().st_size <= figures.MAX_BYTES
        with Image.open(path) as saved:
            assert max(saved.size) <= figures.MAX_PIXELS


def test_hyphenated_heading_is_joined():
    items = [
        {"type": "text", "text": "Reasoning-", "text_level": 1, "page_idx": 0, "bbox": [0.1, 0.1, 0.5, 0.2]},
        {"type": "text", "text": "Enhanced", "page_idx": 0, "bbox": [0.1, 0.2, 0.3, 0.3]},
        {"type": "text", "text": "paragraf biasa", "page_idx": 0, "bbox": None},
    ]
    assert [item["text"] for item in join_hyphenated_headings(items)] == ["ReasoningEnhanced", "paragraf biasa"]


if __name__ == "__main__":
    tests = [check for name, check in list(globals().items()) if name.startswith("test_")]
    for check in tests:
        check()
        print("ok", check.__name__)
    print(f"{len(tests)} cek lolos")

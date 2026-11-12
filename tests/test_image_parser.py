"""Cek logika parser gambar pada blok docvortex asli (tanpa menjalankan model).

Jalankan dari root repo: ``python tests/test_image_parser.py`` (atau ``pytest tests``).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
from docvortex import schema
from PIL import Image

from src.modules.images import parser as images


def span(text):
    return schema.TextSpan(type="text", content=text)


def text(content, index, bbox):
    return schema.TextBlock(type="text", index=index, bbox=bbox, content=[span(content)])


def aux(kind, content, index, bbox):
    return schema.PageAuxTextBlock(type=kind, index=index, bbox=bbox, content=[span(content)])


def picture(index, bbox):
    return schema.ImageBlock(type="image", index=index, bbox=bbox, content=[
        schema.ImageBodyBlock(type="image_body", index=index, bbox=bbox, content=""),
    ])


def page(*blocks):
    return schema.PageInfo(page_idx=0, blocks=list(blocks))


def test_text_coverage_counts_text_and_page_furniture_but_not_pictures():
    document = page(
        text("paragraf", 0, (0.0, 0.0, 1.0, 0.3)),         # 30% halaman
        aux("footer", "kaki", 1, (0.0, 0.9, 1.0, 1.0)),    # 10%
        picture(2, (0.0, 0.3, 1.0, 0.9)),                  # gambar: tidak dihitung
        aux("aside_text", "arXiv", 3, (0.0, 0.0, 0.05, 1.0)),  # teks pinggir: tidak dihitung
    )
    assert abs(images.text_coverage(document) - 0.40) < 1e-9
    photo = page(picture(0, (0.0, 0.0, 1.0, 1.0)), text("label", 1, (0.1, 0.9, 0.3, 0.95)))
    assert images.text_coverage(photo) < images.VISUAL_TEXT_COVERAGE <= images.text_coverage(document)


def test_margin_items_are_placed_by_position_and_headers_are_left_to_the_content_list():
    blocks = page(
        aux("page_number", "- 7 -", 0, (0.45, 0.02, 0.55, 0.05)),
        aux("header", "KOP SURAT", 1, (0.3, 0.06, 0.7, 0.09)),
        text("isi", 2, (0.1, 0.2, 0.9, 0.8)),
        aux("footer", "Dicetak 2026", 3, (0.1, 0.95, 0.5, 0.98)),
    )
    top, bottom = images.margin_items(blocks)
    assert [item["text"] for item in top] == ["- 7 -"]
    assert [item["text"] for item in bottom] == ["Dicetak 2026"]
    assert all(item["type"] == "text" and item["page_idx"] == 0 for item in [*top, *bottom])


def test_image_becomes_a_one_page_pdf_the_size_of_its_pixels():
    with tempfile.TemporaryDirectory() as tmp_dir:
        source = Path(tmp_dir) / "foto.png"
        Image.new("RGBA", (800, 400), (255, 0, 0, 0)).save(source)  # transparan: harus jadi putih, bukan hitam
        pdf = images.image_to_pdf(source, Path(tmp_dir) / "foto.pdf")
        with pymupdf.open(pdf) as document:
            assert len(document) == 1
            rect = document[0].rect
            scale = images.RENDER_DPI / 72
            assert (round(rect.width * scale), round(rect.height * scale)) == (800, 400)
            pixel = document[0].get_pixmap(dpi=72).pixel(10, 10)
        assert pixel == (255, 255, 255)

        whole = images._whole_image(source, Path(tmp_dir))
        assert whole["type"] == "image" and whole["page_idx"] == 0 and whole["image_caption"] is None
        assert Path(whole["img_path"]).is_absolute() and Path(whole["img_path"]).suffix == ".jpg"


if __name__ == "__main__":
    tests = [check for name, check in list(globals().items()) if name.startswith("test_")]
    for check in tests:
        check()
        print("ok", check.__name__)
    print(f"{len(tests)} cek lolos")

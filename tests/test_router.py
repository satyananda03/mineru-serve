"""Cek router jenis file dan parser ringan (md, txt, json), tanpa model dan tanpa S3.

Jalankan dari root repo: ``python tests/test_router.py`` (atau ``pytest tests``).
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import router
from src.modules.contract import ParseOptions


def parse(name: str, content: str):
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / name
        path.write_text(content, encoding="utf-8")
        return asyncio.run(router.parse_file(path, Path(tmp_dir), ParseOptions()))


def rejected(action) -> str:
    try:
        action()
    except ValueError as error:
        return str(error)
    raise AssertionError("seharusnya ditolak dengan ValueError")


def test_extension_decides_the_parser_and_unknown_ones_are_rejected():
    assert router.file_type("Laporan Akhir.PDF") == "pdf"
    assert router.file_type("catatan.markdown") == "markdown"
    message = rejected(lambda: router.file_type("virus.exe"))
    assert ".exe" in message and ".pdf" in message
    assert rejected(lambda: router.file_type("tanpa_ekstensi"))
    assert router.is_light("md") and router.is_light("json") and not router.is_light("pdf")
    assert {"xlsx", "docx", "doc", "odt", "rtf", "pptx"} <= router.SUPPORTED_EXTENSIONS
    assert not router.is_light("xlsx") and not router.is_light("docx")
    assert {"jpg", "jpeg", "png"} <= router.SUPPORTED_EXTENSIONS and not router.is_light("png")


def test_text_file_is_one_text_item_stamped_with_document_layout():
    for name in ("a.md", "a.markdown", "a.txt"):
        result = parse(name, "# Judul\n\nIsi.")
        assert (result.file_type, result.layout) == (name.split(".")[1], "document")
        assert result.content_list == [{"type": "text", "text": "# Judul\n\nIsi.", "layout": "document"}]


def test_prebuilt_content_list_keeps_its_own_layout_and_non_text_items_get_none():
    items = [
        {"type": "text", "text": "dari sheet", "layout": "sheet", "page_idx": "Rekap"},
        {"type": "text", "text": "biasa", "page_idx": 0},
        {"type": "table", "table_body": "| a |\n| --- |", "table_caption": None, "table_footnote": None, "page_idx": 0},
    ]
    result = parse("siap.json", json.dumps(items))
    assert (result.file_type, result.layout) == ("json", "document")
    assert [item.get("layout") for item in result.content_list] == ["sheet", "document", None]


def test_spreadsheet_is_parsed_per_sheet_with_sheet_layout():
    from openpyxl import Workbook

    with tempfile.TemporaryDirectory() as tmp_dir:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Rekap"
        for row in (["Metrik", "Nilai"], ["Total layanan", 12], ["Terpetakan", 3]):
            sheet.append(row)
        path = Path(tmp_dir) / "rekap.xlsx"
        workbook.save(path)
        result = asyncio.run(router.parse_file(path, Path(tmp_dir), ParseOptions()))
    assert (result.file_type, result.layout) == ("xlsx", "sheet")
    (table,) = result.content_list
    assert (table["type"], table["page_idx"]) == ("table", "Rekap")
    assert table["table_body"].splitlines()[0] == "| Metrik | Nilai |" and "| Total layanan | 12 |" in table["table_body"]


def test_json_that_is_not_a_content_list_is_rejected():
    assert "array of object" in rejected(lambda: parse("salah.json", json.dumps({"type": "text"})))


def test_check_rejects_unknown_tier_broken_pdf_and_pages_outside_the_document():
    with tempfile.TemporaryDirectory() as tmp_dir:
        text = Path(tmp_dir) / "a.md"
        text.write_text("x")
        router.check_file(text, ParseOptions())
        assert "tier='turbo'" in rejected(lambda: router.check_file(text, ParseOptions(tier="turbo")))

        broken = Path(tmp_dir) / "rusak.pdf"
        broken.write_text("bukan pdf")
        assert "tidak valid atau rusak" in rejected(lambda: router.check_file(broken, ParseOptions()))

        import pymupdf

        pdf = Path(tmp_dir) / "dua_halaman.pdf"
        with pymupdf.open() as document:
            document.new_page()
            document.new_page()
            document.save(pdf)
        router.check_file(pdf, ParseOptions(pages="1-2"))
        assert "2 halaman" in rejected(lambda: router.check_file(pdf, ParseOptions(pages="9")))


if __name__ == "__main__":
    tests = [check for name, check in list(globals().items()) if name.startswith("test_")]
    for check in tests:
        check()
        print("ok", check.__name__)
    print(f"{len(tests)} cek lolos")

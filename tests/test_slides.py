"""Cek parser slides tanpa memanggil VLM: deteksi dek, susunan item, tanya ulang, dan isi prompt.

Jalankan dari root repo: ``python tests/test_slides.py`` (atau ``pytest tests``).
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
from pydantic import ValidationError

from src.modules.slides import parser as slides
from src.modules.slides import transcriber
from src.modules.slides.transcriber import SlideTable, SlideTranscription


def pdf_with_pages(tmp_dir: str, name: str, sizes: list[tuple[int, int]]) -> Path:
    path = Path(tmp_dir) / name
    with pymupdf.open() as document:
        for width, height in sizes:
            document.new_page(width=width, height=height)
        document.save(path)
    return path


def test_widescreen_pdf_is_a_slide_deck_and_portrait_or_mixed_is_not():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wide, portrait = (960, 540), (595, 842)
        assert slides.is_slide_deck(pdf_with_pages(tmp_dir, "dek.pdf", [wide] * 5))
        assert not slides.is_slide_deck(pdf_with_pages(tmp_dir, "laporan.pdf", [portrait] * 5))
        assert not slides.is_slide_deck(pdf_with_pages(tmp_dir, "campur.pdf", [wide] * 3 + [portrait] * 2))  # 60% < 80%
        broken = Path(tmp_dir) / "rusak.pdf"
        broken.write_text("bukan pdf")
        assert not slides.is_slide_deck(broken)


def test_slide_becomes_one_text_item_with_its_image_then_one_table_per_grid():
    transcription = SlideTranscription(
        markdown="# Judul Slide\n- butir",
        tables=[
            SlideTable(caption="Target 2026", columns=["Indikator", "Nilai"], rows=[["A|B", "90%"], ["C", "80%", "ekstra"]], footnotes=["Sumber: BPS"]),
            SlideTable(caption="Kosong", columns=["x"], rows=[]),
        ],
    )
    text, table = slides.slide_items(transcription, 4, "/tmp/slide_4.jpg")
    assert text == {"type": "text", "text": "# Judul Slide\n- butir", "page_idx": 4, "img_path": "/tmp/slide_4.jpg"}
    assert (table["type"], table["page_idx"], table["table_caption"], table["table_footnote"]) == ("table", 4, ["Target 2026"], ["Sumber: BPS"])
    # Baris yang lebih lebar dari header menambah kolom kosong; "|" di dalam sel di-escape.
    assert table["table_body"].splitlines() == [
        "| Indikator | Nilai |  |",
        "| --- | --- | --- |",
        "| A\\|B | 90% |  |",
        "| C | 80% | ekstra |",
    ]
    assert slides.slide_items(SlideTranscription(markdown="  ", tables=[]), 0, "x.jpg") == []


def test_coverage_is_the_share_of_reference_words_found_in_the_transcript():
    assert slides._coverage("Rencana Kegiatan Tahun Anggaran", "rencana kegiatan lain") == 0.5
    assert slides._coverage("a b c", "apa saja") == 1.0  # tanpa kata > 3 huruf tidak ada yang bisa hilang


class FakeModel:
    """Model yang membalas urutan jawaban; exception dilempar, lainnya dikembalikan."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def invalid_output() -> ValidationError:
    try:
        SlideTranscription.model_validate({"tables": "bukan list"})
    except ValidationError as error:
        return error
    raise AssertionError("seharusnya tidak valid")


def test_invalid_reply_is_asked_again_once_with_the_error():
    good = SlideTranscription(markdown="ok")
    model = FakeModel([invalid_output(), good])
    assert asyncio.run(transcriber._ask(model, ["pesan"])) is good
    first, second = model.calls
    assert first == ["pesan"] and second[0] == "pesan" and len(second) == 2
    assert "does not match the required output schema" in second[1].content

    twice_wrong = FakeModel([invalid_output(), invalid_output()])
    try:
        asyncio.run(transcriber._ask(twice_wrong, ["pesan"]))
    except ValidationError:
        assert len(twice_wrong.calls) == 2
    else:
        raise AssertionError("jawaban tidak valid kedua harus diteruskan sebagai error")


def test_prompt_takes_no_glossary_and_forbids_expanding_abbreviations():
    prompt = transcriber._chat_prompt("slide_transcription", with_image=True)
    assert sorted(prompt.input_variables) == ["image_url", "page_number", "reference_text", "style_groups"]
    system, human = prompt.format_messages(page_number=3, reference_text="teks", style_groups="", image_url="data:image/jpeg;base64,AAAA")
    text_block, image_block = human.content
    assert "Never expand, translate or explain one unless its full form is printed on the same slide" in text_block["text"]
    assert "do not expand an abbreviation" in text_block["text"] and "ACRONYMS" not in text_block["text"]
    assert image_block == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}
    assert "Presentation Slide Transcriber" in system.content


def test_latex_backslashes_eaten_by_json_decoding_are_restored():
    assert SlideTranscription(markdown="rumus \x0crac{a}{b} dan \x08eta").markdown == "rumus \\frac{a}{b} dan \\beta"


if __name__ == "__main__":
    tests = [check for name, check in list(globals().items()) if name.startswith("test_")]
    for check in tests:
        check()
        print("ok", check.__name__)
    print(f"{len(tests)} cek lolos")

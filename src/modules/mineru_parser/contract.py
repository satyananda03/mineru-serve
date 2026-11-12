"""Bentuk content list yang dikembalikan parser ini.

Sama dengan kontrak parser PDF hybrid_rag (``hybrid_rag/ingestion/parser/pdf/contract.py``),
jadi chunker dan pipeline multimodal di sana tidak berubah saat parsernya diganti. Dua tambahan,
keduanya diabaikan pembaca yang tidak mengenalnya:

* ``bbox`` di setiap item: ``[x0, y0, x1, y1]`` ternormalisasi 0-1 terhadap halaman.
* item ``equation`` (rumus blok sebagai LaTeX), yang tidak pernah dihasilkan Textract.

Aturan yang dijaga parser:

* Item berurutan sesuai urutan baca. Footer, nomor halaman dan header yang berulang antar
  halaman dibuang; header yang hanya muncul di satu halaman tetap ada karena bisa berupa isi.
* Satu item ``text`` per blok layout (paragraf, butir daftar, heading).
* Heading adalah item ``text`` dengan ``text_level`` (1 = judul dokumen, 2+ = judul bagian).
* Gambar disimpan sebagai JPEG di folder gambar; ``img_path`` absolut. API mengunggahnya ke S3
  (``routes/parse.py``), jadi di respons API ``img_path`` adalah URL.
* ``layout`` tidak diisi di sini: router hybrid_rag yang mencapnya.
"""
from typing import Literal, NotRequired, TypedDict

BBox = list[float]


class TextItem(TypedDict):
    type: Literal["text"]
    text: str
    page_idx: int
    bbox: BBox | None
    text_level: NotRequired[int]


class ImageItem(TypedDict):
    type: Literal["image"]
    img_path: str
    image_caption: list[str] | None
    image_footnote: list[str] | None
    page_idx: int
    bbox: BBox | None


class TableItem(TypedDict):
    type: Literal["table"]
    table_body: str
    """Tabel sebagai markdown."""
    table_caption: list[str] | None
    table_footnote: list[str] | None
    page_idx: int
    bbox: BBox | None


class EquationItem(TypedDict):
    type: Literal["equation"]
    text: str
    """Rumus di dalam ``$$...$$``."""
    page_idx: int
    bbox: BBox | None
    text_format: NotRequired[Literal["latex"]]


ContentItem = TextItem | ImageItem | TableItem | EquationItem

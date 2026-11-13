"""Bentuk hasil parser: content list, dan amplop yang membungkusnya.

Content list sama dengan kontrak hybrid_rag (``hybrid_rag/ingestion/parser/pdf/contract.py``), jadi
chunker dan pipeline multimodal di sana tidak berubah. Dua tambahan dari parser PDF MinerU, keduanya
diabaikan pembaca yang tidak mengenalnya:

* ``bbox`` di item PDF: ``[x0, y0, x1, y1]`` ternormalisasi 0-1 terhadap halaman.
* item ``equation`` (rumus blok sebagai LaTeX), yang tidak pernah dihasilkan Textract.

Aturan yang dijaga setiap parser:

* Item berurutan sesuai urutan baca. Footer, nomor halaman dan header yang berulang antar
  halaman dibuang; header yang hanya muncul di satu halaman tetap ada karena bisa berupa isi.
* Satu item ``text`` per blok layout (paragraf, butir daftar, heading).
* Heading adalah item ``text`` dengan ``text_level`` (1 = judul dokumen, 2+ = judul bagian).
* ``page_idx`` adalah halaman 0-based, atau nama sheet untuk spreadsheet.
* Parser menulis gambar ke folder kerja dengan ``img_path`` lokal; ``router`` mengunggahnya ke S3,
  jadi di hasil akhir ``img_path`` adalah URL.
* Item ``text`` dicap ``layout`` oleh ``router``, bukan oleh parser.
"""
from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

BBox = list[float]
Layout = Literal["document", "slides", "sheet"]
"""Tata letak fisik dokumen; menentukan chunker di hybrid_rag (``parent_child_chunker.CHUNKERS``)."""
Tier = Literal["basic", "flash"]
"""Seberapa dalam MinerU membaca PDF dan gambar. ``basic``: text layer, OCR untuk halaman scan, struktur
tabel dan rumus. ``flash``: hanya text layer, lebih cepat; halaman scan keluar sebagai gambar tanpa teks."""


class TextItem(TypedDict):
    type: Literal["text"]
    text: str
    page_idx: int | str
    bbox: NotRequired[BBox | None]
    text_level: NotRequired[int]
    layout: NotRequired[Layout]
    img_path: NotRequired[str]
    """Hanya item slide: gambar slide utuh."""


class ImageItem(TypedDict):
    type: Literal["image"]
    img_path: str
    image_caption: list[str] | None
    image_footnote: list[str] | None
    page_idx: int | str
    bbox: NotRequired[BBox | None]


class TableItem(TypedDict):
    type: Literal["table"]
    table_body: str
    """Tabel sebagai markdown."""
    table_caption: list[str] | None
    table_footnote: list[str] | None
    page_idx: int | str
    bbox: NotRequired[BBox | None]


class EquationItem(TypedDict):
    type: Literal["equation"]
    text: str
    """Rumus di dalam ``$$...$$``."""
    page_idx: int
    bbox: BBox | None
    text_format: NotRequired[Literal["latex"]]


ContentItem = TextItem | ImageItem | TableItem | EquationItem


@dataclass(frozen=True)
class ParseOptions:
    """Pilihan dari pemanggil. Parser yang tidak mengenal sebuah pilihan mengabaikannya."""

    tier: Tier = "basic"
    pages: str | None = None
    """Pilihan halaman 1-based seperti ``1-3,8`` (PDF); kosong berarti semua."""


@dataclass(frozen=True)
class ParseResult:
    """Yang diterima pemanggil untuk satu file."""

    file_type: str
    """Ekstensi file tanpa titik, huruf kecil."""
    layout: Layout
    content_list: list[ContentItem]

"""Perabot halaman: yang tercetak di halaman tetapi bukan isi dokumen.

Aturannya sama dengan jalur Textract di hybrid_rag
(``amazon_textract/content_list.py``: ``IGNORED_LAYOUT_TYPES`` dan ``_running_header_ids``):

* Footer, nomor halaman dan teks pinggir selalu dibuang.
* Header dibuang hanya bila berulang antar halaman. MinerU melabeli berdasarkan posisi, jadi header
  yang muncul di satu halaman saja bisa berupa isi (``LAMPIRAN ... NOMOR ...``, judul formulir).
* Kata sambung di kaki halaman (``(3) Dalam . . .``) dibuang: ia mengulang awal halaman berikutnya.
"""
import re
from collections import Counter
from typing import Any, Iterator

from .blocks import inline_text

ALWAYS_DROPPED = frozenset({"footer", "page_number", "aside_text"})
# Blok yang teksnya dibandingkan antar halaman untuk mengenali header berulang.
COMPARED_TYPES = frozenset({"text", "doc_title", "paragraph_title", "header"})

# Header tanpa kata seperti ini adalah logo yang terbaca OCR (``￥``, ``大``), bukan isi.
# ponytail: hanya huruf Latin; perluas bila dokumen berhuruf lain perlu dilayani.
REAL_WORD = re.compile(r"[A-Za-z]{3,}")

CATCHWORD_DOTS = re.compile(r"(?:\.\s*){2,}$")
CATCHWORD_MAX_WORDS = 6
CATCHWORD_MIN_TOP = 0.75  # seperempat bawah halaman


def content_blocks(pages: list) -> Iterator[tuple[int, Any]]:
    """``(page_idx, block)`` semua blok tingkat atas yang merupakan isi, dalam urutan baca MinerU."""
    running = _running_headers(pages)
    for page in pages:
        for block in page.blocks:
            if not _is_furniture(block, page.page_idx, running):
                yield page.page_idx, block


def _is_furniture(block: Any, page_idx: int, running: set[tuple[int, int]]) -> bool:
    kind = str(block.type)
    if kind in ALWAYS_DROPPED:
        return True
    if kind == "header":
        return (page_idx, block.index) in running or not REAL_WORD.search(inline_text(block.content))
    return kind == "text" and _is_catchword(block)


def _is_catchword(block: Any) -> bool:
    text = inline_text(block.content)
    return (
        bool(block.bbox)
        and block.bbox[1] >= CATCHWORD_MIN_TOP
        and len(text.split()) <= CATCHWORD_MAX_WORDS
        and bool(CATCHWORD_DOTS.search(text))
    )


def _running_headers(pages: list) -> set[tuple[int, int]]:
    """``(page_idx, block.index)`` blok ``header`` yang berulang antar halaman.

    Berulang bila teksnya ada di blok teks halaman lain (``PRESIDEN REPUBLIK INDONESIA`` dilabeli
    header di satu halaman, judul di halaman lain), atau header halaman lain hanya beda angka
    (``Hal. 2``). Angka tetap dihitung terhadap teks lain: ``Pasal 12`` yang dilabeli header tidak
    boleh cocok dengan ``Pasal 5`` di halaman lain.
    """
    pages_with_text: Counter = Counter()
    pages_with_header: Counter = Counter()
    headers: list[tuple[int, int, str]] = []
    for page in pages:
        keys = {
            block.index: _text_key(inline_text(block.content))
            for block in page.blocks
            if str(block.type) in COMPARED_TYPES
        }
        page_headers = [block.index for block in page.blocks if str(block.type) == "header"]
        pages_with_text.update(set(keys.values()))
        pages_with_header.update({_digits_masked(keys[index]) for index in page_headers})
        headers += [(page.page_idx, index, keys[index]) for index in page_headers]
    return {
        (page_idx, index)
        for page_idx, index, key in headers
        if key and (pages_with_text[key] > 1 or pages_with_header[_digits_masked(key)] > 1)
    }


def _text_key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text).strip().casefold()


def _digits_masked(key: str) -> str:
    return re.sub(r"\d", "0", key)

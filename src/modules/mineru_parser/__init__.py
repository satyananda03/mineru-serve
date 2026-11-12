"""Parser PDF berbasis MinerU lokal: PDF → content list berkontrak sama dengan parser Textract hybrid_rag.

* ``parser``          — ``parse_pdf`` = ``analyze_pdf`` (blok MinerU) lalu ``pages_to_items``
* ``page_furniture``  — header berulang, footer, nomor halaman, kata sambung halaman
* ``blocks``          — blok MinerU → item (text / image / table / equation)
* ``tables``          — badan tabel → markdown
* ``figures``         — crop figure dari halaman PDF
* ``geometry``        — bbox ternormalisasi ↔ halaman PDF
* ``runtime``         — thread dan pemuatan model

Bentuk content list: ``src/modules/contract.py``. Aturan ukuran figure: ``src/modules/figures.py``.
"""
from .parser import OCR_MODE_BY_TIER, analyze_pdf, pages_to_items, parse_pdf, select_pages

__all__ = ["OCR_MODE_BY_TIER", "analyze_pdf", "pages_to_items", "parse_pdf", "select_pages"]

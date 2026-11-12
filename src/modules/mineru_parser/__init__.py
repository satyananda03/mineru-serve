"""Parser PDF berbasis MinerU lokal: PDF → content list berkontrak sama dengan parser Textract hybrid_rag.

* ``parser``          — ``parse_pdf``, pintu masuk dan orkestrasi
* ``page_furniture``  — header berulang, footer, nomor halaman, kata sambung halaman
* ``blocks``          — blok MinerU → item (text / image / table / equation)
* ``tables``          — badan tabel → markdown
* ``figures``         — crop figure, filter ukuran, JPEG layak VLM
* ``geometry``        — bbox ternormalisasi ↔ halaman PDF
* ``runtime``         — thread dan pemuatan model
* ``contract``        — bentuk dan aturan content list
"""
from .parser import parse_pdf, select_pages

__all__ = ["parse_pdf", "select_pages"]

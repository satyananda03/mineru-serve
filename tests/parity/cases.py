"""Kasus uji paritas: halaman terpilih dari dokumen uji, dipotong jadi PDF kecil di ``.work/cases``.

Kedua parser menerima potongan yang persis sama, jadi ``page_idx`` keduanya sejajar.
"""
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
WORK = HERE / ".work"
BASELINE = HERE / "baseline_textract"

T, P1, P2 = "Dokumen Test", "policy_indikator_1", "policy_indikator_2"
CASES = [  # (grup, nama, dokumen sumber, halaman 1-based)
    ("scan", "water_mailing", f"{T}/Dokumen Uji Scanned PDF & OCR/PublicWaterMassMailing.pdf", [1, 2, 3]),
    ("scan", "ccitt", f"{T}/Dokumen Uji Scanned PDF & OCR/ccitt.pdf", [1]),
    ("scan", "graph", f"{T}/Dokumen Uji Scanned PDF & OCR/graph.pdf", [1]),
    ("scan", "linn", f"{T}/Dokumen Uji Scanned PDF & OCR/linn.pdf", [1]),
    ("scan", "skew", f"{T}/Dokumen Uji Scanned PDF & OCR/skew.pdf", [1]),
    ("layout", "attention_1706", f"{T}/Dokumen Uji Variasi Layout/1706.03762v7.pdf", [1, 2, 3, 4]),
    ("layout", "layoutparser_2103", f"{T}/Dokumen Uji Variasi Layout/2103.15348v2.pdf", [1, 2, 3]),
    ("layout", "doclaynet_2206", f"{T}/Dokumen Uji Variasi Layout/2206.01062v1.pdf", [1, 2, 3]),
    ("layout", "docling_2408", f"{T}/Dokumen Uji Variasi Layout/2408.09869v5.pdf", [1, 2, 3]),
    ("layout", "embedded_img_tbl", f"{T}/Dokumen Uji Variasi Layout/embedded-images-tables.pdf", [1]),
    ("layout", "conference_ieee", f"{T}/conference_ieee.pdf", [1, 2, 3]),
    ("tabel", "tbl_2305_pg9", f"{T}/Dokumen Uji Variasi Tabel/2305.03393v1-pg9.pdf", [1]),
    ("tabel", "tbl_column_span", f"{T}/Dokumen Uji Variasi Tabel/column_span_2.pdf", [1]),
    ("tabel", "tbl_health", f"{T}/Dokumen Uji Variasi Tabel/health.pdf", [1]),
    ("tabel", "tbl_multiple", f"{T}/Dokumen Uji Variasi Tabel/multiple_tables.pdf", [1]),
    ("tabel", "tbl_puertos", f"{T}/Dokumen Uji Variasi Tabel/puertos1.pdf", [1]),
    ("policy", "perpres_12_2025", f"{P1}/Perpres Nomor 12 Tahun 2025.pdf", [1, 2, 3, 4, 5, 6, 7]),
    ("policy", "perpres_178_2024", f"{P1}/Perpres Nomor 178 Tahun 2024.pdf", [1, 2, 3, 4]),
    ("policy", "uu_59_2024", f"{P1}/UU Nomor 59 Tahun 2024.pdf", [1, 2, 34, 92, 93]),
    ("policy", "perpres_39_2023", f"{P2}/Perpres Nomor 39 Tahun 2023.pdf", [1, 2, 3]),
    ("policy", "pp_60_2008", f"{P2}/PP Nomor 60 Tahun 2008.pdf", [1, 2, 3, 4]),
    ("policy", "permen_5_2020", f"{P2}/Permen PANRB Nomor 5 Tahun 2020.pdf", [15, 16, 17, 50]),
    ("policy", "brin_2_2024", f"{P2}/Peraturan BRIN Nomor 2 Tahun 2024.pdf", [1, 2, 19, 20]),
    ("policy", "permen_8_2026", f"{P1}/Permen PANRB Nomor 8 Tahun 2026.pdf", [8, 9, 10, 37, 43]),
]


def prepare(names: list[str] | None = None) -> list[dict]:
    """Kasus (semua, atau yang bernama di ``names``) dengan potongan PDF-nya sudah ada di disk."""
    (WORK / "cases").mkdir(parents=True, exist_ok=True)
    cases = []
    for group, name, source, pages in CASES:
        if names and name not in names:
            continue
        pdf = WORK / "cases" / f"{name}.pdf"
        if not pdf.exists():
            with pymupdf.open(ROOT / source) as document:
                document.select([page - 1 for page in pages])
                document.save(pdf, garbage=3, deflate=True)
        cases.append({"group": group, "name": name, "pdf": str(pdf), "pages": pages})
    return cases

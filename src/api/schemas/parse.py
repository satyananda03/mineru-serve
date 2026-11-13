"""Bentuk request dan response endpoint ``/parse``.

Pilihan tetap (``tier``) dikunci di sini, jadi muncul sebagai ``enum`` di OpenAPI dan dropdown di Swagger;
nilai di luarnya dijawab 422. Pemeriksaan yang butuh isi file (ekstensi, halaman, PDF rusak) ada di
``src.modules.router.check_file`` dan dijawab 400.
"""
from typing import Any, Literal

from fastapi import UploadFile
from pydantic import BaseModel, Field, field_validator

from src.modules.contract import Layout, Tier

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class ParseForm(BaseModel):
    """Isi form ``POST /parse`` (multipart/form-data)."""

    file: UploadFile = Field(description="pdf, docx, pptx, xlsx, gambar, md, txt, atau json content list")
    tier: Tier = Field(
        "basic",
        description="Berlaku untuk PDF dan gambar; huruf besar/kecil bebas. "
        "basic: text layer, OCR untuk halaman scan, struktur tabel dan rumus. "
        "flash: hanya text layer, lebih cepat; halaman scan keluar sebagai gambar tanpa teks.",
    )
    pages: str | None = Field(None, description="Halaman PDF 1-based, mis. '4' atau '1-3,8'; kosong = semua")

    @field_validator("tier", mode="before")
    @classmethod
    def _normalize_tier(cls, value: object) -> object:
        """``"BASIC "`` → ``"basic"``: pemanggil tidak perlu menebak penulisan nilainya."""
        return value.strip().lower() if isinstance(value, str) else value


class ParseResult(BaseModel):
    """Hasil job yang berhasil."""

    file_type: str = Field(description="Ekstensi file, mis. 'pdf', 'docx', 'md'")
    layout: Layout = Field(description="Tata letak dokumen: document | slides | sheet")
    # Sengaja dict, bukan ContentItem: item content list .json datang dari pemanggil dan boleh membawa
    # key lain; validasi per item akan membuang key itu diam-diam. Bentuknya: src/modules/contract.py.
    content_list: list[dict[str, Any]] = Field(
        description="Item text / table / image / equation dalam urutan baca (lihat src/modules/contract.py). "
        "img_path figure berupa URL S3."
    )
    elapsed_seconds: float = Field(description="Lama parse di worker, dalam detik")


class ParseJob(BaseModel):
    """Status sebuah job parse; bentuk yang sama dijawab ``POST /parse`` dan ``GET /parse/{job_id}``."""

    job_id: str
    status: JobStatus = Field(description="queued → running → succeeded atau failed")
    error: str | None = Field(None, description="Sebab kegagalan, hanya saat status failed")
    result: ParseResult | None = Field(None, description="Hasil, hanya saat status succeeded")

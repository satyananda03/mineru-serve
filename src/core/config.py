"""Pengaturan layanan, dibaca sekali dari environment (``.env``)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _optional(name: str) -> str | None:
    """Nilai env, atau None bila tidak diset atau kosong (``KEY=`` berarti tidak diset)."""
    return os.getenv(name) or None


@dataclass(frozen=True)
class Settings:
    # Ambang figure: nama dan arti sama dengan hybrid_rag, dalam piksel pada render 400 DPI.
    figure_min_width_px: int = int(os.getenv("FIGURE_MIN_WIDTH_PX") or 600)
    figure_min_height_px: int = int(os.getenv("FIGURE_MIN_HEIGHT_PX") or 600)
    figure_min_area_ratio: float = float(os.getenv("FIGURE_MIN_AREA_RATIO") or 0.01)
    # S3 tempat figure di-host: nama env sama dengan hybrid_rag, jadi satu bucket dipakai bersama.
    s3_bucket: str | None = _optional("S3_BUCKET")
    s3_region: str | None = _optional("S3_REGION")
    s3_access_key_id: str | None = _optional("S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = _optional("S3_SECRET_ACCESS_KEY")
    s3_prefix: str = os.getenv("S3_PREFIX") or "pdf-extractions"
    port: int = int(os.getenv("PORT") or 8000)


settings = Settings()

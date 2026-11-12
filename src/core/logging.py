"""Satu konfigurasi logging untuk API dan CLI."""
import logging


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def get_logger(name: str) -> logging.Logger:
    """Nama yang dipakai kode klien model dari aplikasi host (``src/services``)."""
    return logging.getLogger(name)

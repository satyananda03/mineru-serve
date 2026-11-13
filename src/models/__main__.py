"""Server MinerU layanan ini: ``python -m src.models [flag mineru-kit api-server]``.

Menyiapkan proses (thread, presisi Torch, saklar rumus, penjaga device) lalu menyerahkannya ke ``mineru-kit api-server``
resmi; semua flag-nya diteruskan apa adanya. Inilah satu-satunya proses yang memuat model: worker
memanggilnya lewat HTTP (``MINERU_API_URL``).

Kenapa bukan ``mineru-kit api-server`` langsung atau ``mineru-kit router``: presisi Torch adalah
konstanta modul MinerU, dan saklar rumus mengganti method MinerU: keduanya harus dipasang di proses yang memuat model. Router menyalakan api-server
sebagai proses baru, sehingga pemasangan itu tidak ikut terbawa.
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

from src.core.logging import configure_logging

from .formula import apply_formula_recognition
from .inference import apply_torch_precision, configure_environment
from .loader import check_device

logger = logging.getLogger(__name__)


def flag_value(argv: list[str], flag: str) -> str | None:
    """Nilai ``flag`` di ``argv`` (``--flag nilai`` atau ``--flag=nilai``), atau None bila tidak ada."""
    for index, arg in enumerate(argv):
        if arg == flag:
            return argv[index + 1] if index + 1 < len(argv) else None
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


def default_upload_dir(argv: list[str]) -> list[str]:
    """Tambahkan ``--upload-dir`` bila tidak diberikan: folder tetap per port di folder sementara sistem.

    Tanpa flag itu MinerU 4.2.1 menyimpan unggahan dan hasil di folder kerja proses, bukan folder sementara
    seperti kata bantuannya: ``click.Path(resolve_path=True)`` mengubah bawaan ``""`` menjadi path folder kerja.
    Folder tetap, bukan folder baru per start: retensi MinerU (``--retention-seconds``) membersihkan sisa run
    sebelumnya saat server menyala. Per port, karena MinerU mengunci foldernya untuk satu server.
    """
    if flag_value(argv, "--upload-dir") is not None:
        return argv
    port = flag_value(argv, "--port") or "8000"
    return [*argv, "--upload-dir", str(Path(tempfile.gettempdir()) / f"mineru-serve-{port}")]


def main() -> None:
    configure_logging()
    configure_environment()
    precision = apply_torch_precision()
    formulas = apply_formula_recognition()
    check_device()
    sys.argv[1:] = default_upload_dir(sys.argv[1:])
    logger.info(
        "Server MinerU: presisi Torch=%s | pengenal rumus=%s | device diminta=%s | upload dir=%s",
        precision or "tidak berlaku (backend ONNX, selalu FP32)", "on" if formulas else "off (model tidak dimuat)",
        os.getenv("MINERU_DEVICE_MODE") or "pilihan MinerU", flag_value(sys.argv[1:], "--upload-dir"),
    )
    from mineru.kit.commands.api_server import main as serve

    serve()  # membaca flag dari sys.argv


if __name__ == "__main__":  # MinerU merender PDF di proses anak (multiprocessing spawn): guard ini wajib
    main()

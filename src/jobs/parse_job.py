"""Isi satu job parse: file unggahan → hasil yang dikirim ke pemanggil.

Tidak tahu apa pun tentang antrean, jadi tetap dipakai apa adanya saat antrean diganti Celery.
"""
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from src.modules.contract import ParseOptions
from src.modules.router import parse_file


@dataclass(frozen=True)
class ParseRequest:
    path: Path
    """File unggahan, berada di dalam ``work_dir``."""
    work_dir: Path
    """Folder kerja job: unggahan, file sementara, crop figure. Dihapus setelah job selesai."""
    options: ParseOptions


async def run(request: ParseRequest) -> dict:
    """Parse file; hasilnya ``{file_type, layout, content_list, elapsed_seconds}``.

    Figure sudah di S3 saat ini kembali, jadi folder kerja aman dihapus, berhasil atau gagal.
    """
    started = time.perf_counter()
    try:
        result = await parse_file(request.path, request.work_dir, request.options)
    finally:
        shutil.rmtree(request.work_dir, ignore_errors=True)
    return {
        "file_type": result.file_type,
        "layout": result.layout,
        "content_list": result.content_list,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }

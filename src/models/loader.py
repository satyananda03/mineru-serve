"""Tempat model MinerU dimuat: penjaga device, dijalankan sebelum model dimuat."""
import os


def check_device() -> None:
    """Tolak menyala bila ``MINERU_DEVICE_MODE`` meminta GPU tetapi MinerU akan berjalan di CPU.

    Tanpa ini, server yang tidak mendapat akses GPU diam-diam berjalan di CPU: MinerU hanya memberi
    warning. Tidak memuat model: yang diperiksa hanya keputusan device MinerU untuk proses ini.
    """
    requested = (os.getenv("MINERU_DEVICE_MODE") or "cpu").split(":")[0]
    if requested == "cpu":
        return

    from mineru.model.runtime.device_state import resolve_runtime_device

    if resolve_runtime_device().is_cpu:
        raise RuntimeError(
            f"MINERU_DEVICE_MODE={requested} tetapi MinerU hanya menemukan CPU. "
            "Periksa akses GPU proses ini (driver, NVIDIA Container Toolkit, reservasi device di compose)."
        )

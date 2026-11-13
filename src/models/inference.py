"""Cara model MinerU menghitung: thread dan presisi Torch. Dipasang sebelum model dimuat.

Env milik MinerU dibaca di ``src/models`` (modul ini, ``formula`` dan ``loader``), bukan di ``src/core/config.py``:
env ini hanya berarti di proses yang memuat model, dan API maupun worker tidak memuat model.
"""
import importlib
import os

# precision MinerU (``auto`` | ``fp32`` | ``fp16``) untuk OCR rekognisi dan pengenal rumus.
TORCH_PRECISION_CONSTANTS = (
    ("mineru.model._internal.pytorchocr.base_ocr_v20", "OCR_INFERENCE_PRECISION"),
    ("mineru.model.mfr.pp_formulanet.predict_formula", "MFR_INFERENCE_PRECISION"),
)
TORCH_PRECISIONS = ("fp32", "fp16")

def configure_environment() -> None:
    """Default thread dan device, harus terpasang sebelum modul ``mineru`` pertama kali diimpor."""
    cpu_count = os.cpu_count() or 8
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    os.environ.setdefault("MINERU_INTRA_OP_NUM_THREADS", str(max(4, cpu_count // 2)))
    os.environ.setdefault("MINERU_INTER_OP_NUM_THREADS", "2")
    os.environ.setdefault("MINERU_TABLE_DEVICE", "auto")

def apply_torch_precision() -> str | None:
    """Pasang presisi inferensi backend Torch (``TORCH_INFERENCE_PRECISION``); ``None`` pada backend ONNX."""
    precision = (os.getenv("TORCH_INFERENCE_PRECISION") or "fp32").strip().lower()
    if precision not in TORCH_PRECISIONS:
        raise ValueError(f"TORCH_INFERENCE_PRECISION='{precision}' tidak valid. Gunakan fp32 atau fp16.")

    from mineru.model.runtime.device import resolve_small_model_backend

    if resolve_small_model_backend() != "torch":
        return None
    for module_name, constant in TORCH_PRECISION_CONSTANTS:
        module = importlib.import_module(module_name)
        if not hasattr(module, constant):
            raise RuntimeError(f"{module_name}.{constant} tidak ada di MinerU ini: presisi Torch tidak bisa dipasang.")
        setattr(module, constant, precision)
    return precision

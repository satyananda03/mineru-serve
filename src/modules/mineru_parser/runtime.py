"""Runtime model MinerU: pengaturan thread dan pemuatan model satu kali per proses."""
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)


def configure_environment() -> None:
    """Default thread dan device, harus terpasang sebelum modul ``mineru`` pertama kali diimpor.

    ``setdefault``: nilai dari environment atau ``.env`` tetap menang.
    """
    cpu_count = os.cpu_count() or 8
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    os.environ.setdefault("MINERU_INTRA_OP_NUM_THREADS", str(max(4, cpu_count // 2)))
    os.environ.setdefault("MINERU_INTER_OP_NUM_THREADS", "2")
    os.environ.setdefault("MINERU_TABLE_DEVICE", "auto")


def warm_up() -> dict[str, Any]:
    """Muat semua model ke singleton MinerU supaya request pertama tidak menanggung cold start.

    Layout, OCR, klasifikasi dan struktur tabel (wired/wireless), dan pengenal rumus.
    """
    configure_environment()
    import onnxruntime
    from mineru.config import get_config
    from mineru.model.runtime.hybrid import AtomModelSingleton, HybridLocalModelContextSingleton

    started = time.perf_counter()
    config = get_config()
    backend = os.getenv("MINERU_SMALL_MODEL_BACKEND", "").strip().lower()
    if backend in ("onnx", "torch", "auto"):
        config.model.small_backend = backend  # type: ignore[assignment]

    context = HybridLocalModelContextSingleton().get_model()
    for name in ("layout_model", "ocr_model", "table_cls_model", "wireless_table_model", "wired_table_model", "mfr_model"):
        getattr(context, name)  # properti lazy: mengaksesnya memuat modelnya

    elapsed = round(time.perf_counter() - started, 3)
    loaded = [str(key) for key in AtomModelSingleton._models.keys()]
    logger.info("Model MinerU siap dalam %ss | device=%s | models=%d", elapsed, context.device, len(loaded))
    return {
        "ready": True,
        "warmup_seconds": elapsed,
        "device": str(context.device),
        "small_backend": str(context.small_backend),
        "onnx_runtime": {
            "version": onnxruntime.__version__,
            "available_providers": onnxruntime.get_available_providers(),
            "intra_op_num_threads": int(os.environ["MINERU_INTRA_OP_NUM_THREADS"]),
            "inter_op_num_threads": int(os.environ["MINERU_INTER_OP_NUM_THREADS"]),
            "onnx_device": config.model.onnx_device,
        },
        "loaded_models": loaded,
    }


@contextmanager
def loaded_models() -> Iterator[dict[str, Any]]:
    """Muat model dan tahan di memori selama konteks hidup; status warm-up sebagai nilainya.

    ``RuntimeOwner`` adalah "sewa" MinerU atas model: tanpa pemilik, model dilepas setelah tiap parse.
    """
    configure_environment()
    from mineru.model.runtime.ownership import RuntimeOwner, release_runtime_owner, runtime_owner

    owner = RuntimeOwner()
    token = runtime_owner.set(owner)
    try:
        yield warm_up()
    finally:
        runtime_owner.reset(token)
        try:
            release_runtime_owner(owner)
        except Exception:
            logger.warning("Gagal melepas runtime owner MinerU", exc_info=True)

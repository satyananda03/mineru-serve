"""Saklar pengenal rumus MinerU (``FORMULA_RECOGNITION``). Dipasang sebelum model dimuat.

``on`` (bawaan): MinerU tidak diubah. ``off``: model rumus tidak pernah dimuat, jadi memorinya tidak
terpakai (model kecil terbesar: bobotnya ±600 MB).

Saat ``off`` yang berubah hanya isi rumus. Area rumus tetap dideteksi model layout, sehingga OCR, urutan
baca, tabel dan bbox sama persis dengan ``on``. Rumus inline hilang dari kalimatnya; rumus blok diisi
parser dari text layer PDF dan dibuang di halaman scan (``src/modules/mineru_parser/blocks.py``).
"""
import os

FORMULA_LABELS = ("inline_formula", "display_formula")
CHOICES = ("on", "off")

class NoFormulaRecognizer:
    """Pengganti model rumus MinerU: area rumus dari layout dikembalikan dengan LaTeX kosong.

    Keluarannya sama dengan ``batch_predict`` model asli yang tidak mengenali apa pun. MinerU sendiri
    memakai LaTeX kosong untuk rumus yang tidak dikenali, jadi tahap sesudahnya tidak perlu diubah.
    """
    def batch_predict(self, images_mfd_res: list, images: list, batch_size: int = 64, interline_enable: bool = True) -> list:
        labels = FORMULA_LABELS if interline_enable else FORMULA_LABELS[:1]
        return [
            [dict(item, latex="") for item in page or [] if isinstance(item, dict) and item.get("label") in labels]
            for page in images_mfd_res
        ]


def apply_formula_recognition() -> bool:
    """Pasang pilihan ``FORMULA_RECOGNITION`` (``on`` | ``off``). Mengembalikan apakah rumus dikenali.

    MinerU mengambil model rumus lewat satu pintu, ``HybridLocalModelContext.get_mfr_model``; ``off``
    menggantinya dengan ``NoFormulaRecognizer``. Pintu itu method internal MinerU, bukan setting resmi:
    bila hilang setelah MinerU di-upgrade, ini gagal dengan jelas alih-alih diam-diam memuat model rumus.
    """
    choice = (os.getenv("FORMULA_RECOGNITION") or "on").strip().lower()
    if choice not in CHOICES:
        raise ValueError(f"FORMULA_RECOGNITION='{choice}' tidak valid. Gunakan on atau off.")
    if choice == "on":
        return True

    from mineru.model.runtime.hybrid import HybridLocalModelContext

    if not hasattr(HybridLocalModelContext, "get_mfr_model"):
        raise RuntimeError("HybridLocalModelContext.get_mfr_model tidak ada di MinerU ini: pengenal rumus tidak bisa dimatikan.")
    HybridLocalModelContext.get_mfr_model = lambda self: NoFormulaRecognizer()
    return False


if __name__ == "__main__":
    # Pengganti harus memilih dan menyusun area rumus persis seperti model asli MinerU.
    import numpy as np
    from mineru.model.mfr.pp_formulanet_plus_m_onnx import PPFormulaNetPlusMONNX

    page = [
        {"label": "inline_formula", "bbox": [1, 1, 9, 9], "score": 0.9, "latex": ""},
        {"label": "display_formula", "bbox": [2, 2, 8, 8], "score": 0.8, "latex": ""},
        {"label": "text", "bbox": [0, 0, 5, 5]},
        "bukan dict",
    ]
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    real = PPFormulaNetPlusMONNX.__new__(PPFormulaNetPlusMONNX)  # tanpa __init__: bobot tidak dimuat
    for interline_enable in (True, False):
        expected = [real._build_formula_items(page, image, interline_enable=interline_enable)[0], []]
        actual = NoFormulaRecognizer().batch_predict([page, None], [image, image], interline_enable=interline_enable)
        assert actual == expected, (interline_enable, actual, expected)

    os.environ["FORMULA_RECOGNITION"] = "off"
    from mineru.model.runtime.hybrid import HybridLocalModelContext

    assert apply_formula_recognition() is False
    assert isinstance(HybridLocalModelContext.get_mfr_model(None), NoFormulaRecognizer)
    print("OK: pengganti model rumus sesuai dengan MinerU yang terpasang")

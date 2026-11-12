# Server parser dokumen (CPU). Build: `docker compose build`; jalankan bersama unoserver lewat docker-compose.yml.
#
# Urutan layer mengikuti seberapa sering isinya berubah: dependensi, lalu model, lalu kode. Mengubah
# kode saja tidak mengunduh ulang dependensi (±1,3 GB) maupun model (±0,9 GB).
FROM python:3.13-slim-bookworm

# libmagic1: deteksi tipe file (python-magic, dipakai unstructured). libgomp1: OpenMP untuk inferensi.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /bin/uv

# Proses berjalan sebagai pengguna biasa, bukan root.
RUN useradd --create-home --uid 1000 app && mkdir /app && chown app:app /app
USER app
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # .venv/bin di PATH: konversi office memanggil `unoconvert` dari sana.
    PATH="/app/.venv/bin:$PATH" \
    # Model MinerU disimpan di dalam image (lihat langkah unduh di bawah).
    HF_HOME=/app/.cache/huggingface \
    # unstructured: tanpa telemetri dan tanpa banner.
    DO_NOT_TRACK=true \
    SCARF_NO_ANALYTICS=true \
    UNSTRUCTURED_DISABLE_NOTICE=1

# 1. Dependensi, persis seperti uv.lock. Tanpa extra torch: tier basic berjalan di ONNX Runtime.
COPY --chown=app:app pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-dev --no-install-project

# 2. Model MinerU (layout, OCR, tabel, rumus) diunduh saat build, bukan saat container menyala.
RUN mineru-models-download MinerU-4_models_onnx --source huggingface

# 3. Kode.
COPY --chown=app:app src ./src

# Sejak sini Hugging Face tidak dihubungi lagi. Memuat semua model sekali di sini membuktikan
# unduhan di atas lengkap: kalau ada yang kurang, build yang gagal, bukan container di produksi.
ENV HF_HUB_OFFLINE=1
RUN python -c "from src.modules.mineru_parser.runtime import warm_up; warm_up()"

EXPOSE 8000
# Satu proses: antrean job ada di memori proses ini, dan tiap proses memuat salinan modelnya sendiri.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# mineru-serve

Layanan parser dokumen lokal. File masuk lewat HTTP, dan output formatnya berupa json **content list**: item
`text` / `table` / `image` / `equation` dalam urutan baca. PDF dan gambar dibaca
[MinerU](https://github.com/opendatalab/MinerU) (model parser: layout, OCR, tabel, rumus) di server local, tanpa layanan cloud.

## Tech stack

[![Python](https://img.shields.io/badge/Python-%2314354C.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-%23009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Celery](https://img.shields.io/badge/Celery-%2337814A.svg?style=flat&logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![Redis](https://img.shields.io/badge/Redis-%23DC382D.svg?style=flat&logo=redis&logoColor=white)](https://redis.io/)
[![PyTorch](https://img.shields.io/badge/PyTorch-%23EE4C2C.svg?style=flat&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![ONNX](https://img.shields.io/badge/ONNX-%23F7931E.svg?style=flat&logo=onnx&logoColor=white)](https://onnx.ai/)
[![Hugging Face](https://img.shields.io/badge/Hugging%20Face-%23FFD21E.svg?style=flat&logo=huggingface&logoColor=black)](https://huggingface.co/)
[![Amazon S3](https://img.shields.io/badge/Amazon%20S3-%23569A31.svg?style=flat&logo=amazons3&logoColor=white)](https://aws.amazon.com/s3/)
[![LibreOffice](https://img.shields.io/badge/LibreOffice-%2318A303.svg?style=flat&logo=libreoffice&logoColor=white)](https://www.libreoffice.org/)
[![Docker](https://img.shields.io/badge/Docker-%232496ED.svg?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![MinerU](https://img.shields.io/badge/MinerU-%23000000.svg?style=flat)](https://github.com/opendatalab/MinerU)

## File input yang didukung

| Ekstensi | Cara dibaca | `layout` |
|---|---|---|
| `pdf` | MinerU. PDF slide (halaman 16:9 / 16:10) ditranskripsi VLM per slide | `document` / `slides` |
| `docx`, `doc`, `odt`, `rtf` | LibreOffice (unoserver) → PDF → MinerU | `document` |
| `pptx` | LibreOffice → PDF → VLM per slide | `slides` |
| `xlsx` | per sheet (unstructured + openpyxl) | `sheet` |
| `jpg`, `jpeg`, `png` | MinerU (OCR); foto/chart juga dikirim utuh sebagai item `image` | `document` |
| `md`, `markdown`, `txt` | satu item `text`, dijawab langsung tanpa antrean | `document` |
| `json` | content list jadi, divalidasi, dijawab langsung tanpa antrean | `document` |

PDF dan gambar menerima `tier`: `basic` (bawaan; OCR untuk scan, struktur tabel, rumus) atau `flash`
(hanya text layer, lebih cepat). PDF juga menerima `pages`, misalnya `1-3,8`.

## Kontrak output

`POST /parse` dan `GET /parse/{job_id}` menjawab bentuk yang sama:

```json
{
  "job_id": "…",
  "status": "succeeded",
  "error": null,
  "result": {
    "file_type": "pdf",
    "layout": "document",
    "elapsed_seconds": 54.1,
    "content_list": [
      {"type": "text", "text": "Attention Is All You Need", "text_level": 1, "page_idx": 0, "bbox": [0.342, 0.185, 0.655, 0.21], "layout": "document"},
      {"type": "table", "table_body": "| Layer Type | Complexity |\n| --- | --- |\n| …", "table_caption": ["Table 1: …"], "table_footnote": null, "page_idx": 5, "bbox": [0.171, 0.088, 0.826, 0.236]},
      {"type": "image", "img_path": "https://<bucket>.s3…/figure_p2.jpg", "image_caption": ["Figure 1: …"], "image_footnote": null, "page_idx": 2, "bbox": [0.321, 0.09, 0.677, 0.498]},
      {"type": "equation", "text": "$$…$$", "text_format": "latex", "page_idx": 3, "bbox": [0.356, 0.585, 0.825, 0.62]}
    ]
  }
}
```

`status`: `queued` → `running` → `succeeded` atau `failed` (sebabnya di `error`). Job hilang setelah
`JOB_TTL_SECONDS`.

| Item | Field | Keterangan |
|---|---|---|
| `text` | `text`, `page_idx`, `layout` | Satu blok (paragraf, butir, heading). Heading punya `text_level` (1 = judul dokumen). |
| `table` | `table_body`, `table_caption`, `table_footnote`, `page_idx` | `table_body` berupa Markdown. |
| `image` | `img_path`, `image_caption`, `image_footnote`, `page_idx` | `img_path` adalah URL S3. |
| `equation` | `text`, `page_idx`, `bbox` | `$$…$$`. `text_format: latex` bila dikenali model rumus. |

Perbedaan per tipe file:

| File | `page_idx` | `bbox` | Item yang mungkin muncul |
|---|---|---|---|
| PDF, office (dokumen), gambar | halaman, mulai 0 | `[x0, y0, x1, y1]` ternormalisasi 0–1 | `text`, `table`, `image`, `equation` |
| PDF slide, `pptx` | nomor slide, mulai 0 | — | satu `text` per slide (dengan `img_path` gambar slide), lalu `table` per grid |
| `xlsx` | nama sheet | — | `text`, `table`, `image` |
| `md`, `txt` | — | — | satu `text` berisi seluruh file |
| `json` | seperti isinya | seperti isinya | seperti isinya |

Definisi lengkap: [src/modules/contract.py](src/modules/contract.py).

## Menjalankan di laptop (tanpa Docker, CPU)

Butuh [uv](https://docs.astral.sh/uv/), Redis, dan bucket S3. Salin `.env.example` ke `.env`, lalu isi
`REDIS_URL` dan `S3_*`. `VLM_*` hanya perlu untuk slide dan gambar visual.

```bash
uv sync
python -m src.models --port 8002 --tier basic --preload-models   # server MinerU (pertama kali mengunduh model)
celery -A src.jobs.celery_app worker --loglevel=info              # worker
python run.py                                                    # API (port 8000)
```

File office butuh unoserver:
`docker run -d --rm -p 127.0.0.1:2003:2003 ghcr.io/unoconv/unoserver-docker:0.4.4` dengan
`UNOSERVER_HOST=127.0.0.1`.

Coba:

```bash
curl -F file=@dokumen.pdf http://localhost:8000/parse            # → {"job_id": "…", "status": "queued"}
curl http://localhost:8000/parse/<job_id>
```

Bila `PARSER_API_KEY` diisi, sertakan header `X-API-Key`. Dokumentasi API: `http://localhost:8000/docs`.

## Deployment (Docker)

```bash
# GPU (Torch + CUDA 12.6)
docker compose up -d --build

# CPU (ONNX)
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

`--build` hanya perlu saat pertama kali atau setelah kode berubah. API terbuka di `HOST_PORT` (bawaan `8001`);
bila port itu sudah dipakai di server, ganti nilainya di `.env`.

### Checklist GPU

- [ ] Host punya driver NVIDIA ≥ 525 dan [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/).
- [ ] GPU punya VRAM kosong untuk model MinerU (cek `nvidia-smi` sebelum menyalakan).
- [ ] `docker compose ps`: semua service `healthy`.
- [ ] `docker compose logs mineru` memuat `backend=torch, mode=gpu` dan `presisi Torch=…`.
- [ ] `curl http://localhost:8001/health` menjawab `"status": "ok"` dan `"mineru": {"reachable": true, "device": "gpu"}`.
- [ ] `nvidia-smi` menampilkan proses server MinerU.
- [ ] Satu PDF uji sampai `succeeded`.

Bila container tidak mendapat GPU, `mineru` menolak menyala dengan pesan
`MINERU_DEVICE_MODE=cuda tetapi MinerU hanya menemukan CPU`, alih-alih diam-diam berjalan di CPU.

### Checklist CPU

- [ ] `docker compose ps`: semua service `healthy`.
- [ ] `docker compose logs mineru` memuat `backend=onnx, mode=cpu`.
- [ ] `curl http://localhost:8001/health` menjawab `"status": "ok"` dan `"device": "cpu"`.
- [ ] Satu PDF uji sampai `succeeded`.

### Arti `status` di `/health`

| Nilai | Arti |
|---|---|
| `ok` | Worker menjawab dan server MinerU terjangkau. |
| `no_worker` | Tidak ada worker: job menunggu di antrean. |
| `mineru_unreachable` | Server MinerU mati: job PDF dan gambar gagal. |
| `redis_unreachable: …` | Redis tidak terjangkau. |

## Setting utama

Lengkapnya ada di [.env.example](.env.example).

| Env | Bawaan | Arti |
|---|---|---|
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Antrean dan hasil job. Dari container, Redis di host = `host.docker.internal`. |
| `S3_*` | — | Serah-terima file api → worker dan hosting figure. |
| `VLM_*` | — | VLM untuk slide dan gambar visual. |
| `TORCH_INFERENCE_PRECISION` | `fp32` | Presisi di GPU: `fp32` atau `fp16`. Tidak berlaku di CPU. |
| `FORMULA_RECOGNITION` | `on` | `off`: model rumus tidak dimuat (hemat memori). Rumus inline hilang dari kalimat, rumus blok diambil dari text layer PDF; bagian lain tidak berubah. |
| `WORKER_CONCURRENCY`, `MINERU_CONCURRENCY` | `1` | Job dan dokumen yang dikerjakan sekaligus. |
| `PARSER_API_KEY` | — | Kunci API; kosong = tanpa autentikasi. |

Mengubah presisi atau enable model formula/rumus cukup dengan `docker compose up -d`, tanpa build ulang.
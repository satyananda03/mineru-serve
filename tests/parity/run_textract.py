"""Buat ulang baseline Textract (``baseline_textract/``) lewat jalur parser hybrid_rag yang asli.

Hanya perlu saat kasus uji berubah: memanggil AWS Textract (berbayar per halaman) dan butuh paket
``hybrid_rag`` di root repo beserta kredensialnya di ``.env``. Mode async mengunggah PDF sementara
ke S3 lalu menghapusnya.

Dari root repo: ``python tests/parity/run_textract.py``
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tests.parity.cases import BASELINE, prepare


async def one(case: dict, slots: asyncio.Semaphore, parse_pdf) -> None:
    async with slots:
        started = time.time()
        with tempfile.TemporaryDirectory() as tmp_dir:
            items = await parse_pdf(Path(case["pdf"]), Path(tmp_dir))
            for item in items:  # crop figure hilang bersama tmp_dir: yang disimpan nama dan ukurannya saja
                if item.get("type") == "image":
                    with Image.open(item["img_path"]) as image:
                        item["img_size"] = list(image.size)
                    item["img_path"] = Path(item["img_path"]).name
        result = {"ok": True, "items": items, "elapsed_s": round(time.time() - started, 1)}
    (BASELINE / f"{case['name']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(case["name"], f"{result['elapsed_s']}s", flush=True)


async def main() -> None:
    from hybrid_rag.ingestion.parser.pdf.amazon_textract import parse_pdf

    BASELINE.mkdir(exist_ok=True)
    slots = asyncio.Semaphore(8)
    await asyncio.gather(*(one(case, slots, parse_pdf) for case in prepare(sys.argv[1:])))


if __name__ == "__main__":
    asyncio.run(main())

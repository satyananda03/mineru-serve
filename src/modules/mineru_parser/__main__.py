"""CLI: ``python -m src.modules.mineru_parser file.pdf --output hasil.json``.

Butuh server MinerU yang menyala di ``MINERU_API_URL`` (``python -m src.models --port 8002 --tier basic``).
"""
import argparse
import asyncio
import json
from pathlib import Path
from typing import get_args

from src.core.logging import configure_logging
from src.modules.contract import Tier

from . import parse_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse PDF menjadi content list lewat server MinerU")
    parser.add_argument("input", type=Path, help="File PDF")
    parser.add_argument("--output", type=Path, default=Path("content_list.json"), help="File JSON hasil")
    parser.add_argument("--pages", default=None, help="Halaman 1-based, mis. '1-5,8'. Default: semua")
    parser.add_argument("--tier", default="basic", choices=get_args(Tier))
    parser.add_argument("--ocr-mode", default=None, choices=["auto", "txt", "ocr"], help="Default: mengikuti --tier")
    parser.add_argument("--image-dir", default="images", help="Folder crop figure (lokal; hanya API yang mengunggah ke S3)")
    args = parser.parse_args()

    configure_logging()
    items = asyncio.run(parse_pdf(args.input, args.image_dir, tier=args.tier, ocr_mode=args.ocr_mode, pages=args.pages))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(items)} item → {args.output}")


if __name__ == "__main__":
    main()

"""File .md / .markdown / .txt → content list satu item.

Dipindah apa adanya dari ``hybrid_rag/ingestion/parser/router.py`` (``_read_text_document``).
"""
import asyncio
from pathlib import Path

from src.modules.contract import Layout, ParseOptions


def _read_text_document(path: Path) -> list[dict]:
    """Turn a .md / .txt file into a one-item content list."""
    return [
        {
            "type": "text",
            "text": path.read_text(encoding="utf-8", errors="replace"),
        }
    ]


async def parse(path: Path, tmp_dir: Path, options: ParseOptions) -> tuple[Layout, list[dict]]:
    return "document", await asyncio.to_thread(_read_text_document, path)

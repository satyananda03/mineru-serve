"""File .json berisi content list siap pakai (mis. hasil ``notion_sync``) → content list.

Tidak ada yang diparse: isinya divalidasi, lalu gambarnya dibawa ke batas VLM seperti figure parser
lain. Dipindah apa adanya dari ``hybrid_rag/ingestion/parser/router.py`` (``_read_content_list``,
``_read_prebuilt``).
"""
import asyncio
import json
from pathlib import Path

from src.modules.contract import Layout, ParseOptions
from src.modules.figures import fit_figures


def _read_content_list(path: Path) -> list[dict]:
    """Read a pre-built content list, validated rather than trusted."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError(
            f"{path.name}: content list harus berupa array of object, "
            f"isinya hanya ini : {type(data).__name__}"
        )
    return data


async def parse(path: Path, tmp_dir: Path, options: ParseOptions) -> tuple[Layout, list[dict]]:
    """A content list that is already the parser's output: nothing to parse,
    only its images brought under the VLM limits like every parser's figures."""
    content_list = await asyncio.to_thread(_read_content_list, path)
    await asyncio.to_thread(fit_figures, content_list, tmp_dir)
    return "document", content_list

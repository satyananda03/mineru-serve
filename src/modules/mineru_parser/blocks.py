"""Blok MinerU → item content list. Satu fungsi per tipe blok, dipilih lewat ``CONVERTERS``.

Tipe blok adalah nilai ``docvortex.schema.BlockType``. Tipe yang tidak punya konverter dicatat di
log, bukan dibuang diam-diam: isi yang hilang tanpa jejak baru ketahuan saat dicari dan tidak ada.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import pymupdf

from src.modules.contract import ContentItem

from .figures import crop_figure
from .geometry import has_raster_image, page_rect, text_in_bbox, union_bbox
from .tables import table_markdown

logger = logging.getLogger(__name__)

# Blok "image" tanpa raster dan tanpa caption yang memuat teks sebanyak ini adalah kotak teks
# berbingkai, bukan gambar.
FRAMED_TEXT_MIN_CHARS = 80
# Sambungan heading yang terpotong tanda hubung: satu kata pendek.
HEADING_TAIL_MAX_CHARS = 25


@dataclass(frozen=True)
class PageContext:
    """Yang dibutuhkan konverter tentang halaman tempat blok berada."""

    page_idx: int
    pdf_page: pymupdf.Page
    image_dir: str


def block_to_items(block: Any, ctx: PageContext) -> list[ContentItem]:
    """Item content list untuk satu blok tingkat atas; [] bila blok kosong atau tak dikenal."""
    kind = str(block.type)
    converter = CONVERTERS.get(kind)
    if converter is None:
        if kind not in _unknown_types:
            _unknown_types.add(kind)
            logger.warning("Tipe blok MinerU '%s' belum punya konverter: isinya tidak ikut output", kind)
        return []
    return converter(block, ctx)


def inline_text(spans: list) -> str:
    """Teks sebuah blok dari span inline-nya. Span membawa spasinya sendiri, jadi digabung tanpa pemisah."""
    parts = []
    for span in spans:
        kind = str(span.type)
        if kind == "hyperlink":
            parts.append(inline_text(span.content))
        elif kind == "equation_inline":
            parts.append(f"${span.content.strip()}$")
        elif kind == "code_inline":
            parts.append(f"`{span.content}`")
        else:
            parts.append(span.content)
    return "".join(parts).strip()


def join_hyphenated_headings(items: list[ContentItem]) -> list[ContentItem]:
    """Gabungkan heading yang terpotong tanda hubung dengan sambungannya di blok berikutnya.

    ``Reasoning-`` lalu ``Enhanced`` (satu kata pendek, halaman yang sama) menjadi satu heading.
    """
    joined: list[ContentItem] = []
    for item in items:
        previous = joined[-1] if joined else None
        if (
            previous is not None
            and previous.get("text_level")
            and previous["text"].endswith("-")
            and item["type"] == "text"
            and not item.get("text_level")
            and item["page_idx"] == previous["page_idx"]
            and len(item["text"]) <= HEADING_TAIL_MAX_CHARS
            and " " not in item["text"]
        ):
            previous["text"] = previous["text"][:-1] + item["text"]
            previous["bbox"] = union_bbox([previous["bbox"], item["bbox"]])
        else:
            joined.append(item)
    return joined


def _text_item(text: str, bbox, ctx: PageContext, level: int | None = None) -> ContentItem:
    item = {"type": "text", "text": text, "page_idx": ctx.page_idx, "bbox": _bbox(bbox)}
    if level:
        item["text_level"] = level
    return item


def _bbox(bbox) -> list[float] | None:
    return [round(value, 4) for value in bbox] if bbox else None


def _leaves(block: Any) -> Iterator[Any]:
    """Butir daun sebuah ``list`` atau ``index``, yang bisa bersarang."""
    for child in block.content:
        if str(child.type) in ("list", "index"):
            yield from _leaves(child)
        else:
            yield child


def _annotations(block: Any, kind: str) -> list[str]:
    """Teks semua anak bertipe ``kind`` (mis. ``table_caption``): caption bisa lebih dari satu blok."""
    texts = [inline_text(child.content) for child in block.content if str(child.type) == kind]
    return [text for text in texts if text]


def _text(block: Any, ctx: PageContext) -> list[ContentItem]:
    text = inline_text(block.content)
    return [_text_item(text, block.bbox, ctx)] if text else []


def _heading(block: Any, ctx: PageContext) -> list[ContentItem]:
    text = inline_text(block.content)
    return [_text_item(text, block.bbox, ctx, level=block.level)] if text else []


def _list(block: Any, ctx: PageContext) -> list[ContentItem]:
    """Satu item per butir: batas antar butir adalah yang dibaca chunker."""
    items = []
    for leaf in _leaves(block):
        if text := inline_text(leaf.content):
            items.append(_text_item(text, leaf.bbox or block.bbox, ctx))
    return items


def _index(block: Any, ctx: PageContext) -> list[ContentItem]:
    """Daftar isi / daftar tabel: satu item, satu baris per entri, supaya tidak tercerai antar chunk."""
    lines = [text for leaf in _leaves(block) if (text := inline_text(leaf.content))]
    return [_text_item("\n".join(lines), block.bbox, ctx)] if lines else []


def _equation(block: Any, ctx: PageContext) -> list[ContentItem]:
    """Rumus blok. Tier flash tidak mengenali rumus, jadi isinya diambil dari text layer PDF."""
    latex = (block.content or "").strip()
    text = latex or " ".join(text_in_bbox(ctx.pdf_page, block.bbox).split())
    if not text:
        return []
    item = {"type": "equation", "text": f"$${text}$$", "page_idx": ctx.page_idx, "bbox": _bbox(block.bbox)}
    if latex:
        item["text_format"] = "latex"
    return [item]


def _code(block: Any, ctx: PageContext) -> list[ContentItem]:
    """Kode atau algoritma sebagai item text ber-fence, didahului caption-nya."""
    bodies = []
    for child in block.content:
        if str(child.type) in ("code_body", "algorithm_body"):
            body = child.content if isinstance(child.content, str) else inline_text(child.content)
            if body.strip():
                bodies.append(f"```text\n{body.strip()}\n```")
    parts = [*_annotations(block, "code_caption"), *bodies, *_annotations(block, "code_footnote")]
    if not parts:
        return []
    bbox = union_bbox([block.bbox, *(child.bbox for child in block.content)])
    return [_text_item("\n".join(parts), bbox, ctx)]


def _table(block: Any, ctx: PageContext) -> list[ContentItem]:
    captions = _annotations(block, "table_caption")
    footnotes = _annotations(block, "table_footnote")
    bbox = union_bbox([block.bbox, *(child.bbox for child in block.content)])
    body = next((child.content for child in block.content if str(child.type) == "table_body"), "")
    markdown = table_markdown(body, ctx.pdf_page, page_rect(ctx.pdf_page, bbox), " ".join(captions))
    if not markdown:
        # Struktur tabel tidak terbaca: gambarnya tetap dibawa supaya VLM yang membacanya.
        return _image_items(bbox, captions, footnotes, ctx)
    return [{
        "type": "table",
        "table_body": markdown,
        "table_caption": captions or None,
        "table_footnote": footnotes or None,
        "page_idx": ctx.page_idx,
        "bbox": _bbox(bbox),
    }]


def _figure(block: Any, ctx: PageContext) -> list[ContentItem]:
    """Blok ``image`` atau ``chart``."""
    kind = str(block.type)
    captions = _annotations(block, f"{kind}_caption")
    footnotes = _annotations(block, f"{kind}_footnote")
    bbox = block.bbox or union_bbox(child.bbox for child in block.content)
    if not bbox:
        return []
    if kind == "image" and not captions and not has_raster_image(ctx.pdf_page, bbox):
        framed_text = text_in_bbox(ctx.pdf_page, bbox)
        if len(framed_text) >= FRAMED_TEXT_MIN_CHARS:
            return [_text_item(framed_text, bbox, ctx)]
    return _image_items(bbox, captions, footnotes, ctx)


def _image_items(bbox, captions: list[str], footnotes: list[str], ctx: PageContext) -> list[ContentItem]:
    """Item ``image`` untuk area ``bbox``. Figure yang terlalu kecil dibuang, tetapi caption-nya tetap jadi teks."""
    path = crop_figure(ctx.pdf_page, bbox, ctx.image_dir, ctx.page_idx)
    if path is None:
        return [_text_item(text, bbox, ctx) for text in (*captions, *footnotes)]
    return [{
        "type": "image",
        "img_path": path,
        "image_caption": captions or None,
        "image_footnote": footnotes or None,
        "page_idx": ctx.page_idx,
        "bbox": _bbox(bbox),
    }]


CONVERTERS: dict[str, Callable[[Any, PageContext], list[ContentItem]]] = {
    "doc_title": _heading,
    "paragraph_title": _heading,
    "text": _text,
    "ref_text": _text,
    "page_footnote": _text,
    "header": _text,  # hanya header yang lolos page_furniture: muncul di satu halaman saja
    "list": _list,
    "index": _index,
    "equation": _equation,
    "code": _code,
    "table": _table,
    "image": _figure,
    "chart": _figure,
}
_unknown_types: set[str] = set()

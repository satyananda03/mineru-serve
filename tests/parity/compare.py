"""Bandingkan output MinerU (``.work/mineru``) dengan baseline Textract (``baseline_textract``).

Dari root repo, setelah ``run_mineru.py``: ``python tests/parity/compare.py``

Acuan teks adalah text layer PDF: kebenaran untuk dokumen born-digital, acuan lunak untuk scan yang
punya text layer (OCR pemindai). Scan tanpa text layer hanya diukur kesepakatannya dengan Textract.
Rumus LaTeX menambah jumlah kata MinerU, jadi presisinya di paper terlihat lebih rendah dari sebenarnya.
"""
import collections
import difflib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pymupdf
from PIL import Image

from src.modules.mineru_parser import figures
from tests.parity.cases import BASELINE, ROOT, WORK, prepare

KNOWN_TYPES = {"text", "image", "table", "equation"}
PAGE_NOISE = {
    "header berulang": re.compile(r"^(PRESIDEN\s+REPUBLIK\s+INDONESIA|MENTERI\s+PENDAYAGUNAAN[A-Z\s]+)(\s*-\s*\w+\s*-)?$"),
    "nomor halaman": re.compile(r"^-\s*\w{1,4}\s*-$"),
    "kata sambung": re.compile(r"(\.\s*){2,}\.?$"),
}
ARTICLES_FILE = ROOT / "hybrid_rag/ingestion/chunking/legal_chunker/articles.py"


def load_articles_module():
    """Pencari Pasal milik legal chunker hybrid_rag; None bila hybrid_rag tidak ada di repo ini."""
    if not ARTICLES_FILE.exists():
        return None
    spec = importlib.util.spec_from_file_location("legal_articles", ARTICLES_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["legal_articles"] = module
    spec.loader.exec_module(module)
    return module


ARTICLES = load_articles_module()


def tokens(text) -> list[str]:
    return re.findall(r"\w+", str(text).casefold())


def as_list(value) -> list[str]:
    if value is None:
        return []
    return [str(entry) for entry in value] if isinstance(value, list) else [str(value)]


def item_text(item: dict) -> str:
    kind = item.get("type", "text")
    if kind == "table":
        body = re.sub(r"<[^>]+>", " ", str(item.get("table_body") or "")).replace("|", " ").replace("**", " ")
        return " ".join([*as_list(item.get("table_caption")), re.sub(r"-{3,}", " ", body), *as_list(item.get("table_footnote"))])
    if kind == "image":
        return " ".join([*as_list(item.get("image_caption")), *as_list(item.get("image_footnote"))])
    return str(item.get("text") or "").replace("$$", " ")


def output_tokens(items: list[dict]) -> list[str]:
    return [token for item in items for token in tokens(item_text(item))]


def score(reference: list[str], candidate: list[str]) -> dict | None:
    """Recall dan presisi kantong-kata (tak peduli urutan) dan rasio urutan (peduli urutan)."""
    if not reference or not candidate:
        return None
    common = sum((collections.Counter(reference) & collections.Counter(candidate)).values())
    return {
        "recall": common / len(reference),
        "precision": common / len(candidate),
        "order": difflib.SequenceMatcher(None, reference, candidate, autojunk=False).ratio(),
    }


def contract_problems(items: list[dict], images_on_disk: bool) -> collections.Counter:
    problems = collections.Counter()
    for item in items:
        kind = item.get("type")
        if kind not in KNOWN_TYPES:
            problems[f"tipe '{kind}' tidak punya processor di hybrid_rag"] += 1
            continue
        if not isinstance(item.get("page_idx"), int):
            problems["page_idx bukan int"] += 1
        if kind in ("image", "table"):
            for key in (f"{kind}_caption", f"{kind}_footnote"):
                if key not in item:
                    problems[f"{key} tidak ada"] += 1
                elif item[key] is not None and not isinstance(item[key], list):
                    problems[f"{key} bertipe {type(item[key]).__name__} (kontrak: list[str] | None)"] += 1
        if kind == "table" and not str(item.get("table_body") or "").lstrip().startswith("|"):
            problems["table_body bukan markdown"] += 1
        if kind == "image" and images_on_disk:
            path = str(item.get("img_path") or "")
            if not (os.path.isabs(path) and os.path.isfile(path)):
                problems["img_path bukan file absolut yang ada"] += 1
                continue
            width, height = image_size(item)
            if not path.lower().endswith(".jpg"):
                problems["gambar bukan JPEG"] += 1
            if max(width, height) > figures.MAX_PIXELS or os.path.getsize(path) > figures.MAX_BYTES:
                problems["gambar melebihi batas VLM"] += 1
    return problems


def image_size(item: dict) -> tuple[int, int]:
    if "img_size" in item:  # baseline Textract: file crop-nya tidak disimpan
        return tuple(item["img_size"])
    with Image.open(item["img_path"]) as image:
        return image.size


def structure(items: list[dict]) -> str:
    kinds = dict(collections.Counter(item.get("type") for item in items))
    levels = dict(sorted(collections.Counter(item["text_level"] for item in items if item.get("text_level")).items()))
    images = ["p%d:%dx%d" % (item["page_idx"], *image_size(item)) for item in items if item.get("type") == "image"]
    return f"n={len(items):3} {kinds} level={levels} kata={len(output_tokens(items))} gambar={images}"


def articles_of(items: list[dict]) -> list[tuple[str, str]]:
    """(judul Pasal, awal isinya) dari pencari Pasal legal chunker, pada teks yang disusun seperti hybrid_rag."""
    content = "\n\n".join(str(item.get("text") or "") for item in items if item.get("type", "text") == "text")
    found = ARTICLES.select_articles(ARTICLES.find_article_candidates(content))
    return [(article.title, " ".join(tokens(content[article.end:article.end + 90]))[:60]) for article in found]


def page_noise(items: list[dict]) -> collections.Counter:
    found = collections.Counter()
    for item in items:
        text = " ".join(str(item.get("text") or "").split())
        if item.get("type", "text") == "text" and len(text) < 60:
            found.update(label for label, pattern in PAGE_NOISE.items() if pattern.search(text))
    return found


def percent(value: float) -> str:
    return f"{value * 100:3.0f}"


def triple(result: dict | None) -> str:
    return f"{percent(result['recall'])}/{percent(result['precision'])}/{percent(result['order'])}" if result else "-"


def main() -> None:
    rows = []
    for case in prepare(sys.argv[1:]):
        mineru_file = WORK / "mineru" / f"{case['name']}.json"
        if not mineru_file.exists():
            print(f"{case['name']}: belum ada hasil MinerU, jalankan run_mineru.py")
            continue
        mineru = json.loads(mineru_file.read_text(encoding="utf-8"))
        textract = json.loads((BASELINE / f"{case['name']}.json").read_text(encoding="utf-8"))
        if not mineru["ok"]:
            print(f"{case['name']}: MinerU gagal: {mineru['error']}")
            continue
        with pymupdf.open(case["pdf"]) as pdf:
            layer = [token for page in pdf for token in tokens(page.get_text())]
        rows.append({**case, "layer": layer, "textract": textract, "mineru": mineru})

    print("== A. KETEPATAN TEKS: recall / presisi / urutan, dalam % (acuan: text layer PDF)")
    print(f"{'kasus':19} {'grup':6} hal | {'textract':^11} | {'mineru':^11} | mineru vs textract")
    for row in rows:
        tx, mn = output_tokens(row["textract"]["items"]), output_tokens(row["mineru"]["items"])
        print(f"{row['name']:19} {row['group']:6} {len(row['pages']):3} | {triple(score(row['layer'], tx)):^11} | "
              f"{triple(score(row['layer'], mn)):^11} | {triple(score(tx, mn)):^11}")

    print("\n== B. STRUKTUR DAN WAKTU")
    for row in rows:
        print(f"{row['name']} ({len(row['pages'])} hal): textract {row['textract']['elapsed_s']}s, mineru {row['mineru']['elapsed_s']}s")
        print(f"   textract {structure(row['textract']['items'])}")
        print(f"   mineru   {structure(row['mineru']['items'])}")

    print("\n== C. PELANGGARAN KONTRAK (semua kasus)")
    for label, on_disk in (("textract", False), ("mineru", True)):
        total = collections.Counter()
        for row in rows:
            total.update(contract_problems(row[label]["items"], on_disk))
        print(f"   {label}: {dict(total) or 'tidak ada'}")

    print("\n== D. PERABOT HALAMAN YANG LOLOS SEBAGAI TEKS (regulasi)")
    for label in ("textract", "mineru"):
        total = collections.Counter()
        for row in rows:
            if row["group"] == "policy":
                total.update(page_noise(row[label]["items"]))
        print(f"   {label}: {dict(total) or 'tidak ada'}")

    if ARTICLES is None:
        print("\n== E. PASAL: dilewati (hybrid_rag tidak ada di repo ini)")
        return
    print("\n== E. PASAL yang ditemukan legal chunker, dan apakah awal isinya sama dengan Textract")
    same_total = reference_total = 0
    for row in rows:
        if row["group"] != "policy":
            continue
        reference = dict(articles_of(row["textract"]["items"]))
        found = articles_of(row["mineru"]["items"])
        different = [(title, head) for title, head in found
                     if title in reference and difflib.SequenceMatcher(None, reference[title], head).ratio() < 0.7]
        same = sum(1 for title, _ in found if title in reference) - len(different)
        same_total, reference_total = same_total + same, reference_total + len(reference)
        print(f"   {row['name']:18} textract {len(reference)} pasal, mineru {len(found)} pasal, isi sama {same}")
        for title, head in different:
            print(f"      BEDA {title}: textract={reference[title][:45]!r} | mineru={head[:45]!r}")
    print(f"   TOTAL isi sama: {same_total}/{reference_total}")


if __name__ == "__main__":
    main()

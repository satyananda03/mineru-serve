"""Badan tabel MinerU → markdown.

MinerU memberi badan tabel sebagai HTML saat struktur tabelnya dikenali (tier basic), atau sebagai
teks polos saat tidak (tier flash). Keduanya berakhir sebagai tabel markdown, yang diminta kontrak.
"""
import re
from html.parser import HTMLParser

import pymupdf

Grid = list[list[str]]

# Baris teks yang berjarak vertikal lebih dari ini (point) dianggap baris tabel yang berbeda.
ROW_GAP_PT = 4.5
# Toleransi (point) saat mencocokkan sebuah sel ke rentang kolom.
COLUMN_SLACK_PT = 4.0
TABLE_LABEL = re.compile(r"^TABLE\s+[IVX\d]+\b", re.IGNORECASE)


def table_markdown(body: str, page: pymupdf.Page, rect: pymupdf.Rect, caption: str = "") -> str:
    """Badan tabel (HTML, markdown, atau teks polos) → tabel markdown.

    ``rect`` adalah area tabel pada ``page``; dipakai hanya untuk badan berupa teks polos.
    Badan yang tidak bisa dijadikan tabel dikembalikan apa adanya, supaya isinya tidak hilang.
    """
    body = (body or "").strip()
    if "<table" in body.lower():
        return _markdown(_grid_from_html(body)) or body
    if not body or body.startswith("|"):
        return body
    grid = _grid_from_pdf_text(page, rect, caption) or _grid_from_spaced_text(body)
    return _markdown(grid) or body


def _markdown(grid: Grid) -> str:
    if not grid:
        return ""
    width = max(len(row) for row in grid)
    rows = [row + [""] * (width - len(row)) for row in grid]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


class _HtmlTable(HTMLParser):
    """Kumpulkan sel ``<td>``/``<th>`` per ``<tr>``; sel ``colspan`` diulang di tiap kolomnya.

    ponytail: ``rowspan`` diabaikan, jadi sel di bawah sel gabungan vertikal bergeser ke kiri.
    Lacak sel yang masih "terbuka" per kolom bila tabel seperti itu sering muncul.
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: Grid = []
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False
        self._colspan = 1

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self._in_cell = True
            self._cell = []
            try:
                self._colspan = max(1, int(dict(attrs).get("colspan") or 1))
            except ValueError:
                self._colspan = 1

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._in_cell = False
            # "|" di dalam sel akan memecah kolom markdown.
            text = " ".join("".join(self._cell).split()).replace("|", "/")
            self._row.extend([text] * self._colspan)
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


def _grid_from_html(html: str) -> Grid:
    parser = _HtmlTable()
    parser.feed(html)
    return parser.rows


def _grid_from_pdf_text(page: pymupdf.Page, rect: pymupdf.Rect, caption: str) -> Grid:
    """Susun ulang baris dan kolom dari posisi teks di text layer PDF; [] bila tidak berbentuk tabel.

    Baris = potongan teks yang sejajar vertikal. Batas kolom diambil dari baris yang kolomnya
    lengkap; potongan teks lain masuk ke kolom yang rentangnya ia tumpangi.
    """
    caption = " ".join(caption.split()).lower()
    cells: list[tuple[float, float, float, str]] = []  # (x0, y0, x1, teks)
    for block in page.get_text("dict", clip=rect).get("blocks", []):
        for line in block.get("lines", []):
            text = " ".join("".join(span.get("text", "") for span in line.get("spans", [])).split())
            if not text:
                continue
            # Caption di atas tabel ikut terpotong ke dalam area tabel: bukan sel.
            if caption and ((len(text) >= 5 and text.lower() in caption) or TABLE_LABEL.match(text)):
                continue
            x0, y0, x1, _ = line["bbox"]
            cells.append((x0, y0, x1, text))
    if not cells:
        return []

    cells.sort(key=lambda cell: (cell[1], cell[0]))
    rows: list[list[tuple[float, float, float, str]]] = []
    for cell in cells:
        if rows and abs(cell[1] - rows[-1][0][1]) <= ROW_GAP_PT:
            rows[-1].append(cell)
        else:
            rows.append([cell])
    for row in rows:
        row.sort(key=lambda cell: cell[0])

    width = max(len(row) for row in rows)
    if width < 2 or len(rows) < 2:
        return []
    full_rows = [row for row in rows if len(row) == width]
    columns = [
        (min(row[i][0] for row in full_rows), max(row[i][2] for row in full_rows)) for i in range(width)
    ]

    grid: Grid = []
    for row in rows:
        values = [""] * width
        for x0, _, x1, text in row:
            hits = [i for i, (left, right) in enumerate(columns) if min(x1, right) - max(x0, left) > -COLUMN_SLACK_PT]
            if not hits:
                center = (x0 + x1) / 2
                hits = [min(range(width), key=lambda i: abs(center - (columns[i][0] + columns[i][1]) / 2))]
            for i in hits:
                values[i] = f"{values[i]} {text}".strip()
        grid.append(values)
    return grid


def _grid_from_spaced_text(body: str) -> Grid:
    """Teks polos berkolom dua spasi atau lebih → baris dan kolom; [] bila tidak berkolom.

    Baris yang kurang kolom dan menjorok dianggap rata kanan, selain itu rata kiri.
    """
    lines = [line for line in body.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    rows = [[cell.strip() for cell in re.split(r"\s{2,}", line.strip()) if cell.strip()] for line in lines]
    width = max(len(row) for row in rows)
    if width < 2:
        return []
    return [
        [""] * (width - len(row)) + row if line.startswith("  ") else row + [""] * (width - len(row))
        for line, row in zip(lines, rows)
    ]

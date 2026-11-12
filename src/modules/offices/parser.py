"""File office (.docx, .doc, .odt, .rtf, .pptx) → PDF → jalur PDF.

Dari ``_parse_office`` di router lama hybrid_rag: tidak ada parser office tersendiri, dokumennya
dikonversi unoserver lalu dibaca seperti PDF biasa.
"""
import shutil
from dataclasses import replace
from pathlib import Path

from src.modules.contract import Layout, ParseOptions
from src.modules.offices.convert import convert_office_to_pdf
from src.modules.pdf import parser as pdf_parser


async def parse(path: Path, tmp_dir: Path, options: ParseOptions) -> tuple[Layout, list[dict]]:
    """Konversi lalu parse. PDF hasil konversi dipindah ke ``tmp_dir`` agar ikut dibersihkan.

    pptx selalu dek slide, apa pun rasio halamannya.
    """
    converted = Path(await convert_office_to_pdf(str(path)))
    pdf = tmp_dir / converted.name
    shutil.move(converted, pdf)
    shutil.rmtree(converted.parent, ignore_errors=True)
    # ``pages`` adalah pilihan halaman PDF dari pemanggil; dokumen office selalu dibaca utuh.
    return await pdf_parser.parse(pdf, tmp_dir, replace(options, pages=None), slides=path.suffix.lower() == ".pptx")

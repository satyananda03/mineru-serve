"""Jalankan parser MinerU pada kasus uji paritas; hasil ke ``.work/mineru/<kasus>.json``.

Dari root repo: ``python tests/parity/run_mineru.py`` (semua) atau ``... run_mineru.py skew ccitt``.
Lalu ``python tests/parity/compare.py``.
"""
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.parity.cases import WORK, prepare


def main() -> None:
    from src.modules.mineru_parser import parse_pdf

    out = WORK / "mineru"
    out.mkdir(parents=True, exist_ok=True)
    for case in prepare(sys.argv[1:]):
        started = time.time()
        try:
            result = {"ok": True, "items": parse_pdf(case["pdf"], out / case["name"] / "images")}
        except Exception as error:
            result = {"ok": False, "error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-1500:]}
        result["elapsed_s"] = round(time.time() - started, 1)
        (out / f"{case['name']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(case["name"], "ok" if result["ok"] else result["error"][:200], f"{result['elapsed_s']}s", flush=True)


if __name__ == "__main__":  # MinerU memakai multiprocessing spawn: guard ini wajib
    main()

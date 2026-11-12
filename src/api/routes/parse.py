"""Endpoint parse: unggah file → job; ambil status dan hasil job.

Parsing bisa berjalan menit, jadi polanya asinkron: ``POST /parse`` mengembalikan ``job_id``, lalu
pemanggil mengambil hasilnya di ``GET /parse/{job_id}``.
"""
import secrets
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile

from src.core.config import settings
from src.jobs.job_queue import Job, JobQueue
from src.jobs.parse_job import ParseRequest
from src.modules.contract import ParseOptions
from src.modules.router import check_file, file_type, is_light


def require_api_key(x_api_key: str | None = Header(None)) -> None:
    """Tolak pemanggil tanpa ``X-API-Key`` yang benar. Tanpa ``PARSER_API_KEY`` (lokal) tidak ada pemeriksaan."""
    expected = settings.parser_api_key
    if expected and not secrets.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="X-API-Key tidak ada atau salah.")


router = APIRouter(dependencies=[Depends(require_api_key)])


def _job_queue(request: Request) -> JobQueue:
    return request.app.state.jobs


def _status(job: Job) -> dict:
    return {"job_id": job.id, "status": job.status, "error": job.error, "result": job.result}


@router.post("/parse", status_code=202, summary="Unggah file untuk diparse")
def submit_parse(
    request: Request,
    file: UploadFile = File(..., description="pdf, docx, pptx, xlsx, gambar, md, txt, atau json content list"),
    tier: str = Form("basic", description="'basic' (default) atau 'flash'; berlaku untuk PDF dan gambar"),
    pages: str | None = Form(None, description="Halaman PDF 1-based, mis. '4' atau '1-3,8'; kosong = semua"),
) -> dict:
    """Mulai job parse; jawabannya ``{job_id, status, error, result}``.

    File besar masuk antrean (``status: queued``). File ringan (md, txt, json) dikerjakan langsung,
    jadi jawabannya sudah ``succeeded`` beserta ``result``.
    """
    filename = Path(file.filename or "").name
    try:
        ext = file_type(filename)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    work_dir = Path(tempfile.mkdtemp(prefix="parser_job_"))
    path = work_dir / "upload" / filename
    path.parent.mkdir()
    with open(path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    options = ParseOptions(tier=tier.strip().lower(), pages=pages)
    try:
        check_file(path, options)
    except ValueError as error:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(error)) from error

    jobs = _job_queue(request)
    parse_request = ParseRequest(path=path, work_dir=work_dir, options=options)
    return _status(jobs.run_now(parse_request) if is_light(ext) else jobs.submit(parse_request))


@router.get("/parse/{job_id}", summary="Status dan hasil job parse")
def get_parse(job_id: str, request: Request) -> dict:
    """``status``: ``queued`` → ``running`` → ``succeeded`` atau ``failed``.

    Saat ``succeeded``, ``result`` berisi ``file_type``, ``layout`` (``document`` | ``slides`` |
    ``sheet``), ``content_list`` (figure sudah berupa URL S3) dan ``elapsed_seconds``. Saat
    ``failed``, ``error`` berisi sebabnya. Job hilang setelah server restart atau melewati masa simpan.
    """
    job = _job_queue(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} tidak ditemukan (sudah kedaluwarsa atau server restart).")
    return _status(job)

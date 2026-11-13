"""Endpoint parse: unggah file → job; ambil status dan hasil job.

Parsing bisa berjalan menit, jadi polanya asinkron: ``POST /parse`` mengembalikan ``job_id``, lalu
pemanggil mengambil hasilnya di ``GET /parse/{job_id}``.
"""
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Header, HTTPException

from src.api.schemas.parse import ParseForm, ParseJob
from src.core.config import settings
from src.jobs import job_queue
from src.jobs.parse_job import ParseRequest
from src.modules.contract import ParseOptions
from src.modules.router import check_file, file_type, is_light


def require_api_key(x_api_key: str | None = Header(None)) -> None:
    """Tolak pemanggil tanpa ``X-API-Key`` yang benar. Tanpa ``PARSER_API_KEY`` (lokal) tidak ada pemeriksaan."""
    expected = settings.parser_api_key
    if expected and not secrets.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="X-API-Key tidak ada atau salah.")


router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/parse", status_code=202, response_model=ParseJob, summary="Unggah file untuk diparse")
def submit_parse(form: Annotated[ParseForm, Form(media_type="multipart/form-data")]) -> dict:
    """Mulai job parse; jawabannya ``{job_id, status, error, result}``.

    File besar masuk antrean (``status: queued``). File ringan (md, txt, json) dikerjakan langsung,
    jadi jawabannya sudah ``succeeded`` beserta ``result``.
    """
    file = form.file
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
    options = ParseOptions(tier=form.tier, pages=form.pages)
    try:
        check_file(path, options)
    except ValueError as error:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(error)) from error

    if is_light(ext):
        return job_queue.run_now(ParseRequest(path=path, work_dir=work_dir, options=options))
    try:
        return job_queue.submit(path, options)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)  # worker mengambil filenya dari S3


@router.get("/parse/{job_id}", response_model=ParseJob, summary="Status dan hasil job parse")
def get_parse(job_id: str) -> dict:
    """``status``: ``queued`` → ``running`` → ``succeeded`` atau ``failed``.

    Saat ``succeeded``, ``result`` berisi ``file_type``, ``layout`` (``document`` | ``slides`` |
    ``sheet``), ``content_list`` (figure sudah berupa URL S3) dan ``elapsed_seconds``. Saat
    ``failed``, ``error`` berisi sebabnya. Job hilang setelah melewati masa simpan (``JOB_TTL_SECONDS``).
    """
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} tidak ditemukan (ID salah atau sudah kedaluwarsa).")
    return job

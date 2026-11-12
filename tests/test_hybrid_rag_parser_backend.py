"""Cek pemilihan backend parser di hybrid_rag dan backend ``external``, dengan server parser palsu.

Jalankan dari root repo: ``python tests/test_hybrid_rag_parser_backend.py`` (atau ``pytest tests``).
"""
import asyncio
import sys
import tempfile
import types
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from hybrid_rag.config import settings
from hybrid_rag.ingestion.parser import external
from hybrid_rag.ingestion.parser.parse import parse_file

CONTENT_LIST = [{"type": "text", "text": "isi", "page_idx": 0, "layout": "document"}]
RESULT = {"file_type": "pdf", "layout": "document", "content_list": CONTENT_LIST, "elapsed_seconds": 1.5}


def job(status, **extra):
    return {"job_id": "j1", "status": status, "error": None, "result": None, **extra}


class FakeParserServer:
    """Menjawab ``POST /parse`` dengan ``first``, lalu tiap ``GET /parse/j1`` dengan giliran berikutnya di ``polls``."""

    def __init__(self, first, polls=()):
        self.first, self.polls, self.requests = first, list(polls), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.first if request.method == "POST" else self.polls.pop(0)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)


@contextmanager
def parser_server(server, timeout=1800.0):
    """Arahkan backend external ke ``server`` palsu, tanpa jeda polling."""
    saved = (settings.parser_binding_host, settings.parser_binding_api_key, settings.parser_timeout,
             external._transport, external.POLL_FIRST_S, external.POLL_MAX_S)
    settings.parser_binding_host, settings.parser_binding_api_key, settings.parser_timeout = "http://parser", "kunci", timeout
    external._transport, external.POLL_FIRST_S, external.POLL_MAX_S = httpx.MockTransport(server), 0.0, 0.0
    try:
        yield server
    finally:
        (settings.parser_binding_host, settings.parser_binding_api_key, settings.parser_timeout,
         external._transport, external.POLL_FIRST_S, external.POLL_MAX_S) = saved


def parse(name="dokumen.pdf", **kwargs):
    async def run():
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / name
            path.write_bytes(b"%PDF-isi")
            async with parse_file(path, **kwargs) as content_list:
                return content_list
    return asyncio.run(run())


def raised(action, error_type) -> str:
    try:
        action()
    except error_type as error:
        return str(error)
    raise AssertionError(f"seharusnya melempar {error_type.__name__}")


def test_external_uploads_then_polls_until_the_job_succeeds():
    server = FakeParserServer(job("queued"), [job("queued"), job("running"), job("succeeded", result=RESULT)])
    with parser_server(server):
        assert parse(parser_backend="external") == CONTENT_LIST
    upload, *polls = server.requests
    assert (upload.method, upload.url.path, upload.headers["x-api-key"]) == ("POST", "/parse", "kunci")
    assert b'filename="dokumen.pdf"' in upload.content and b"%PDF-isi" in upload.content
    assert [(r.method, r.url.path) for r in polls] == [("GET", "/parse/j1")] * 3


def test_light_file_that_is_done_on_upload_is_not_polled():
    server = FakeParserServer(job("succeeded", result=RESULT))
    with parser_server(server):
        assert parse("catatan.md", parser_backend="external") == CONTENT_LIST
    assert len(server.requests) == 1


def test_server_failures_surface_with_the_servers_own_explanation():
    with parser_server(FakeParserServer(job("queued"), [job("failed", error="RuntimeError: unoserver mati")])):
        assert "unoserver mati" in raised(lambda: parse(parser_backend="external"), external.ParserServerError)
    rejected = httpx.Response(400, json={"detail": "File PDF tidak valid atau rusak"})
    with parser_server(FakeParserServer(rejected)):
        message = raised(lambda: parse(parser_backend="external"), external.ParserServerError)
        assert "HTTP 400" in message and "tidak valid atau rusak" in message
    lost = httpx.Response(404, json={"detail": "Job j1 tidak ditemukan"})
    with parser_server(FakeParserServer(job("queued"), [lost])):
        assert "tidak ditemukan" in raised(lambda: parse(parser_backend="external"), external.ParserServerError)


def test_timeout_counts_from_running_not_from_queued():
    waiting = [job("queued")] * 5
    with parser_server(FakeParserServer(job("queued"), [*waiting, job("succeeded", result=RESULT)]), timeout=0.0):
        assert parse(parser_backend="external") == CONTENT_LIST  # antre lama bukan timeout
    with parser_server(FakeParserServer(job("queued"), [job("running")] * 3), timeout=0.0):
        assert "belum selesai" in raised(lambda: parse(parser_backend="external"), TimeoutError)


def test_external_rejects_before_uploading_what_cannot_work():
    server = FakeParserServer(job("succeeded", result=RESULT))
    with parser_server(server):
        assert "tidak didukung" in raised(lambda: parse("program.exe", parser_backend="external"), ValueError)
        settings.parser_binding_host = None
        assert "PARSER_BINDING_HOST" in raised(lambda: parse(parser_backend="external"), RuntimeError)
    assert server.requests == []

    async def missing():
        async with parse_file("/tidak/ada.pdf", parser_backend="external"):
            pass
    raised(lambda: asyncio.run(missing()), FileNotFoundError)


def test_backend_follows_the_setting_unless_the_call_overrides_it():
    calls = []

    @asynccontextmanager
    async def builtin_parse_file(file_path, entity_registry=None):
        calls.append((Path(file_path).name, entity_registry))
        yield ["dari builtin"]

    # Backend bawaan diganti tiruan: parser aslinya butuh Textract dan dependensi lain.
    stub = types.ModuleType("hybrid_rag.ingestion.parser.router")
    stub.parse_file = builtin_parse_file
    sys.modules["hybrid_rag.ingestion.parser.router"] = stub
    import hybrid_rag.ingestion.parser as package
    package.router = stub
    saved = settings.parser_backend
    try:
        assert settings.parser_backend == "builtin"
        assert parse(entity_registry="iccn") == ["dari builtin"] and calls == [("dokumen.pdf", "iccn")]
        with parser_server(FakeParserServer(job("succeeded", result=RESULT))):
            assert parse(parser_backend="external") == CONTENT_LIST
            settings.parser_backend = "external"
            assert parse() == CONTENT_LIST
            assert parse(parser_backend="builtin") == ["dari builtin"]
        assert "builtin" in raised(lambda: parse(parser_backend="remote"), ValueError)
    finally:
        settings.parser_backend = saved
        del sys.modules["hybrid_rag.ingestion.parser.router"]
        del package.router


if __name__ == "__main__":
    tests = [check for name, check in list(globals().items()) if name.startswith("test_")]
    for check in tests:
        check()
        print("ok", check.__name__)
    print(f"{len(tests)} cek lolos")

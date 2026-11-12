"""Kebijakan retry bersama untuk semua klien model (LLM, VLM, embedding, rerank).

Retry tenacity per instance; SDK dipasang ``max_retries=0`` supaya dua lapis retry tidak berlipat.
"""
import asyncio
import functools
import logging
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
import openai
from tenacity import before_sleep_log, retry, retry_if_exception, stop_after_attempt

from src.core.logging import get_logger

logger = get_logger(__name__)

_PROXY_FLAP_MARKERS = ("model identifier is invalid", "available model group fallbacks")


def _is_proxy_flap(body: str) -> bool:
    """LiteLLM sesekali menjawab 400 "model identifier is invalid" untuk model yang sah; request ulang berhasil."""
    lowered = (body or "").lower()
    return any(marker in lowered for marker in _PROXY_FLAP_MARKERS)


def is_transient(exc: BaseException) -> bool:
    """True kalau mengirim ulang permintaan yang sama bisa berhasil."""
    if isinstance(exc, httpx.HTTPStatusError):  # jalur rerank
        code = exc.response.status_code
        return code in (408, 429) or code >= 500 or (code == 400 and _is_proxy_flap(exc.response.text))
    if isinstance(exc, (httpx.TransportError, TimeoutError)):  # TimeoutError: stream macet di langchain-openai
        return True
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        code = exc.status_code
        return code in (408, 409, 429) or code >= 500 or (code == 400 and _is_proxy_flap(str(exc)))
    return False


def _seconds(value) -> float | None:
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            delay = (parsedate_to_datetime(str(value)).astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    return max(0.0, float(math.ceil(delay)))


def retry_delay(exc: BaseException | None, attempt: int) -> float:
    """`retry_after` dari provider (body JSON, lalu header) kalau ada; kalau tidak 1s, 2s, 4s, maksimal 8s.

    Cloudflare 524 dari binding membawa ``{"retry_after": 120}``: mengulang setelah 1–2 detik hanya
    masuk lagi ke origin yang sama sibuknya.
    """
    body = getattr(exc, "body", None)
    headers = getattr(getattr(exc, "response", None), "headers", None)
    delay = _seconds(body.get("retry_after")) if isinstance(body, dict) else None
    if delay is None and headers is not None:
        delay = _seconds(headers.get("retry-after"))
    return delay if delay is not None else min(8.0, 2.0 ** (attempt - 1))


def _wait(state) -> float:
    return retry_delay(state.outcome.exception(), state.attempt_number)


def with_retry(attempts):
    """Retry sync/async atas :func:`is_transient`; ``attempts(*args)`` = jumlah percobaan untuk panggilan ini.

    ``reraise=True``: pemanggil melihat error aslinya, bukan ``RetryError``.
    """
    def decorate(func):
        def policy(*args):
            return retry(stop=stop_after_attempt(max(1, attempts(*args))), wait=_wait,
                         retry=retry_if_exception(is_transient),
                         before_sleep=before_sleep_log(logger, logging.WARNING), reraise=True)(func)

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def awrapper(*args, **kwargs):
                return await policy(*args)(*args, **kwargs)
            return awrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return policy(*args)(*args, **kwargs)
        return wrapper

    return decorate


per_instance = with_retry(lambda self, *_: self.retry_attempts)

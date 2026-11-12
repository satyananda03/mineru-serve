"""Klien chat (LLM): ``RetryingChat``, factory ``get_llm`` (signature = hook ``hybrid_rag.providers``),
dan helper invoke bersama: chain terstruktur dari prompt YAML, penanda prompt cache, hitung token.
"""
import asyncio
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from src.core.config import CONTEXT_BUDGET_TOKENS, MODEL_CONTEXT_WINDOWS, MODELS_WITHOUT_TEMPERATURE, NOVA_MODELS, settings
from src.core.logging import get_logger
from src.services.prompt_service import load_chat_prompt_template
from src.services.retry_service import is_transient, per_instance, retry_delay

logger = get_logger(__name__)

_NO_CACHE = {"cache": {"no-cache": True}}

#: ID tool call yang diterima semua model chat (Bedrock/Anthropic: [A-Za-z0-9_-], OpenAI: ≤ 40 karakter).
_PORTABLE_TOOL_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")


def portable_tool_call_id(tool_call_id: str) -> str:
    """ID dari model lain (Kimi: ``functions.get_rubric:1``) → ID yang diterima model mana pun saat model diganti
    di tengah percakapan. Deterministik: tool call dan hasil tool-nya tetap berpasangan, prompt cache tetap kena.

    ponytail: duplikat ``_sanitize_bedrock_tool_use_id`` LiteLLM (sudah ada di 1.105.7); hapus setelah proxy
    LiteLLM di server di-upgrade.
    """
    if _PORTABLE_TOOL_CALL_ID.fullmatch(tool_call_id):
        return tool_call_id
    return "call_" + hashlib.sha256(tool_call_id.encode()).hexdigest()[:24]
_NOVA_REASONING = {"reasoningConfig": {"type": "enabled", "maxReasoningEffort": "medium"}}

def _is_empty(result) -> bool:
    """Respons tanpa teks dan tanpa tool call."""
    message = result.generations[0].message if result.generations else None
    return message is None or (not message.text.strip() and not getattr(message, "tool_calls", None))


def _is_exhausted_empty(result) -> bool:
    """Completion yang menghabiskan max_tokens tidak membaik bila request identik diulang."""
    message = result.generations[0].message if result.generations else None
    return bool(message and _is_empty(result) and message.response_metadata.get("finish_reason") == "length")


class RetryingChat(ChatOpenAI):
    """``ChatOpenAI`` dengan retry sendiri, retry untuk respons kosong, ``cache_control`` pada pesan tool, dan ID
    tool call yang diterima semua model.

    langchain_openai membuang ``cache_control`` blok konten pesan tool saat konversi, padahal LiteLLM
    membacanya di level pesan; tanpa itu riwayat agent tidak pernah dibaca dari prompt cache.
    ID tool call dinormalisasi di payload saja (:func:`portable_tool_call_id`); riwayat tersimpan tidak berubah.
    """
    retry_attempts: int = 1

    def _get_request_payload(self, input_, *, stop=None, **kwargs) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for m, d in zip(self._convert_input(input_).to_messages(), payload["messages"]):
            if m.type == "tool" and isinstance(m.content, list):
                cc = next((b["cache_control"] for b in m.content if isinstance(b, dict) and "cache_control" in b), None)
                if cc:
                    d["cache_control"] = cc
            for call in d.get("tool_calls") or []:
                call["id"] = portable_tool_call_id(call["id"])
            if d.get("tool_call_id"):
                d["tool_call_id"] = portable_tool_call_id(d["tool_call_id"])
        return payload

    @per_instance
    def _generate_with_cache(self, *args, **kwargs):
        return super()._generate_with_cache(*args, **kwargs)

    async def _agenerate_with_cache(self, messages, stop=None, run_manager=None, **kwargs):
        caller = (getattr(run_manager, "metadata", None) or {}).get("caller", "?")
        attempts = max(1, self.retry_attempts)
        for attempt in range(1, attempts + 1):
            retry_exc: BaseException | None = None
            if attempt > 1:
                # Ulangan melewati cache proxy; extra_body level call menimpa milik model, jadi digabung dulu.
                kwargs["extra_body"] = {**(self.extra_body or {}), **(kwargs.get("extra_body") or {}), **_NO_CACHE}
            try:
                result = await super()._agenerate_with_cache(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as exc:
                if attempt == attempts or not is_transient(exc):
                    raise
                retry_exc, reason = exc, f"{type(exc).__name__}: {str(exc)[:160]}"
            else:
                if _is_exhausted_empty(result):
                    message = result.generations[0].message
                    logger.warning("[llm] caller=%s %s completion habis tanpa teks/tool call (finish=length, tokens_out=%s); tidak diulang",
                                   caller, self.model_name, (message.usage_metadata or {}).get("output_tokens"))
                    return result
                if not _is_empty(result) or attempt == attempts:
                    return result
                reason = "respons kosong (tanpa teks, tanpa tool call)"
            wait = retry_delay(retry_exc, attempt)
            # Ukuran prefill ikut dicatat supaya 524 bisa dipilah: payload besar (waktu prefill) vs blackout provider.
            size = sum(len(m.text) for m in messages)
            logger.warning("[llm] caller=%s %s percobaan %d/%d gagal (%d pesan, ~%dK char): %s; ulang dalam %ds",
                           caller, self.model_name, attempt, attempts, len(messages), size // 1000, reason, wait)
            await asyncio.sleep(wait)


@lru_cache(maxsize=100)
def get_llm(model_id: str, *, base_url: str | None = None, api_key: str | None = None, timeout: float | None = None,
            max_retries: int | None = None, max_tokens: int | None = 500, streaming: bool = False,
            temperature: float | None = 0.0) -> RetryingChat:
    """Klien chat; binding default ``LLM_BINDING_*``. ``temperature`` dibuang untuk model yang menolaknya."""
    window = MODEL_CONTEXT_WINDOWS.get(model_id)
    budget = {"profile": {"max_input_tokens": min(window, CONTEXT_BUDGET_TOKENS)}} if window else {}
    return RetryingChat(
        model=model_id, base_url=base_url or settings.llm_binding_host, api_key=api_key or settings.llm_binding_api_key,
        temperature=None if model_id in MODELS_WITHOUT_TEMPERATURE else temperature, max_tokens=max_tokens,
        extra_body=_NOVA_REASONING if model_id in NOVA_MODELS else None, streaming=streaming, stream_usage=True,
        timeout=timeout, max_retries=0, retry_attempts=settings.max_retries if max_retries is None else max_retries,
        **budget,
    )

def tandai_riwayat(msgs: list) -> list:
    """Satu penanda cache di pesan terakhir (selain system): seluruh riwayat sampai titik ini dibaca dari cache pada
    panggilan berikutnya. Penanda lama dicabut supaya batas jumlah breakpoint cache tidak terlampaui."""
    for m in msgs[1:]:
        if isinstance(m.content, list):
            for blok in m.content:
                if isinstance(blok, dict):
                    blok.pop("cache_control", None)
    last = msgs[-1]
    if isinstance(last.content, str):
        last.content = [{"type": "text", "text": last.content}]
    last.content[-1]["cache_control"] = {"type": "ephemeral"}
    return msgs


def cache_prompt(msgs: list) -> list:
    """Penanda cache di akhir system prompt, dan di akhir awalan bersama bila pesan user terdiri dari beberapa blok
    (semua blok kecuali yang terakhir, lihat ``user_prompt`` berupa daftar di prompt YAML)."""
    if msgs and isinstance(msgs[0], SystemMessage):
        msgs[0] = SystemMessage(content=[{"type": "text", "text": msgs[0].content,
                                        "cache_control": {"type": "ephemeral"}}])
    last = msgs[-1] if msgs else None
    if isinstance(last, HumanMessage) and isinstance(last.content, list) and len(last.content) > 1:
        last.content[-2] = {**last.content[-2], "cache_control": {"type": "ephemeral"}}
    return msgs


#: Percobaan satu panggilan terstruktur, termasuk perbaikan setelah argumen tool ditolak validasi skema.
STRUCTURED_ATTEMPTS = 3

_LEAKED_PARAMETER = re.compile(r'<parameter name="(\w+)">(.*?)(?=</parameter>|<parameter name="|$)', re.S)


def repair_tool_args(args: dict) -> dict:
    """Pulihkan dua slip encoding tool call tanpa memanggil model lagi:

    - parameter berikutnya tertulis DI DALAM nilai string sebelumnya (``"…</parameter><parameter name="status">met"``);
    - list/objek dikirim sebagai string JSON, kadang memuat sisa argumen (``'[{…}], "alasan": "…", "status": "…"}'``).
    Parameter yang sudah ada tidak ditimpa.
    """
    repaired = dict(args)
    for key, value in args.items():
        if not isinstance(value, str):
            continue
        head, marker, tail = value.partition('<parameter name="')
        if marker:
            repaired[key] = head.strip().removesuffix("</parameter>").rstrip()
            for name, content in _LEAKED_PARAMETER.findall(marker + tail):
                repaired.setdefault(name, content.strip())
        elif value.lstrip()[:1] in "[{":
            for candidate in (value, f'{{"{key}": {value}', f'{{"{key}": {value}}}'):
                try:
                    parsed = json.loads(candidate)
                except ValueError:
                    continue
                if candidate is value:
                    repaired[key] = parsed
                elif isinstance(parsed, dict):
                    repaired |= {name: item for name, item in parsed.items() if name == key or name not in args}
                break
    return repaired


class StructuredChain:
    """YAML prompt -> cache_control -> forced tool use -> ``{"raw": AIMessage, "parsed": schema}``.

    Argumen tool yang ditolak skema dikembalikan ke model sebagai hasil tool berisi pesan galatnya, lalu model
    memanggil ulang. Mengulang request yang identik pada temperature 0 cenderung menghasilkan galat yang sama.

    ``reasoning_effort``: tool_choice "auto" alih-alih paksa, karena Claude di Bedrock diam-diam mematikan thinking
    bila tool dipaksa. Model boleh tidak memanggil tool, jadi itu diperlakukan seperti argumen yang ditolak. Token
    thinking ikut ``max_tokens``.
    """

    def __init__(self, llm: RetryingChat, prompts: str | Path, prompt_name: str, schema, reasoning_effort: str | None = None):
        self._prompt = load_chat_prompt_template(prompts, prompt_name)
        self._tool, self._schema, self._thinking = schema.__name__, schema, reasoning_effort is not None
        if self._thinking:
            self._llm = llm.bind_tools([schema], tool_choice="auto", reasoning_effort=reasoning_effort) | self._parsed
        else:
            self._llm = llm.with_structured_output(schema, method="function_calling", include_raw=True)

    def _parsed(self, raw) -> dict:
        """Keluaran ``bind_tools`` dalam bentuk ``with_structured_output(include_raw=True)``."""
        for call in raw.tool_calls:
            if call["name"] == self._tool:
                try:
                    return {"raw": raw, "parsed": self._schema.model_validate(call["args"]), "parsing_error": None}
                except ValidationError as exc:
                    return {"raw": raw, "parsed": None, "parsing_error": exc}
        return {"raw": raw, "parsed": None, "parsing_error": f"{self._tool} was not called"}

    def _repaired(self, raw):
        """Skema terisi dari argumen yang dipulihkan ``repair_tool_args``; None bila tetap tidak valid."""
        for call in raw.tool_calls:
            if call["name"] == self._tool:
                try:
                    return self._schema.model_validate(repair_tool_args(call["args"]))
                except ValidationError:
                    return None
        return None

    async def ainvoke(self, variables: dict) -> dict:
        msgs = prompt_msgs = cache_prompt(self._prompt.format_messages(**variables))
        for attempt in range(1, STRUCTURED_ATTEMPTS + 1):
            out = await self._llm.ainvoke(msgs)
            if out["parsing_error"] is None and out["parsed"] is not None:
                return out
            if (parsed := self._repaired(out["raw"])) is not None:
                logger.info("%s: argumen tool dipulihkan tanpa memanggil ulang model", self._tool)
                return {**out, "parsed": parsed, "parsing_error": None}
            logger.warning("%s: argumen tool ditolak (percobaan %d/%d): %s", self._tool, attempt, STRUCTURED_ATTEMPTS,
                           str(out["parsing_error"])[:300])
            raw = out["raw"]
            # Pydantic memotong input_value di pesan galat; ekor tiap string menunjukkan bentuk slip (parameter bocor).
            logger.warning("%s: argumen mentah (ekor): %s", self._tool,
                           [{k: v[-200:] if isinstance(v, str) else type(v).__name__ for k, v in (c.get("args") or {}).items()}
                            for c in [*raw.tool_calls, *raw.invalid_tool_calls]])
            feedback = (f"Invalid {self._tool} arguments: {out['parsing_error']}. Call {self._tool} again with every "
                        "required field as its own argument.")
            calls = [*raw.tool_calls, *raw.invalid_tool_calls]
            if self._thinking:  # an assistant tool call sent back without its thinking block is rejected by the API
                msgs = [*prompt_msgs, HumanMessage(content=feedback)]
            elif calls:
                msgs = [*msgs, raw, *[ToolMessage(content=feedback, tool_call_id=c["id"]) for c in calls]]
            else:
                msgs = [*msgs, raw, HumanMessage(content=feedback)]
        raise OutputParserException(f"output tidak valid setelah {STRUCTURED_ATTEMPTS} percobaan: {out['parsing_error']}")


def structured_chain(llm: RetryingChat, prompts: str | Path, prompt_name: str, schema,
                     reasoning_effort: str | None = None) -> StructuredChain:
    return StructuredChain(llm, prompts, prompt_name, schema, reasoning_effort)

def usage_of(msg) -> dict:
    u = getattr(msg, "usage_metadata", None) or {}
    d = u.get("input_token_details") or {}
    return {"in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0),
            "cache_read": d.get("cache_read", 0), "cache_write": d.get("cache_creation", 0)}

def add_usage(total: dict, u: dict) -> dict:
    return {k: total.get(k, 0) + u.get(k, 0) for k in ("in", "out", "cache_read", "cache_write")}
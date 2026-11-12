"""Transkripsi satu slide oleh VLM: gambar slide + text layer → Markdown dan tabel terstruktur.

Porting bagian slide dari hybrid_rag, logikanya tidak diubah:

* skema keluaran dan pesan       — ``ingestion/multimodal/chain.py``
* tanya ulang bila tidak valid   — ``core/llm_cache.py`` (``_ask``, ``REASK_PROMPT``)
* tipe ``Prose``                 — ``ingestion/text_cleaning.py``

Modelnya dibuat klien yang sama dengan aplikasi host (``src/services/vlm_service.py``). Yang tidak
ikut: cache LLM, karena cache itu menempel pada penyimpanan RAG.
"""
import logging
import re
from functools import cache
from pathlib import Path
from typing import Annotated, Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from openai import LengthFinishReasonError
from pydantic import AfterValidator, BaseModel, Field, ValidationError

from src.core.config import settings
from src.services.prompt_service import load_prompt
from src.services.vlm_service import get_vlm

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent / "prompt.yaml"

# Model families whose endpoint rejects the field outright (Bedrock: "This model doesn't
# support the temperature field"), so it is never sent to them.
_NO_TEMPERATURE_FAMILIES = ("grok",)

# A model reply that breaks its output schema as a whole (invalid JSON, a missing
# or mistyped field, or JSON cut off at max_tokens because the model ran on).
# Asking again can succeed; infrastructure errors are not in here.
INVALID_OUTPUT_ERRORS = (ValidationError, OutputParserException, LengthFinishReasonError)

# Sent after the original messages when a reply broke the schema. Changing the
# request is the point: the same request gets the same reply back, from the
# LLM proxy's response cache or from the model itself at temperature 0.
REASK_PROMPT = (
    "Your previous reply was rejected because it does not match the required output schema:\n"
    "{error}\n\n"
    "Answer the same request again. Return every required field, each at the nesting level "
    "the schema defines, and nothing else."
)

_FORMFEED_LATEX_PATTERN = re.compile(r"\x0c(?=[A-Za-z])")
_BACKSPACE_LATEX_PATTERN = re.compile(r"\x08(?=[A-Za-z])")
# Whitespace + residue spelling that completes a common LaTeX command whose
# remainder collides with no English word ("eq"/"o"/"exists" are deliberately
# absent: "eq." abbreviations, the word "o"/"exists" would false-positive).
_WS_LATEX_SUSPECT_PATTERN = re.compile(
    r"\t(?=(?:au|heta|imes|ext|ilde|herefore|riangle)\b)"
    r"|\r(?=(?:ho|ight|angle|ceil)\b)"
    r"|\n(?=(?:abla|otin)\b)"
)


def repair_vlm_json_escape_damage(text: str, *, context: str = "") -> str:
    """Restore LaTeX backslashes destroyed by JSON escape decoding.

    Applied to string values parsed out of VLM/LLM JSON responses, where an
    un-doubled LaTeX command like ``"\\frac"`` arrives as ``\\x0c`` + ``rac``.
    Only the two zero-risk cases are repaired:

    - form feed + letter  -> ``\\f`` + letter (``\\frac``, ``\\forall``, ...)
    - backspace + letter  -> ``\\b`` + letter (``\\beta``, ``\\bar``, ...)

    Isolated control characters (not followed by a letter) are left alone for
    downstream sanitization to drop. Whitespace-class damage (``\\tau`` ->
    tab + ``au`` etc.) is ambiguous with legitimate whitespace and is only
    logged at WARNING level, never rewritten.
    """
    if not text:
        return text

    repaired = _FORMFEED_LATEX_PATTERN.sub(r"\\f", text)
    repaired = _BACKSPACE_LATEX_PATTERN.sub(r"\\b", repaired)
    if repaired != text:
        logger.warning(
            "Repaired LaTeX escape damage (\\f/\\b decoded by JSON parser)%s",
            f" in {context}" if context else "",
        )

    suspect = _WS_LATEX_SUSPECT_PATTERN.search(repaired)
    if suspect:
        snippet = repaired[max(0, suspect.start() - 30) : suspect.start() + 30]
        logger.warning(
            "Suspected whitespace-class LaTeX escape damage%s (not auto-repaired): %r",
            f" in {context}" if context else "",
            snippet,
        )

    return repaired


#: A model-written prose field, with LaTeX backslashes the JSON decoding ate put back.
Prose = Annotated[str, AfterValidator(repair_vlm_json_escape_damage)]


class SlideTable(BaseModel):
    caption: str = Field(
        description="The table's own title or heading as printed on the slide; the slide title when the table has none."
    )
    columns: list[str] = Field(
        description=(
            "Column headers, left to right, exactly as printed. The first entry is the header of the row-label column, "
            "\"\" when that cell is empty."
        )
    )
    rows: list[list[str]] = Field(
        description=(
            "One list per row, top to bottom, one cell per column in the order of `columns`; \"\" for an empty cell. "
            "Keep units and footnote markers (*, **) in the cell where they are printed."
        )
    )
    footnotes: list[str] = Field(
        default_factory=list,
        description="Notes and source lines printed for this table (e.g. '*) Data dari BPS', 'Sumber: BPS 2025'), verbatim.",
    )


class SlideTranscription(BaseModel):
    markdown: Prose = Field(
        description="All slide content that is not inside `tables`, as Markdown following the instructions. Never repeat a table cell here."
    )
    tables: list[SlideTable] = Field(
        default_factory=list,
        description=(
            "Every grid on the slide: values read by row AND column, i.e. cells aligned under shared column headers and beside shared row labels (printed tables, scorecards, matrices such as years x attributes). "
            "NOT tables: charts, org charts, flows, timelines drawn along a line, plain lists, or cards without shared headers. "
            "Empty when the slide has no grid."
        ),
    )


def _chat_prompt(target: str, *, with_image: bool) -> ChatPromptTemplate:
    cfg = load_prompt(target, PROMPT_PATH)
    human: list[dict] = [{"type": "text", "text": cfg["user_prompt"]}]
    if with_image:
        human.append({"type": "image_url", "image_url": {"url": "{image_url}"}})
    return ChatPromptTemplate.from_messages(
        [("system", cfg["system_prompt"]), ("human", human)]
    )


def _temperature_kwargs(model_id: str | None) -> dict[str, Any]:
    """An explicit None for families that reject the field: leaving it out lets the client's own default (0) through."""
    if any(family in (model_id or "").lower() for family in _NO_TEMPERATURE_FAMILIES):
        return {"temperature": None}
    return {}


@cache
def _vlm() -> Runnable:
    """A vision-capable chat model, uncapped: a ``max_tokens`` cap truncates the structured output."""
    settings.require_vlm()
    return get_vlm(
        settings.vlm_model,
        base_url=settings.vlm_binding_host,
        api_key=settings.vlm_binding_api_key,
        timeout=settings.vlm_timeout,
        max_retries=settings.max_retries,
        max_tokens=None,
        **_temperature_kwargs(settings.vlm_model),
    )


async def _ask(llm: Runnable, messages: list[BaseMessage]) -> Any:
    """``llm.ainvoke(messages)``, once more when the reply breaks its schema.

    The retry carries the validation error (:data:`REASK_PROMPT`), so it is a new
    request the model can correct itself on. A second invalid reply propagates.
    """
    try:
        return await llm.ainvoke(messages)
    except INVALID_OUTPUT_ERRORS as e:
        logger.warning(f"invalid structured output, asking again with the error: {str(e)[:500]}")
        feedback = HumanMessage(content=REASK_PROMPT.format(error=str(e)[:2000]))
        return await llm.ainvoke([*messages, feedback])


def slide_transcription_chain() -> Runnable:
    """Vision chain for one whole slide: Markdown text plus each grid as a structured table."""
    prompt = _chat_prompt("slide_transcription", with_image=True)
    llm = _vlm().with_structured_output(SlideTranscription, strict=True)

    async def _invoke(inputs: dict[str, Any]) -> SlideTranscription:
        return await _ask(llm, prompt.format_messages(**inputs))

    return RunnableLambda(_invoke, name="slide_transcription")

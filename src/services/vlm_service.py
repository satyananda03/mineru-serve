"""Klien vision (VLM): ``get_vlm``, klien chat dengan binding ``VLM_BINDING_*``."""
from src.core.config import settings
from src.services.llm_service import RetryingChat, get_llm


def get_vlm(model_id: str | None = None, *, base_url: str | None = None, api_key: str | None = None, **kwargs) -> RetryingChat:
    """Klien vision; binding default ``VLM_BINDING_*``, jatuh ke binding LLM."""
    return get_llm(model_id or settings.vlm_model, base_url=base_url or settings.resolved_vlm_binding_host,
                   api_key=api_key or settings.resolved_vlm_binding_api_key, **kwargs)

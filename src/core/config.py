"""Pengaturan layanan, dibaca sekali dari environment (``.env``)."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

NOVA_MODELS: frozenset[str] = frozenset({"mjai.nova-2-lite-v1:0"})
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "global.moonshotai.kimi-k3": 200000,
    "global.anthropic.claude-haiku-5-5": 200000,
    "mjai.kimi-k2.5": 200000,
}
CONTEXT_BUDGET_TOKENS = 120000
MODELS_WITHOUT_TEMPERATURE: frozenset[str] = frozenset({"global.moonshotai.kimi-k3", "global.anthropic.claude-haiku-5-5"})

def _optional(name: str) -> str | None:
    """Nilai env, atau None bila tidak diset atau kosong (``KEY=`` berarti tidak diset)."""
    return os.getenv(name) or None

@dataclass(frozen=True)
class Settings:
    figure_min_width_px: int = int(os.getenv("FIGURE_MIN_WIDTH_PX") or 600)
    figure_min_height_px: int = int(os.getenv("FIGURE_MIN_HEIGHT_PX") or 600)
    figure_min_area_ratio: float = float(os.getenv("FIGURE_MIN_AREA_RATIO") or 0.01)
    s3_bucket: str | None = _optional("S3_BUCKET")
    s3_region: str | None = _optional("S3_REGION")
    s3_access_key_id: str | None = _optional("S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = _optional("S3_SECRET_ACCESS_KEY")
    s3_prefix: str = os.getenv("S3_PREFIX") or "pdf-extractions"
    unoserver_host: str = os.getenv("UNOSERVER_HOST") or "127.0.0.1"
    unoserver_port: int = int(os.getenv("UNOSERVER_PORT") or 2003)
    office_convert_timeout: int = int(os.getenv("OFFICE_CONVERT_TIMEOUT") or 120)
    max_parallel_office_convert: int = int(os.getenv("MAX_PARALLEL_OFFICE_CONVERT") or 1)
    vlm_model: str | None = _optional("VLM_MODEL")
    vlm_binding_host: str | None = _optional("VLM_BINDING_HOST")
    vlm_binding_api_key: str | None = _optional("VLM_BINDING_API_KEY")
    vlm_max_async: int = int(os.getenv("VLM_MAX_ASYNC") or 3)
    vlm_timeout: float = float(os.getenv("VLM_TIMEOUT") or 300.0)
    llm_binding_host: str | None = _optional("LLM_BINDING_HOST") or _optional("LITELLM_PROXY_API_BASE")
    llm_binding_api_key: str | None = _optional("LLM_BINDING_API_KEY") or _optional("LITELLM_PROXY_API_KEY")
    max_retries: int = int(os.getenv("MAX_RETRIES") or 5)
    parser_api_key: str | None = _optional("PARSER_API_KEY")
    job_ttl_seconds: int = int(os.getenv("JOB_TTL_SECONDS") or 3600)
    port: int = int(os.getenv("PORT") or 8000)

    @property
    def resolved_vlm_binding_host(self) -> str | None:
        return self.vlm_binding_host or self.llm_binding_host

    @property
    def resolved_vlm_binding_api_key(self) -> str | None:
        return self.vlm_binding_api_key or self.llm_binding_api_key

    def require_vlm(self) -> None:
        """Error yang jelas bila setting VLM belum lengkap, alih-alih gagal di tengah panggilan model."""
        names = {"VLM_MODEL": self.vlm_model, "VLM_BINDING_HOST": self.vlm_binding_host, "VLM_BINDING_API_KEY": self.vlm_binding_api_key}
        missing = [name for name, value in names.items() if not value]
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

settings = Settings()
"""Satu-satunya loader prompt YAML untuk agent dan workflow.

- :func:`load_chat_prompt_template` — default: ``ChatPromptTemplate`` siap ``.format`` / ``.format_messages`` / ``|``.
- :func:`load_prompt` — string mentah, untuk prompt yang memuat ``{...}`` literal (contoh JSON) atau untuk hash cache.
"""
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


@lru_cache(maxsize=16)
def _load_prompt_file(file_path: Path) -> dict[str, Any]:
    """Parse a prompt YAML file. Cached — prompt files do not change at runtime."""
    try:
        with open(file_path, encoding="utf-8") as f:
            prompts = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Prompt file not found: {file_path}") from e
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing prompt YAML: {file_path}") from e
    if not isinstance(prompts, dict):
        raise ValueError(f"Prompt file must contain a mapping: {file_path}")
    return prompts


def load_prompt(target_prompt: str, file_path: str | Path) -> dict[str, str | list[str]]:
    """Return one prompt's raw ``system_prompt`` / ``user_prompt``.

    Values come back verbatim so the caller can ``str.format`` them with its own
    context. A missing ``user_prompt`` is returned as an empty string. ``user_prompt`` may be a list
    of text blocks: every block but the last is a prefix shared across calls (see ``llm_service.cache_prompt``).
    """
    path = Path(file_path)
    cfg = _load_prompt_file(path).get(target_prompt)
    if cfg is None:
        raise ValueError(f"Prompt template {target_prompt} not found in {path}")
    return {
        "system_prompt": cfg.get("system_prompt", ""),
        "user_prompt": cfg.get("user_prompt", ""),
    }


def load_chat_prompt_template(
    file_path: str | Path, target_prompt: str, include_messages: bool = False
) -> ChatPromptTemplate:
    """Build a LangChain ``ChatPromptTemplate`` from a prompt YAML entry."""
    cfg = load_prompt(target_prompt, file_path)
    messages: list = [("system", cfg["system_prompt"])]
    if include_messages:
        messages.append(MessagesPlaceholder(variable_name="messages"))
    user = cfg["user_prompt"]
    if user:
        messages.append(("human", [{"type": "text", "text": t} for t in user] if isinstance(user, list) else user))
    return ChatPromptTemplate.from_messages(messages)

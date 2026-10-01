"""LLM clients for judges and the feedback generator (docs/ARCHITECTURE.md §5.2, §7.3).

``get_client(provider, api_key=…, base_url=…)`` returns an :class:`forge.domain.ports.LLMClient`:

* ``openai`` — any OpenAI-compatible ``/chat/completions`` endpoint;
* ``anthropic`` — Anthropic Messages API.

Retries on 429/5xx/timeouts use ``FORGE_JUDGE_MAX_RETRIES``. Secrets are never logged.
"""

from __future__ import annotations

from typing import Any

import httpx

from forge.config import settings
from forge.domain.ports import LLMClient
from forge.infra.llm.anthropic import AnthropicClient
from forge.infra.llm.base import (
    LLMError,
    LLMHTTPError,
    LLMRefusalError,
    LLMResponseError,
    LLMTimeoutError,
)
from forge.infra.llm.openai import OpenAICompatibleClient
from forge.infra.llm.pricing import MODEL_PRICES, ModelPrice, estimate_cost, price_for

SUPPORTED_PROVIDERS = ("openai", "anthropic")


def get_client(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int | None = None,
    retry_base_delay: float = 1.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LLMClient:
    """LLM client for ``provider`` (``openai`` / ``anthropic``). Raises ``ValueError`` otherwise."""
    retries = settings.judge_max_retries if max_retries is None else max_retries
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "base_url": base_url,
        "max_retries": retries,
        "headers": headers,
        "retry_base_delay": retry_base_delay,
        "transport": transport,
    }
    name = str(getattr(provider, "value", provider)).lower()
    if name == "openai":
        return OpenAICompatibleClient(**kwargs)
    if name == "anthropic":
        return AnthropicClient(**kwargs)
    raise ValueError(f"Fournisseur LLM non pris en charge : {provider}")


def client_from_credentials(
    provider: str, credentials: dict[str, str], *, base_url: str | None = None
) -> LLMClient:
    """Client built from decrypted credentials (``api_key``, ``base_url``, ``header:<Name>``)."""
    headers = {k.removeprefix("header:"): v for k, v in credentials.items() if k.startswith("header:")}
    return get_client(
        provider,
        api_key=credentials.get("api_key"),
        base_url=base_url or credentials.get("base_url"),
        headers=headers or None,
    )


__all__ = [
    "MODEL_PRICES",
    "SUPPORTED_PROVIDERS",
    "AnthropicClient",
    "LLMError",
    "LLMHTTPError",
    "LLMRefusalError",
    "LLMResponseError",
    "LLMTimeoutError",
    "ModelPrice",
    "OpenAICompatibleClient",
    "client_from_credentials",
    "estimate_cost",
    "get_client",
    "price_for",
]

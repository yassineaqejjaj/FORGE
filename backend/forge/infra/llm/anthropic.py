"""Anthropic Messages API client (``POST /v1/messages``, ``anthropic-version: 2023-06-01``), httpx only.

Structured JSON is requested through the system prompt (the answer is parsed tolerantly by the
judge parser). Model specifics handled here:

* sampling parameters are rejected by recent models (Opus 4.7+, Opus 5.x, Sonnet 5.x, Fable,
  Mythos): ``temperature`` is only sent to models that accept it;
* models that think by default (Opus 5.x, Sonnet 5.x, Fable, Mythos) spend output tokens on
  reasoning, so ``max_tokens`` gets a floor to leave room for the JSON answer;
* ``stop_reason="refusal"`` raises :class:`LLMRefusalError` (the judge is then reported as failed).
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from forge.domain.ports import LLMResponse
from forge.infra.llm.base import LLMRefusalError, LLMResponseError, post_json

DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
NO_SAMPLING_MODELS = re.compile(r"claude-(?:opus-(?:4-[7-9]|5)|sonnet-5|fable|mythos)", re.IGNORECASE)
THINKING_BY_DEFAULT = re.compile(r"claude-(?:opus-5|sonnet-5|fable|mythos)", re.IGNORECASE)
THINKING_MIN_MAX_TOKENS = 16_000


def json_instructions(schema: dict[str, Any]) -> str:
    return (
        "\n\nRéponds uniquement avec un objet JSON valide (sans texte autour ni bloc de code) conforme à ce "
        f"schéma JSON :\n{json.dumps(schema, ensure_ascii=False)}"
    )


class AnthropicClient:
    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None = None,
        max_retries: int = 2,
        headers: dict[str, str] | None = None,
        retry_base_delay: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key or ""
        base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.base_url = base.removesuffix("/v1")
        self.max_retries = max(0, max_retries)
        self._headers = dict(headers or {})
        self.retry_base_delay = retry_base_delay
        self._transport = transport

    def __repr__(self) -> str:  # never expose the key
        return f"AnthropicClient(base_url={self.base_url!r})"

    def _request_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            **self._headers,
            "x-api-key": self._api_key,
        }

    @staticmethod
    def accepts_temperature(model: str) -> bool:
        return not NO_SAMPLING_MODELS.search(model or "")

    @staticmethod
    def effective_max_tokens(model: str, max_tokens: int) -> int:
        if THINKING_BY_DEFAULT.search(model or ""):
            return max(max_tokens, THINKING_MIN_MAX_TOKENS)
        return max_tokens

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1500,
        json_schema: dict[str, Any] | None = None,
        timeout_seconds: float = 60.0,
    ) -> LLMResponse:
        system_text = system + (json_instructions(json_schema) if json_schema is not None else "")
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": self.effective_max_tokens(model, max_tokens),
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        }
        if system_text:
            payload["system"] = system_text
        if self.accepts_temperature(model):
            payload["temperature"] = temperature
        body, latency_ms = await post_json(
            f"{self.base_url}/v1/messages",
            payload=payload,
            headers=self._request_headers(),
            timeout_seconds=timeout_seconds,
            max_retries=self.max_retries,
            base_delay=self.retry_base_delay,
            provider="Anthropic",
            transport=self._transport,
        )
        return self._parse(body, model, latency_ms)

    @staticmethod
    def _parse(body: dict[str, Any], model: str, latency_ms: float) -> LLMResponse:
        if body.get("type") == "error":
            raise LLMResponseError(f"Anthropic : {body.get('error')}")
        stop_reason = body.get("stop_reason")
        if stop_reason == "refusal":
            details = body.get("stop_details") or {}
            category = details.get("category") if isinstance(details, dict) else None
            raise LLMRefusalError(
                f"Anthropic : le modèle a refusé de répondre (catégorie {category or 'inconnue'})"
            )
        content = body.get("content")
        if not isinstance(content, list):
            raise LLMResponseError("Anthropic : réponse sans « content »")
        text = "".join(
            str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
        tool_calls = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            model=str(body.get("model") or model),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            latency_ms=latency_ms,
            raw={"id": body.get("id"), "stop_reason": stop_reason},
            tool_calls=tool_calls,
            stop_reason=stop_reason,
        )

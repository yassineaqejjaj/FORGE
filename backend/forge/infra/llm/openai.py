"""OpenAI-compatible chat completions client (OpenAI, Azure-compatible gateways, vLLM, Ollama, Mistral…).

Structured output strategy when a JSON schema is requested: ``response_format`` ``json_schema`` →
on a 400 mentioning the response format, ``json_object`` → then plain text (the parser is
tolerant). The supported mode is remembered per (base URL, model) for the life of the process.

Reasoning models (``gpt-5*``, ``o1``/``o3``/``o4*``) take ``max_completion_tokens`` (which also
covers hidden reasoning tokens, hence a floor) and no ``temperature``.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

import httpx

from forge.domain.ports import LLMResponse
from forge.infra.llm.base import LLMHTTPError, LLMRefusalError, LLMResponseError, post_json

DEFAULT_BASE_URL = "https://api.openai.com/v1"
REASONING_MODEL = re.compile(r"^(?:.*/)?(?:gpt-5|o\d)", re.IGNORECASE)
REASONING_MIN_COMPLETION_TOKENS = 8000
JsonMode = Literal["json_schema", "json_object", "plain"]
_DOWNGRADE: dict[str, JsonMode] = {"json_schema": "json_object", "json_object": "plain"}
_FORMAT_HINTS = (
    "response_format",
    "json_schema",
    "json_object",
    "structured",
    "not supported",
    "unsupported",
)


class OpenAICompatibleClient:
    provider = "openai"
    _modes: ClassVar[dict[tuple[str, str], JsonMode]] = {}

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
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.max_retries = max(0, max_retries)
        self._headers = dict(headers or {})
        self.retry_base_delay = retry_base_delay
        self._transport = transport

    def __repr__(self) -> str:  # never expose the key
        return f"OpenAICompatibleClient(base_url={self.base_url!r})"

    def _request_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self._headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def is_reasoning_model(model: str) -> bool:
        return bool(REASONING_MODEL.match(model or ""))

    def _payload(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        mode: JsonMode,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages] if system else list(messages),
        }
        if self.is_reasoning_model(model):
            payload["max_completion_tokens"] = max(max_tokens, REASONING_MIN_COMPLETION_TOKENS)
        else:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = temperature
        if json_schema is not None and mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "forge_judge_verdict", "schema": json_schema, "strict": False},
            }
        elif json_schema is not None and mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
        return payload

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
        cache_key = (self.base_url, model)
        mode: JsonMode = self._modes.get(cache_key, "json_schema") if json_schema is not None else "plain"
        while True:
            payload = self._payload(
                system=system, messages=messages, model=model, temperature=temperature,
                max_tokens=max_tokens, json_schema=json_schema, mode=mode,
            )  # fmt: skip
            try:
                body, latency_ms = await post_json(
                    f"{self.base_url}/chat/completions",
                    payload=payload,
                    headers=self._request_headers(),
                    timeout_seconds=timeout_seconds,
                    max_retries=self.max_retries,
                    base_delay=self.retry_base_delay,
                    provider="OpenAI",
                    transport=self._transport,
                )
            except LLMHTTPError as exc:
                hint = str(exc).lower()
                if (
                    exc.status_code in (400, 422)
                    and mode in _DOWNGRADE
                    and any(h in hint for h in _FORMAT_HINTS)
                ):
                    mode = _DOWNGRADE[mode]
                    self._modes[cache_key] = mode
                    continue
                raise
            return self._parse(body, model, latency_ms)

    @staticmethod
    def _parse(body: dict[str, Any], model: str, latency_ms: float) -> LLMResponse:
        choices = body.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise LLMResponseError("OpenAI : réponse sans « choices »")
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # some gateways return content parts
            content = "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        if not content and message.get("refusal"):
            raise LLMRefusalError(
                f"OpenAI : le modèle a refusé de répondre ({str(message['refusal'])[:200]})"
            )
        usage = body.get("usage") or {}
        return LLMResponse(
            text=str(content or ""),
            model=str(body.get("model") or model),
            input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
            latency_ms=latency_ms,
            raw={"id": body.get("id"), "finish_reason": choice.get("finish_reason")},
            tool_calls=list(message.get("tool_calls") or []),
            stop_reason=choice.get("finish_reason"),
        )

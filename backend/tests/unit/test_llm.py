"""LLM clients (respx, no real network): payloads, structured output fallback, retries, pricing."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from forge.infra.llm import (
    AnthropicClient,
    LLMHTTPError,
    LLMRefusalError,
    LLMTimeoutError,
    OpenAICompatibleClient,
    client_from_credentials,
    estimate_cost,
    get_client,
    price_for,
)
from forge.infra.llm import base as llm_base
from forge.infra.llm.openai import OpenAICompatibleClient as _OpenAI

SCHEMA = {"type": "object", "properties": {"criteria": {"type": "array"}}}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(llm_base, "sleep", instant)
    _OpenAI._modes.clear()


def openai_body(text: str = '{"criteria": []}') -> dict:
    return {
        "id": "c1",
        "model": "gpt-5-mini-2025-08-07",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


def anthropic_body(text: str = '{"criteria": []}', stop: str = "end_turn") -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "model": "claude-haiku-4-5-20251001",
        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
        "stop_reason": stop,
        "usage": {"input_tokens": 200, "output_tokens": 40},
    }


@respx.mock
async def test_openai_payload_and_parse() -> None:
    route = respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=openai_body())
    )
    client = OpenAICompatibleClient(api_key="sk-secret", base_url="https://llm.test/v1", retry_base_delay=0)
    response = await client.complete(
        system="sys", messages=[{"role": "user", "content": "hi"}], model="gpt-4.1-mini", json_schema=SCHEMA
    )
    sent = json.loads(route.calls[0].request.content)
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-secret"
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["response_format"]["type"] == "json_schema" and sent["max_tokens"] == 1500
    assert sent["temperature"] == 0.0
    assert (
        response.text == '{"criteria": []}' and response.input_tokens == 120 and response.output_tokens == 30
    )
    assert "sk-secret" not in repr(client)


@respx.mock
async def test_openai_reasoning_models_use_completion_tokens() -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=openai_body())
    )
    await OpenAICompatibleClient(api_key="k").complete(
        system="s", messages=[], model="gpt-5-mini", max_tokens=1500
    )
    sent = json.loads(route.calls[0].request.content)
    assert "temperature" not in sent and sent["max_completion_tokens"] >= 1500 and "max_tokens" not in sent


@respx.mock
async def test_openai_structured_output_fallback_chain() -> None:
    route = respx.post("https://llm.test/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(400, json={"error": {"message": "response_format json_schema is not supported"}}),
            httpx.Response(400, json={"error": {"message": "response_format json_object unsupported"}}),
            httpx.Response(200, json=openai_body("texte")),
        ]
    )
    client = OpenAICompatibleClient(api_key="k", base_url="https://llm.test/v1")
    response = await client.complete(system="s", messages=[], model="llama3", json_schema=SCHEMA)
    formats = [json.loads(c.request.content).get("response_format") for c in route.calls]
    assert formats == [formats[0], {"type": "json_object"}, None] and formats[0]["type"] == "json_schema"
    assert response.text == "texte"
    # The supported mode is remembered.
    route.side_effect = None
    route.return_value = httpx.Response(200, json=openai_body())
    await client.complete(system="s", messages=[], model="llama3", json_schema=SCHEMA)
    assert "response_format" not in json.loads(route.calls[-1].request.content)


@respx.mock
async def test_retries_on_429_and_5xx_then_success() -> None:
    route = respx.post("https://llm.test/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "1"}, json={"error": {"message": "rate"}}),
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json=openai_body()),
        ]
    )
    client = OpenAICompatibleClient(
        api_key="k", base_url="https://llm.test/v1", max_retries=2, retry_base_delay=0
    )
    await client.complete(system="s", messages=[], model="gpt-4.1")
    assert route.call_count == 3


@respx.mock
async def test_retries_exhausted_and_non_retryable() -> None:
    respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": {"message": "boom"}})
    )
    client = OpenAICompatibleClient(
        api_key="k", base_url="https://llm.test/v1", max_retries=1, retry_base_delay=0
    )
    with pytest.raises(LLMHTTPError) as exc_info:
        await client.complete(system="s", messages=[], model="gpt-4.1")
    assert exc_info.value.status_code == 500 and "2 tentative" in str(exc_info.value)
    respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    with pytest.raises(LLMHTTPError) as unauthorized:
        await client.complete(system="s", messages=[], model="gpt-4.1")
    assert unauthorized.value.status_code == 401 and not unauthorized.value.retryable
    assert "k" not in str(unauthorized.value).split("—")[0].replace("OpenAI", "")


@respx.mock
async def test_timeouts_are_retried_then_raised() -> None:
    route = respx.post("https://llm.test/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))
    client = OpenAICompatibleClient(
        api_key="k", base_url="https://llm.test/v1", max_retries=2, retry_base_delay=0
    )
    with pytest.raises(LLMTimeoutError):
        await client.complete(system="s", messages=[], model="gpt-4.1")
    assert route.call_count == 3


@respx.mock
async def test_anthropic_payload_headers_and_parse() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=anthropic_body("{}"))
    )
    client = AnthropicClient(api_key="sk-ant-secret")
    response = await client.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        model="claude-haiku-4-5-20251001",
        json_schema=SCHEMA,
    )
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "sk-ant-secret"
    assert request.headers["anthropic-version"] == "2023-06-01"
    sent = json.loads(request.content)
    assert sent["system"].startswith("sys") and "schéma JSON" in sent["system"]
    assert sent["temperature"] == 0.0 and sent["max_tokens"] == 1500
    assert response.text == "{}" and response.input_tokens == 200 and response.output_tokens == 40


@respx.mock
async def test_anthropic_recent_models_skip_sampling_and_raise_token_floor() -> None:
    route = respx.post("https://proxy.test/v1/messages").mock(
        return_value=httpx.Response(200, json=anthropic_body())
    )
    await AnthropicClient(api_key="k", base_url="https://proxy.test/v1").complete(
        system="s", messages=[{"role": "user", "content": "x"}], model="claude-opus-5-5", max_tokens=1500
    )
    sent = json.loads(route.calls[0].request.content)
    assert "temperature" not in sent and sent["max_tokens"] >= 16_000


@respx.mock
async def test_anthropic_refusal_and_overloaded_retry() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=[httpx.Response(529, json={"type": "error", "error": {"message": "overloaded"}}),
                     httpx.Response(200, json=anthropic_body("", stop="refusal"))]
    )  # fmt: skip
    client = AnthropicClient(api_key="k", retry_base_delay=0)
    with pytest.raises(LLMRefusalError):
        await client.complete(
            system="s", messages=[{"role": "user", "content": "x"}], model="claude-sonnet-5-5"
        )
    assert route.call_count == 2


def test_get_client_and_credentials() -> None:
    assert isinstance(get_client("openai", api_key="k"), OpenAICompatibleClient)
    assert isinstance(get_client("anthropic", api_key="k"), AnthropicClient)
    with pytest.raises(ValueError):
        get_client("heuristic")
    client = client_from_credentials(
        "openai", {"api_key": "k", "base_url": "https://gw.test/v1", "header:X-Org": "acme"}
    )
    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "https://gw.test/v1" and client._request_headers()["X-Org"] == "acme"


def test_pricing() -> None:
    assert price_for("claude-opus-5-5").input_per_mtok == 4.0
    assert price_for("claude-sonnet-5-5").output_per_mtok == 10.0
    assert price_for("claude-haiku-4-5-20251001").input_per_mtok == 1.0
    assert price_for("gpt-5").output_per_mtok == 10.0
    assert price_for("gpt-5-mini-2025-08-07").input_per_mtok == 0.25
    assert price_for("gpt-4.1-nano").input_per_mtok == 0.10
    assert price_for("openai/gpt-4.1").input_per_mtok == 2.0
    assert price_for("mystery-model") is None and estimate_cost("mystery-model", 10, 10) is None
    assert estimate_cost("gpt-4.1", 1_000_000, 500_000) == pytest.approx(6.0)

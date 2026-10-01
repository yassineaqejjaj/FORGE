"""Anthropic Messages API adapter (``POST {base_url}/v1/messages`` with ``tools``) — docs §8.1.

Same FORGE-driven loop as the OpenAI adapter: ``tool_use`` blocks are answered with the scenario
tool mocks (``tool_result`` blocks), ``thinking`` blocks become ``reasoning`` events, each model
call is an ``llm_call`` event. Header ``anthropic-version: 2023-06-01``.
"""

from __future__ import annotations

from typing import Any

import httpx

from forge.adapters.base import conversation, credential_headers, extract_json, http_timeout
from forge.adapters.http import create_client, request_json
from forge.adapters.tool_loop import ToolNames, parse_arguments, run_tool, steps_exhausted
from forge.domain.enums import AdapterKind, BuiltinErrorType, TraceEventType
from forge.domain.traces.costs import estimate_cost
from forge.domain.types import AgentExecutionError, AgentRequest, AgentResult, TokenUsage

DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096
TARGET = "Le fournisseur Anthropic"


class AnthropicAdapter:
    kind = AdapterKind.anthropic

    async def invoke(self, request: AgentRequest, recorder: Any) -> AgentResult:
        agent = request.agent
        if agent.model is None:
            raise AgentExecutionError("Aucune configuration de modèle pour cet agent (adapter anthropic)")
        names = ToolNames(agent.tools)
        messages: list[dict[str, Any]] = conversation(request)
        usage = TokenUsage()
        cost_total: float | None = None
        max_steps = max(1, int(agent.budget.max_steps or 1))
        async with create_client(timeout=http_timeout(request), headers=self._headers(request)) as client:
            for step in range(1, max_steps + 1):
                data = await self._complete(client, request, messages, names, step, recorder)
                call_usage = _usage(data)
                usage.add(call_usage)
                call_cost = estimate_cost(agent.model, call_usage)
                if call_cost is not None:
                    cost_total = (cost_total or 0.0) + call_cost
                blocks = [b for b in data.get("content") or [] if isinstance(b, dict)]
                self._record_thinking(blocks, recorder)
                tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
                if not tool_uses:
                    return self._result(request, blocks, messages, usage, recorder, cost_total, step)
                text = _text(blocks)
                if text:
                    recorder.event(TraceEventType.reasoning, "Raisonnement intermédiaire", output=text)
                messages.append({"role": "assistant", "content": blocks})
                results: list[dict[str, Any]] = []
                for block in tool_uses:
                    outcome = await run_tool(
                        request,
                        recorder,
                        tool=names.original(str(block.get("name") or "")),
                        arguments=parse_arguments(block.get("input")),
                        call_id=str(block.get("id") or ""),
                        step=step,
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.get("id"),
                            "content": outcome.content,
                            "is_error": outcome.is_error,
                        }
                    )
                messages.append({"role": "user", "content": results})
        raise AgentExecutionError(steps_exhausted(max_steps), error_type=BuiltinErrorType.BUDGET_EXCEEDED)

    # --- Internals ----------------------------------------------------------------------------------

    def _headers(self, request: AgentRequest) -> dict[str, str]:
        credentials = request.agent.credentials
        headers = credential_headers(credentials)
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if credentials.get("api_key"):
            headers["x-api-key"] = credentials["api_key"]
        return headers

    def _url(self, request: AgentRequest) -> str:
        agent = request.agent
        base = (
            agent.credentials.get("base_url")
            or agent.adapter_config.get("base_url")
            or agent.endpoint
            or DEFAULT_BASE_URL
        )
        base = str(base).rstrip("/")
        if base.endswith("/v1/messages"):
            return base
        return f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"

    def _body(
        self, request: AgentRequest, messages: list[dict[str, Any]], names: ToolNames
    ) -> dict[str, Any]:
        agent = request.agent
        model = agent.model
        assert model is not None
        body: dict[str, Any] = {
            "model": model.model,
            "max_tokens": model.max_tokens
            or int(agent.adapter_config.get("max_tokens") or DEFAULT_MAX_TOKENS),
            "messages": messages,
        }
        if agent.system_prompt:
            body["system"] = agent.system_prompt
        if model.temperature is not None:
            body["temperature"] = model.temperature
        if model.top_p is not None:
            body["top_p"] = model.top_p
        body.update(model.params)
        if agent.tools:
            body["tools"] = [
                {"name": names.wire(t.name), "description": t.description, "input_schema": t.parameters}
                for t in agent.tools
            ]
        return body

    async def _complete(
        self,
        client: httpx.AsyncClient,
        request: AgentRequest,
        messages: list[dict[str, Any]],
        names: ToolNames,
        step: int,
        recorder: Any,
    ) -> dict[str, Any]:
        model = request.agent.model
        assert model is not None
        with recorder.span(
            TraceEventType.llm_call,
            f"Appel au modèle {model.model} (étape {step})",
            input={"messages": messages[-4:]},
            attributes={"model": model.model, "provider": model.provider, "step": step},
        ) as handle:
            data, _ = await request_json(
                client,
                "POST",
                self._url(request),
                target=TARGET,
                json_payload=self._body(request, messages, names),
            )
            if not isinstance(data, dict) or not isinstance(data.get("content"), list):
                raise AgentExecutionError(f"{TARGET} a renvoyé une réponse sans « content »")
            call_usage = _usage(data)
            call_cost = estimate_cost(model, call_usage)
            handle.set_output(_text(data["content"]) or {"content": data["content"]})
            handle.set_attributes(
                model=data.get("model") or model.model,
                input_tokens=call_usage.input_tokens,
                output_tokens=call_usage.output_tokens,
                cost=call_cost,
                finish_reason=data.get("stop_reason"),
            )
            recorder.add_usage(call_usage, cost=call_cost)
        return data

    def _record_thinking(self, blocks: list[dict[str, Any]], recorder: Any) -> None:
        for block in blocks:
            if block.get("type") == "thinking" and block.get("thinking"):
                recorder.event(TraceEventType.reasoning, "Réflexion du modèle", output=block["thinking"])

    def _result(
        self,
        request: AgentRequest,
        blocks: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        usage: TokenUsage,
        recorder: Any,
        cost: float | None,
        steps: int,
    ) -> AgentResult:
        text = _text(blocks)
        messages.append({"role": "assistant", "content": text})
        output_json = (
            extract_json(text) if request.agent.adapter_config.get("response_format") == "json" else None
        )
        return AgentResult(
            output_text=text,
            output_json=output_json,
            messages=messages,
            token_usage=usage,
            model_calls=steps,
            tool_calls=getattr(recorder, "tool_calls", 0),
            estimated_cost=cost,
            metadata={"provider": "anthropic", "steps": steps},
        )


def _text(blocks: list[Any]) -> str:
    return "\n".join(
        str(b.get("text") or "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
    ).strip()


def _usage(data: dict[str, Any]) -> TokenUsage:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return TokenUsage(
        input_tokens=int(usage.get("input_tokens") or 0), output_tokens=int(usage.get("output_tokens") or 0)
    )

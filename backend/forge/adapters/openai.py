"""OpenAI-compatible adapter (``POST {base_url}/chat/completions`` with ``tools``) — docs §8.1.

Works with OpenAI and every compatible server (vLLM, Ollama, Mistral, Gemini compatibility layer…).
FORGE drives the loop: system prompt, declared tools, scenario tool mocks, ``budget.max_steps``
model turns. Each model call → ``llm_call`` (model, tokens, cost), each tool call → ``tool_call`` +
``tool_result``. Secrets (``api_key``, ``base_url``) come from the agent credential.
"""

from __future__ import annotations

from typing import Any

import httpx

from forge.adapters.base import as_dict, conversation, credential_headers, extract_json, http_timeout
from forge.adapters.http import create_client, request_json
from forge.adapters.tool_loop import ToolNames, parse_arguments, run_tool, steps_exhausted
from forge.domain.enums import AdapterKind, BuiltinErrorType, TraceEventType
from forge.domain.traces.costs import estimate_cost
from forge.domain.types import AgentExecutionError, AgentRequest, AgentResult, TokenUsage

DEFAULT_BASE_URL = "https://api.openai.com/v1"
TARGET = "Le fournisseur OpenAI"
#: ``ModelSpec.params`` keys consumed by FORGE, never forwarded to the provider.
_INTERNAL_PARAMS = frozenset({"max_tokens_param"})


class OpenAIAdapter:
    kind = AdapterKind.openai

    async def invoke(self, request: AgentRequest, recorder: Any) -> AgentResult:
        agent = request.agent
        if agent.model is None:
            raise AgentExecutionError("Aucune configuration de modèle pour cet agent (adapter openai)")
        names = ToolNames(agent.tools)
        messages: list[dict[str, Any]] = []
        if agent.system_prompt:
            messages.append({"role": "system", "content": agent.system_prompt})
        messages += conversation(request)
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
                message = _first_message(data)
                tool_calls = [c for c in message.get("tool_calls") or [] if isinstance(c, dict)]
                if not tool_calls:
                    return self._result(request, message, messages, usage, recorder, cost_total, step)
                if message.get("content"):
                    recorder.event(
                        TraceEventType.reasoning, "Raisonnement intermédiaire", output=message["content"]
                    )
                messages.append(
                    {"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls}
                )
                for call in tool_calls:
                    function = call.get("function") or {}
                    outcome = await run_tool(
                        request,
                        recorder,
                        tool=names.original(str(function.get("name") or "")),
                        arguments=parse_arguments(function.get("arguments")),
                        call_id=str(call.get("id") or ""),
                        step=step,
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": call.get("id"), "content": outcome.content}
                    )
        raise AgentExecutionError(steps_exhausted(max_steps), error_type=BuiltinErrorType.BUDGET_EXCEEDED)

    # --- Internals ----------------------------------------------------------------------------------

    def _headers(self, request: AgentRequest) -> dict[str, str]:
        credentials = request.agent.credentials
        headers = credential_headers(credentials)
        if credentials.get("api_key"):
            headers["Authorization"] = f"Bearer {credentials['api_key']}"
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
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    def _body(
        self, request: AgentRequest, messages: list[dict[str, Any]], names: ToolNames
    ) -> dict[str, Any]:
        model = request.agent.model
        assert model is not None
        body: dict[str, Any] = {"model": model.model, "messages": messages}
        if model.temperature is not None:
            body["temperature"] = model.temperature
        if model.top_p is not None:
            body["top_p"] = model.top_p
        if model.seed is not None:
            body["seed"] = model.seed
        if model.max_tokens is not None:
            body[str(model.params.get("max_tokens_param") or "max_tokens")] = model.max_tokens
        body.update({k: v for k, v in model.params.items() if k not in _INTERNAL_PARAMS})
        if request.agent.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": names.wire(t.name),
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.agent.tools
            ]
        if request.agent.adapter_config.get("response_format") == "json":
            body["response_format"] = {"type": "json_object"}
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
            if not isinstance(data, dict) or not data.get("choices"):
                raise AgentExecutionError(f"{TARGET} a renvoyé une réponse sans « choices »")
            call_usage = _usage(data)
            call_cost = estimate_cost(model, call_usage)
            message = _first_message(data)
            handle.set_output(message.get("content") or {"tool_calls": message.get("tool_calls")})
            handle.set_attributes(
                model=data.get("model") or model.model,
                input_tokens=call_usage.input_tokens,
                output_tokens=call_usage.output_tokens,
                cost=call_cost,
                finish_reason=(data["choices"][0] or {}).get("finish_reason"),
            )
            recorder.add_usage(call_usage, cost=call_cost)
        return data

    def _result(
        self,
        request: AgentRequest,
        message: dict[str, Any],
        messages: list[dict[str, Any]],
        usage: TokenUsage,
        recorder: Any,
        cost: float | None,
        steps: int,
    ) -> AgentResult:
        text = str(message.get("content") or "")
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
            metadata={
                "provider": request.agent.model.provider if request.agent.model else None,
                "steps": steps,
            },
        )


def _first_message(data: dict[str, Any]) -> dict[str, Any]:
    choice = (data.get("choices") or [{}])[0] or {}
    message = choice.get("message") if isinstance(choice, dict) else None
    return message if isinstance(message, dict) else {}


def _usage(data: dict[str, Any]) -> TokenUsage:
    usage = as_dict(data.get("usage"))
    return TokenUsage(
        input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
    )

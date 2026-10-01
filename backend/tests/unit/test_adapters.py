"""Adapters: mock script, FORGE Agent Protocol (custom_api), mapped mode, NOVA, OpenAI/Anthropic loops."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from forge.adapters.base import build_protocol_body, result_from_protocol
from forge.adapters.registry import UnknownAdapterError, get_adapter
from forge.adapters.templating import json_path_get, render
from forge.adapters.tool_loop import ToolNames, find_mock
from forge.domain.enums import AdapterKind, Difficulty, EventStatus, ScenarioVisibility, TraceEventType
from forge.domain.traces.recorder import InMemoryTraceRecorder
from forge.domain.types import (
    AgentBudget,
    AgentExecutionError,
    AgentRequest,
    AgentSpec,
    ModelSpec,
    ScenarioSpec,
    ToolMock,
    ToolSpec,
)

SECRET = "sk-test-secret-value"


def make_request(
    kind: AdapterKind,
    *,
    adapter_config: dict[str, Any] | None = None,
    endpoint: str | None = None,
    model: ModelSpec | None = None,
    tools: list[ToolSpec] | None = None,
    mocks: list[ToolMock] | None = None,
    credentials: dict[str, str] | None = None,
    budget: AgentBudget | None = None,
    repetition: int = 0,
    attempt: int = 1,
) -> AgentRequest:
    scenario = ScenarioSpec(
        scenario_id="s", scenario_version_id="sv-1", slug="prd", name="PRD", version=1, category="product_management",
        difficulty=Difficulty.medium, visibility=ScenarioVisibility.public,
        input={"prompt": "Rédige un PRD pour l'export CSV."}, context={"documents": [{"id": "d1", "title": "Note", "content": "Besoin d'export."}]},
        constraints=["Maximum 300 mots"], expected_output="SECRET-EXPECTED", tool_mocks=mocks or [],
    )  # fmt: skip
    agent = AgentSpec(
        agent_id="a", agent_version_id="av", agent_name="Agent", agent_slug="agent", version="1.0",
        adapter_kind=kind, endpoint=endpoint, model=model, system_prompt="Tu es un PM.", tools=tools or [],
        adapter_config=adapter_config or {}, budget=budget or AgentBudget(), credentials=credentials or {},
    )  # fmt: skip
    return AgentRequest(
        run_id="run-1",
        scenario=scenario,
        agent=agent,
        context=scenario.context,
        trace_headers={"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01", "X-Forge-Run-Id": "run-1",
                       "X-Forge-Scenario-Version": "sv-1", "X-Forge-Repetition": str(repetition),
                       "X-Forge-Attempt": str(attempt)},
        otel_trace_id="a" * 32,
    )  # fmt: skip


# --- Mock ---------------------------------------------------------------------------------------------


async def test_mock_script_events_usage_and_repetition_override() -> None:
    script = {
        "output": "Réponse à « {{input.prompt}} »",
        "events": [
            {
                "type": "llm_call",
                "name": "Génération",
                "attributes": {"input_tokens": 100, "output_tokens": 20},
            },
            {"type": "tool_call", "name": "jira.search", "input": {"query": "x"}},
        ],
        "by_repetition": {"1": {"output": "Variante"}},
    }
    recorder = InMemoryTraceRecorder()
    result = await get_adapter("mock").invoke(
        make_request(AdapterKind.mock, adapter_config={"script": script}), recorder
    )
    assert result.output_text == "Réponse à « Rédige un PRD pour l'export CSV. »"
    assert result.token_usage.total_tokens == 120 and result.model_calls == 1 and result.tool_calls == 1
    assert [e.type for e in recorder.events] == [TraceEventType.llm_call, TraceEventType.tool_call]
    second = await get_adapter("mock").invoke(
        make_request(AdapterKind.mock, adapter_config={"script": script}, repetition=1),
        InMemoryTraceRecorder(),
    )
    assert second.output_text == "Variante"


async def test_mock_errors_and_transient_failures() -> None:
    script = {"error": {"message": "Agent en panne", "error_type": "EXECUTION_ERROR", "retryable": False},
              "events": [{"type": "reasoning", "name": "Début"}]}  # fmt: skip
    recorder = InMemoryTraceRecorder()
    with pytest.raises(AgentExecutionError, match="Agent en panne") as exc:
        await get_adapter("mock").invoke(
            make_request(AdapterKind.mock, adapter_config={"script": script}), recorder
        )
    assert not exc.value.retryable and len(recorder.events) == 1
    flaky = {"script": {"output": "ok", "fail_on_attempts": [1]}}
    with pytest.raises(AgentExecutionError) as exc:
        await get_adapter("mock").invoke(
            make_request(AdapterKind.mock, adapter_config=flaky), InMemoryTraceRecorder()
        )
    assert exc.value.retryable
    result = await get_adapter("mock").invoke(
        make_request(AdapterKind.mock, adapter_config=flaky, attempt=2), InMemoryTraceRecorder()
    )
    assert result.output_text == "ok"


def test_registry_unknown_kind() -> None:
    with pytest.raises(UnknownAdapterError):
        get_adapter("nope")


# --- Templating & helpers -----------------------------------------------------------------------------


def test_templating_and_json_paths() -> None:
    variables = {
        "input": {"prompt": "Bonjour"},
        "context": {"documents": [1]},
        "credentials": {"api_key": "k"},
    }
    rendered = render({"q": "{{input.prompt}}", "ctx": "{{ context }}", "h": "Bearer {{credentials.api_key}}",
                       "missing": "{{nope.x}}"}, variables)  # fmt: skip
    assert rendered == {"q": "Bonjour", "ctx": {"documents": [1]}, "h": "Bearer k", "missing": None}
    data = {"choices": [{"message": {"content": "hi"}}]}
    assert json_path_get(data, "choices[0].message.content") == "hi"
    assert json_path_get(data, "$.choices.0.message.content") == "hi"
    assert json_path_get(data, "choices[3].x", "d") == "d"


def test_protocol_body_never_leaks_expected_output_or_mocks() -> None:
    request = make_request(AdapterKind.custom_api, mocks=[ToolMock(tool="t", response="r")],
                           adapter_config={"parameters": {"white_box": True}})  # fmt: skip
    body = build_protocol_body(request)
    serialized = json.dumps(body)
    assert "SECRET-EXPECTED" not in serialized and "tool_mocks" not in serialized
    assert body["protocol"] == "forge-agent-protocol/v1" and body["agent"]["parameters"] == {
        "white_box": True
    }
    assert body["input"]["prompt"].startswith("Rédige") and body["constraints"] == ["Maximum 300 mots"]


def test_tool_names_and_mock_matching() -> None:
    names = ToolNames([ToolSpec(name="jira.search"), ToolSpec(name="jira_search")])
    assert names.wire("jira.search") == "jira_search" and names.wire("jira_search") == "jira_search_2"
    assert names.original("jira_search_2") == "jira_search"
    mocks = [
        ToolMock(tool="jira.search", match={"query": "EXPORT"}, response=[1]),
        ToolMock(tool="jira.search", response=[2]),
    ]
    assert find_mock(mocks, "jira.search", {"query": "export", "limit": 5})[0] == 0
    assert find_mock(mocks, "jira.search", {"query": "autre"})[0] == 1
    assert find_mock(mocks, "crm", {}) is None


def test_protocol_error_after_events_keeps_partial_trace() -> None:
    from datetime import UTC, datetime

    recorder = InMemoryTraceRecorder()
    data = {"events": [{"type": "reasoning", "name": "x"}], "error": {"message": "quota", "retryable": True}}
    with pytest.raises(AgentExecutionError) as exc:
        result_from_protocol(data, recorder=recorder, started_at=datetime.now(UTC))
    assert exc.value.retryable and len(recorder.events) == 1
    with pytest.raises(AgentExecutionError, match="output"):
        result_from_protocol({"events": []}, recorder=recorder, started_at=datetime.now(UTC))


# --- custom_api ---------------------------------------------------------------------------------------


@respx.mock
async def test_custom_api_forge_mode_propagates_headers_and_parses_response() -> None:
    route = respx.post("https://agent.example/invoke").mock(
        return_value=httpx.Response(200, json={
            "output": "# PRD", "output_json": {"ok": True},
            "events": [{"id": "1", "type": "llm_call", "name": "LLM", "offset_ms": 5, "duration_ms": 50,
                        "attributes": {"model": "m", "input_tokens": 10, "output_tokens": 4}},
                       {"id": "2", "type": "tool_call", "name": "jira.search", "parent_id": "1"}],
            "usage": {"input_tokens": 100, "output_tokens": 40}, "cost": 0.02,
        })
    )  # fmt: skip
    recorder = InMemoryTraceRecorder()
    request = make_request(
        AdapterKind.custom_api, endpoint="https://agent.example/invoke", credentials={"api_key": SECRET}
    )
    result = await get_adapter("custom_api").invoke(request, recorder)
    sent = route.calls.last.request
    assert sent.headers["traceparent"].startswith("00-" + "a" * 32)
    assert sent.headers["x-forge-run-id"] == "run-1" and sent.headers["authorization"] == f"Bearer {SECRET}"
    assert json.loads(sent.content)["run_id"] == "run-1"
    assert result.output_text == "# PRD" and result.output_json == {"ok": True}
    assert result.token_usage.total_tokens == 140 and result.estimated_cost == 0.02 and result.tool_calls == 1
    assert recorder.events[1].parent_key == recorder.events[0].key


@pytest.mark.parametrize(("status", "retryable"), [(400, False), (404, False), (429, True), (503, True)])
@respx.mock
async def test_custom_api_http_error_semantics(status: int, retryable: bool) -> None:
    respx.post("https://agent.example/invoke").mock(return_value=httpx.Response(status, json={"error": "x"}))
    request = make_request(
        AdapterKind.custom_api, endpoint="https://agent.example/invoke", credentials={"api_key": SECRET}
    )
    with pytest.raises(AgentExecutionError) as exc:
        await get_adapter("custom_api").invoke(request, InMemoryTraceRecorder())
    assert exc.value.retryable is retryable and SECRET not in str(exc.value)


@respx.mock
async def test_custom_api_connect_error_is_retryable() -> None:
    respx.post("https://agent.example/invoke").mock(side_effect=httpx.ConnectError("refused"))
    request = make_request(AdapterKind.custom_api, endpoint="https://agent.example/invoke")
    with pytest.raises(AgentExecutionError) as exc:
        await get_adapter("custom_api").invoke(request, InMemoryTraceRecorder())
    assert exc.value.retryable


@respx.mock
async def test_custom_api_mapped_mode() -> None:
    route = respx.post("https://api.example/v2/chat").mock(
        return_value=httpx.Response(
            200, json={"data": {"answer": "Réponse"}, "meta": {"tokens": {"in": 7, "out": 3}}}
        )
    )
    config = {
        "mode": "mapped", "url": "https://api.example/v2/chat",
        "headers": {"X-Api-Key": "{{credentials.api_key}}"},
        "body_template": {"question": "{{input.prompt}}", "system": "{{system_prompt}}", "docs": "{{context.documents}}"},
        "output_path": "data.answer", "usage_paths": {"input_tokens": "meta.tokens.in", "output_tokens": "meta.tokens.out"},
    }  # fmt: skip
    result = await get_adapter("custom_api").invoke(
        make_request(AdapterKind.custom_api, adapter_config=config, credentials={"api_key": SECRET}),
        InMemoryTraceRecorder(),
    )
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == SECRET
    assert json.loads(sent.content) == {"question": "Rédige un PRD pour l'export CSV.", "system": "Tu es un PM.",
                                        "docs": [{"id": "d1", "title": "Note", "content": "Besoin d'export."}]}  # fmt: skip
    assert result.output_text == "Réponse" and result.token_usage.total_tokens == 10


# --- NOVA ---------------------------------------------------------------------------------------------


@respx.mock
async def test_nova_handoffs_become_agent_handoff_events() -> None:
    route = respx.post("https://nova.example/v1/agents/pm-crew/runs").mock(
        return_value=httpx.Response(200, json={
            "output": "Plan livré",
            "handoffs": [{"from": "orchestrator", "to": "writer", "reason": "rédaction", "offset_ms": 10, "duration_ms": 80}],
            "agents": [{"name": "writer", "events": [{"type": "llm_call", "name": "Rédaction", "offset_ms": 20,
                        "attributes": {"input_tokens": 50, "output_tokens": 10}}]},
                       {"name": "reviewer", "events": [{"type": "reasoning", "name": "Relecture", "offset_ms": 95}]}],
        })
    )  # fmt: skip
    recorder = InMemoryTraceRecorder()
    request = make_request(AdapterKind.nova, adapter_config={"nova_agent_id": "pm-crew"},
                           credentials={"base_url": "https://nova.example", "api_key": SECRET})  # fmt: skip
    result = await get_adapter("nova").invoke(request, recorder)
    assert json.loads(route.calls.last.request.content)["nova_agent_id"] == "pm-crew"
    handoffs = [e for e in recorder.events if e.type == TraceEventType.agent_handoff]
    assert [h.attributes["agent"] for h in handoffs] == ["writer", "reviewer"]
    llm = next(e for e in recorder.events if e.type == TraceEventType.llm_call)
    assert llm.parent_key == handoffs[0].key and llm.attributes["agent"] == "writer"
    assert result.metadata["handoffs"] == 2 and result.token_usage.total_tokens == 60


async def test_nova_requires_agent_id() -> None:
    with pytest.raises(AgentExecutionError, match="nova_agent_id"):
        await get_adapter("nova").invoke(make_request(AdapterKind.nova), InMemoryTraceRecorder())


# --- OpenAI / Anthropic loops -------------------------------------------------------------------------

MODEL = ModelSpec(provider="openai", model="gpt-test", input_cost_per_mtok=1.0, output_cost_per_mtok=2.0)
TOOLS = [ToolSpec(name="jira.search", description="Recherche Jira")]
MOCKS = [ToolMock(tool="jira.search", match={"query": "export"}, response={"issues": ["PROD-1"]})]


@respx.mock
async def test_openai_tool_loop_with_mocks() -> None:
    replies = iter([
        {"model": "gpt-test", "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "jira_search", "arguments": '{"query": "Export"}'}},
            {"id": "c2", "type": "function", "function": {"name": "jira_search", "arguments": '{"query": "autre"}'}}]}}],
         "usage": {"prompt_tokens": 100, "completion_tokens": 10}},
        {"model": "gpt-test", "choices": [{"finish_reason": "stop", "message": {"content": "PRD final"}}],
         "usage": {"prompt_tokens": 150, "completion_tokens": 50}},
    ])  # fmt: skip
    route = respx.post("https://llm.example/v1/chat/completions").mock(
        side_effect=lambda r: httpx.Response(200, json=next(replies))
    )
    recorder = InMemoryTraceRecorder(model=MODEL)
    request = make_request(AdapterKind.openai, model=MODEL, tools=TOOLS, mocks=MOCKS,
                           credentials={"api_key": SECRET, "base_url": "https://llm.example/v1"})  # fmt: skip
    result = await get_adapter("openai").invoke(request, recorder)
    first = json.loads(route.calls[0].request.content)
    assert first["tools"][0]["function"]["name"] == "jira_search" and first["messages"][0]["role"] == "system"
    assert route.calls[0].request.headers["authorization"] == f"Bearer {SECRET}"
    second = json.loads(route.calls[1].request.content)
    tool_messages = [m for m in second["messages"] if m["role"] == "tool"]
    assert json.loads(tool_messages[0]["content"]) == {"issues": ["PROD-1"]}
    assert "indisponible" in tool_messages[1]["content"]
    assert result.output_text == "PRD final" and result.model_calls == 2 and result.tool_calls == 2
    assert result.token_usage.total_tokens == 310 and result.estimated_cost == pytest.approx(0.00037)
    types = [e.type for e in recorder.events]
    assert types.count(TraceEventType.llm_call) == 2 and types.count(TraceEventType.tool_result) == 2
    failed = [
        e for e in recorder.events if e.type == TraceEventType.tool_result and e.status == EventStatus.error
    ]
    assert len(failed) == 1 and failed[0].attributes["error_type"] == "TOOL_FAILURE"


@respx.mock
async def test_openai_max_steps_budget() -> None:
    reply = {
        "choices": [
            {"message": {"tool_calls": [{"id": "c", "function": {"name": "jira_search", "arguments": "{}"}}]}}
        ]
    }
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=reply)
    )
    request = make_request(AdapterKind.openai, model=MODEL, tools=TOOLS, budget=AgentBudget(max_steps=2))
    with pytest.raises(AgentExecutionError) as exc:
        await get_adapter("openai").invoke(request, InMemoryTraceRecorder())
    assert exc.value.error_type == "BUDGET_EXCEEDED"


@respx.mock
async def test_anthropic_tool_loop() -> None:
    replies = iter([
        {"content": [{"type": "thinking", "thinking": "Je cherche"}, {"type": "tool_use", "id": "t1", "name": "jira_search",
                      "input": {"query": "export"}}], "stop_reason": "tool_use", "usage": {"input_tokens": 80, "output_tokens": 20}},
        {"content": [{"type": "text", "text": "Synthèse"}], "stop_reason": "end_turn", "usage": {"input_tokens": 120, "output_tokens": 30}},
    ])  # fmt: skip
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=lambda r: httpx.Response(200, json=next(replies))
    )
    model = ModelSpec(provider="anthropic", model="claude-test")
    recorder = InMemoryTraceRecorder()
    request = make_request(
        AdapterKind.anthropic, model=model, tools=TOOLS, mocks=MOCKS, credentials={"api_key": SECRET}
    )
    result = await get_adapter("anthropic").invoke(request, recorder)
    headers = route.calls[0].request.headers
    assert headers["x-api-key"] == SECRET and headers["anthropic-version"] == "2023-06-01"
    body = json.loads(route.calls[0].request.content)
    assert body["system"] == "Tu es un PM." and body["tools"][0]["input_schema"]["type"] == "object"
    follow_up = json.loads(route.calls[1].request.content)["messages"][-1]["content"][0]
    assert follow_up["type"] == "tool_result" and follow_up["is_error"] is False
    assert result.output_text == "Synthèse" and result.token_usage.total_tokens == 250
    assert any(e.type == TraceEventType.reasoning for e in recorder.events)

"""Helpers shared by the adapters: FORGE Agent Protocol (FAP v1) request/response, run headers.

The FAP is specified in ``docs/AGENT_PROTOCOL.md``. Agents only ever receive the agent view of the
scenario (input, prepared context, constraints) — never expected outputs, criteria, rules or mocks.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from forge.config import settings
from forge.domain.enums import BuiltinErrorType, TraceEventSource, TraceEventType
from forge.domain.traces.protocol import FAP_VERSION, parse_protocol_events, parse_usage, usage_from_events
from forge.domain.traces.recorder import import_events
from forge.domain.types import (
    AgentExecutionError,
    AgentRequest,
    AgentResult,
    TokenUsage,
    TraceEventData,
    to_dict,
)

HEADER_RUN_ID = "X-Forge-Run-Id"
HEADER_SCENARIO_VERSION = "X-Forge-Scenario-Version"
HEADER_REPETITION = "X-Forge-Repetition"
HEADER_ATTEMPT = "X-Forge-Attempt"
HEADER_TRACEPARENT = "traceparent"
#: Extra HTTP time on top of the budget timeout: the runner's own timeout must fire first.
HTTP_TIMEOUT_MARGIN_SECONDS = 5.0


def as_dict(value: Any) -> dict[str, Any]:
    """``value`` when it is a JSON object, else an empty dict (tolerant payload parsing)."""
    return value if isinstance(value, dict) else {}


def _header(request: AgentRequest, name: str) -> str | None:
    wanted = name.lower()
    for key, value in request.trace_headers.items():
        if key.lower() == wanted:
            return value
    return None


def repetition_of(request: AgentRequest) -> int:
    try:
        return int(_header(request, HEADER_REPETITION) or 0)
    except ValueError:
        return 0


def attempt_of(request: AgentRequest) -> int:
    try:
        return max(1, int(_header(request, HEADER_ATTEMPT) or 1))
    except ValueError:
        return 1


def http_timeout(request: AgentRequest) -> float:
    configured = request.agent.adapter_config.get("http_timeout_seconds")
    budget = request.agent.budget.timeout_seconds or settings.runner_default_timeout_seconds
    base = float(configured) if configured else float(budget)
    return base + HTTP_TIMEOUT_MARGIN_SECONDS


def credential_headers(credentials: dict[str, str]) -> dict[str, str]:
    """Extra headers stored in the credential (``header:<Name>`` keys)."""
    return {k.removeprefix("header:"): v for k, v in credentials.items() if k.startswith("header:")}


def propagation_headers(request: AgentRequest) -> dict[str, str]:
    """W3C ``traceparent`` + FORGE correlation headers (docs §8 step 5)."""
    return {k: str(v) for k, v in request.trace_headers.items() if v is not None}


# --- Request ----------------------------------------------------------------------------------------


def build_protocol_body(request: AgentRequest) -> dict[str, Any]:
    """FAP v1 request body (``POST <endpoint>``)."""
    agent = request.agent
    view = request.scenario.agent_view()
    return {
        "protocol": FAP_VERSION,
        "run_id": request.run_id,
        "trace_id": request.otel_trace_id,
        "repetition": repetition_of(request),
        "attempt": attempt_of(request),
        "scenario_version_id": view["scenario_version_id"],
        "input": view["input"],
        "context": request.context,
        "constraints": view["constraints"],
        "agent": {
            "name": agent.agent_name,
            "slug": agent.agent_slug,
            "version": agent.version,
            "system_prompt": agent.system_prompt,
            "model": to_dict(agent.model) if agent.model else None,
            "tools": [to_dict(t) for t in agent.tools],
            "parameters": dict(agent.adapter_config.get("parameters") or {}),
            "memory": dict(agent.memory_config),
            "orchestration": dict(agent.orchestration_config),
        },
        "budget": to_dict(agent.budget),
    }


# --- Response ---------------------------------------------------------------------------------------


def protocol_error(data: Any) -> AgentExecutionError | None:
    """``{"error": {"message", "type", "retryable"}}`` (or a plain string) → exception, else ``None``."""
    error = data.get("error") if isinstance(data, dict) else None
    if not error:
        return None
    if isinstance(error, str):
        return AgentExecutionError(f"L'agent a signalé une erreur : {error}")
    if not isinstance(error, dict):
        return AgentExecutionError("L'agent a signalé une erreur")
    message = str(error.get("message") or "erreur non détaillée")
    return AgentExecutionError(
        f"L'agent a signalé une erreur : {message}",
        error_type=str(error.get("type") or error.get("error_type") or BuiltinErrorType.EXECUTION_ERROR),
        retryable=bool(error.get("retryable", False)),
    )


def split_output(data: dict[str, Any]) -> tuple[str, Any]:
    """``(output_text, output_json)`` from ``output`` / ``output_text`` / ``output_json``."""
    output = data.get("output")
    output_json = data.get("output_json")
    text = data.get("output_text")
    if isinstance(output, dict) and ("text" in output or "json" in output):
        text = text if text is not None else output.get("text")
        output_json = output_json if output_json is not None else output.get("json")
    elif isinstance(output, str):
        text = text if text is not None else output
    elif output is not None and output_json is None:
        output_json = output
    if text is None and output_json is not None:
        text = json.dumps(output_json, ensure_ascii=False, indent=2)
    if text is None:
        raise AgentExecutionError("Réponse de l'agent invalide : champ « output » manquant")
    return str(text), output_json


def result_from_protocol(
    data: Any,
    *,
    recorder: Any,
    started_at: datetime,
    key_prefix: str = "agent:",
    extra_events: list[TraceEventData] | None = None,
) -> AgentResult:
    """Parse a FAP response: import its events into the recorder, report usage, build the result.

    An ``error`` in the body raises ``AgentExecutionError`` *after* the events were imported, so the
    partial trace is kept.
    """
    if not isinstance(data, dict):
        raise AgentExecutionError("Réponse de l'agent invalide : objet JSON attendu")
    events = parse_protocol_events(
        data.get("events") if isinstance(data.get("events"), list) else [],
        base_time=started_at,
        source=TraceEventSource.adapter,
        key_prefix=key_prefix,
    )
    events += extra_events or []
    import_events(recorder, events)
    error = protocol_error(data)
    if error is not None:
        raise error
    text, output_json = split_output(data)
    return _result(data, events, recorder, text, output_json)


def _result(
    data: dict[str, Any], events: list[TraceEventData], recorder: Any, text: str, output_json: Any
) -> AgentResult:
    usage_data = as_dict(data.get("usage"))
    usage = parse_usage(usage_data)
    event_usage, event_calls, event_cost = usage_from_events(events)
    if usage.total_tokens == 0:
        usage = event_usage
    cost = _float(data.get("cost", usage_data.get("cost")))
    if cost is None:
        cost = event_cost
    recorder.add_usage(TokenUsage(usage.input_tokens, usage.output_tokens), cost=cost, model_call=False)
    tool_calls = sum(1 for e in events if e.type == TraceEventType.tool_call)
    for _ in range(tool_calls):
        recorder.count_tool_call()
    metadata = dict(data["metadata"]) if isinstance(data.get("metadata"), dict) else {}
    if data.get("model"):
        metadata.setdefault("model", data["model"])
    return AgentResult(
        output_text=text,
        output_json=output_json,
        messages=[m for m in data.get("messages") or [] if isinstance(m, dict)],
        token_usage=usage,
        model_calls=int(usage_data.get("model_calls") or event_calls or (1 if usage.total_tokens else 0)),
        tool_calls=int(usage_data.get("tool_calls") or tool_calls),
        estimated_cost=cost,
        metadata=metadata,
        raw={k: v for k, v in data.items() if k not in ("events", "output", "output_text", "messages")},
    )


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --- Prompt rendering (FORGE-driven LLM loops) -------------------------------------------------------


def render_documents(context: dict[str, Any]) -> str:
    lines: list[str] = []
    for doc in context.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        header = f"[{doc.get('id', '?')}] {doc.get('title', '')}".strip()
        lines.append(f"### {header}\n{doc.get('content', '')}".rstrip())
    facts = [f for f in context.get("facts") or [] if f]
    if facts:
        lines.append("### Faits\n" + "\n".join(f"- {fact}" for fact in facts))
    extra = context.get("text") or context.get("orbit_context")
    if isinstance(extra, str) and extra.strip():
        lines.append(extra.strip())
    return "\n\n".join(lines)


def render_user_message(request: AgentRequest) -> str:
    """Scenario prompt + prepared context + constraints as one user message (French headings)."""
    prompt = str(request.scenario.input.get("prompt") or "").strip()
    parts = [prompt] if prompt else []
    documents = render_documents(request.context or {})
    if documents:
        parts.append(f"## Contexte\n\n{documents}")
    if request.scenario.constraints:
        parts.append("## Contraintes\n" + "\n".join(f"- {c}" for c in request.scenario.constraints))
    return "\n\n".join(parts) or "(aucune consigne)"


def conversation(request: AgentRequest) -> list[dict[str, Any]]:
    """Initial chat messages: scenario ``messages`` (multi-turn) completed by the rendered prompt."""
    history = [
        {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
        for m in request.scenario.input.get("messages") or []
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ]
    if not history or request.scenario.input.get("prompt") or request.context.get("documents"):
        history.append({"role": "user", "content": render_user_message(request)})
    return history


def extract_json(text: str) -> Any:
    """JSON object from a model answer (raw JSON or a fenced ```json block); ``None`` otherwise."""
    candidate = text.strip()
    if "```" in candidate:
        start = candidate.find("```")
        body = candidate[start + 3 :]
        body = body.removeprefix("json").removeprefix("JSON")
        end = body.find("```")
        candidate = body[:end] if end >= 0 else body
    try:
        return json.loads(candidate.strip())
    except ValueError:
        return None

"""Deterministic scripted agent (tests, demos) — docs §8.1.

``adapter_config.script``::

    {
      "output": "Réponse pour {{input.prompt}}",     # placeholders: input, context, constraints, repetition…
      "output_json": {...},                           # optional
      "events": [{"type": "tool_call", "name": "jira.search", "input": {...}, "duration_ms": 120}, ...],
      "usage": {"input_tokens": 1200, "output_tokens": 300}, "cost": 0.004, "model": "mock-model",
      "latency_ms": 250,                              # simulated latency (spread over the events)
      "error": {"message": "…", "retryable": false, "error_type": "EXECUTION_ERROR"},
      "fail_on_attempts": [1],                        # transient (retryable) failure on these attempts
      "by_repetition": {"1": {"output": "…"}}         # shallow override per repetition
    }

Without ``usage``, tokens are summed from the ``llm_call`` events' ``input_tokens``/``output_tokens``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from forge.adapters.base import attempt_of, repetition_of
from forge.adapters.templating import render
from forge.domain.enums import AdapterKind, EventStatus, TraceEventSource, TraceEventType
from forge.domain.traces.protocol import parse_event_type, parse_usage
from forge.domain.traces.recorder import import_events
from forge.domain.types import AgentExecutionError, AgentRequest, AgentResult, TokenUsage, TraceEventData

DEFAULT_OUTPUT = "Réponse simulée : {{input.prompt}}"


def resolve_script(config: dict[str, Any], repetition: int) -> dict[str, Any]:
    script = dict(config.get("script") or {})
    overrides = script.pop("by_repetition", None) or {}
    override = overrides.get(str(repetition)) if isinstance(overrides, dict) else None
    if isinstance(override, dict):
        script.update(override)
    return script


class MockAdapter:
    kind = AdapterKind.mock

    async def invoke(self, request: AgentRequest, recorder: Any) -> AgentResult:
        repetition = repetition_of(request)
        attempt = attempt_of(request)
        script = resolve_script(request.agent.adapter_config, repetition)
        if attempt in {int(a) for a in script.get("fail_on_attempts") or []}:
            raise AgentExecutionError(f"Échec transitoire simulé (tentative {attempt})", retryable=True)
        variables = {
            "input": request.scenario.input,
            "context": request.context,
            "constraints": request.scenario.constraints,
            "repetition": repetition,
            "attempt": attempt,
        }
        events = [e for e in script.get("events") or [] if isinstance(e, dict)]
        pause = max(0.0, float(script.get("latency_ms") or 0)) / 1000 / (len(events) + 1)
        for item in events:
            await asyncio.sleep(pause)
            self._record(item, recorder, variables)
        await asyncio.sleep(pause)
        usage, cost, model_calls = self._usage(script, events)
        error = script.get("error")
        if error:
            raise _scripted_error(error)
        recorder.add_usage(usage, cost=cost, model_call=False)
        output = render(script.get("output", DEFAULT_OUTPUT), variables)
        return AgentResult(
            output_text=output if isinstance(output, str) else str(output),
            output_json=render(script.get("output_json"), variables),
            messages=[{"role": "assistant", "content": output}],
            token_usage=usage,
            model_calls=model_calls,
            tool_calls=sum(
                1 for e in events if parse_event_type(e.get("type"))[0] == TraceEventType.tool_call
            ),
            estimated_cost=cost,
            metadata={"model": script.get("model", "mock"), "repetition": repetition, "attempt": attempt},
        )

    def _record(self, item: dict[str, Any], recorder: Any, variables: dict[str, Any]) -> None:
        event_type, original = parse_event_type(item.get("type"))
        attributes = dict(item.get("attributes") or {})
        if original:
            attributes.setdefault("original_type", original)
        if event_type in (TraceEventType.tool_call, TraceEventType.tool_result):
            attributes.setdefault("tool", item.get("name"))
        if event_type == TraceEventType.tool_call:
            recorder.count_tool_call()
        started = datetime.now(UTC)
        duration = float(item["duration_ms"]) if item.get("duration_ms") is not None else 0.0
        event = TraceEventData(
            type=event_type,
            name=str(item.get("name") or event_type.value),
            started_at=started,
            ended_at=started + timedelta(milliseconds=max(0.0, duration)),
            key="",
            status=EventStatus.error if item.get("status") == "error" else EventStatus.ok,
            input=render(item.get("input"), variables),
            output=render(item.get("output"), variables),
            attributes=attributes,
            source=TraceEventSource.adapter,
        )
        # Simulated events start now and last ``duration_ms`` (never back-dated before the call).
        import_events(recorder, [event])

    def _usage(
        self, script: dict[str, Any], events: list[dict[str, Any]]
    ) -> tuple[TokenUsage, float | None, int]:
        llm_events = [e for e in events if parse_event_type(e.get("type"))[0] == TraceEventType.llm_call]
        usage = parse_usage(script.get("usage"))
        if usage.total_tokens == 0:
            for event in llm_events:
                usage.add(parse_usage(event.get("attributes") or {}))
        cost = script.get("cost")
        if cost is None:
            costs = [(e.get("attributes") or {}).get("cost") for e in llm_events]
            cost = (
                sum(float(c) for c in costs if c is not None) if any(c is not None for c in costs) else None
            )
        return (
            usage,
            (float(cost) if cost is not None else None),
            len(llm_events) or (1 if usage.total_tokens else 0),
        )


def _scripted_error(error: Any) -> AgentExecutionError:
    if not isinstance(error, dict):
        return AgentExecutionError(str(error))
    return AgentExecutionError(
        str(error.get("message") or "Erreur simulée"),
        error_type=str(error.get("error_type") or error.get("type") or "EXECUTION_ERROR"),
        retryable=bool(error.get("retryable", False)),
    )

"""FORGE Agent Protocol (FAP v1) event format → :class:`TraceEventData` (docs/AGENT_PROTOCOL.md).

Events come inline in agent responses (``events``) or are pushed to ``POST /runs/{id}/events``.
Parsing is tolerant: an unknown ``type`` becomes ``custom`` (original kept in ``original_type``),
timing falls back to ``offset_ms`` relative to a base time, then to the previous event's end.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from forge.domain.enums import EventStatus, TraceEventSource, TraceEventType
from forge.domain.types import TokenUsage, TraceEventData

FAP_VERSION = "forge-agent-protocol/v1"
#: Attempts for which the invocation span id is recognised as the agent's root parent.
MAX_TRACKED_ATTEMPTS = 10


def invocation_span_id(run_id: str, attempt: int) -> str:
    """Deterministic span id of the runner's invocation (``traceparent``) for one attempt of a run.

    Being derivable from the run id, it lets trace ingestion recognise the agent's root spans even
    when they arrive before the runner persisted the trace.
    """
    return hashlib.sha256(f"forge-invocation:{run_id}:{attempt}".encode()).hexdigest()[:16]


def invocation_span_ids(run_id: str) -> frozenset[str]:
    return frozenset(invocation_span_id(run_id, a) for a in range(1, MAX_TRACKED_ATTEMPTS + 1))


#: Top-level convenience fields of a FAP event copied into ``attributes``.
_ATTRIBUTE_SHORTCUTS = (
    "model", "tool", "arguments", "input_tokens", "output_tokens", "cost", "documents", "agent",
    "error_type", "http_status",
)  # fmt: skip

EVENT_TYPE_ALIASES: dict[str, TraceEventType] = {
    "llm": TraceEventType.llm_call,
    "model_call": TraceEventType.llm_call,
    "tool": TraceEventType.tool_call,
    "tool_response": TraceEventType.tool_result,
    "thought": TraceEventType.reasoning,
    "thinking": TraceEventType.reasoning,
    "handoff": TraceEventType.agent_handoff,
    "search": TraceEventType.retrieval,
    "answer": TraceEventType.final_answer,
}


def parse_event_type(value: Any) -> tuple[TraceEventType, str | None]:
    """``(type, original)`` — ``original`` is set when the value had to be mapped to ``custom``."""
    raw = str(value or "").strip().lower()
    try:
        return TraceEventType(raw), None
    except ValueError:
        pass
    if raw in EVENT_TYPE_ALIASES:
        return EVENT_TYPE_ALIASES[raw], None
    return TraceEventType.custom, raw or None


def parse_datetime(value: Any) -> datetime | None:
    """ISO 8601 string (``Z`` accepted) or epoch seconds → aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_protocol_events(
    items: list[Any] | None,
    *,
    base_time: datetime,
    source: TraceEventSource = TraceEventSource.adapter,
    key_prefix: str = "fap:",
    extra_attributes: dict[str, Any] | None = None,
) -> list[TraceEventData]:
    """Convert FAP JSON events. Non-dict items are skipped; ids are namespaced with ``key_prefix``."""
    events: list[TraceEventData] = []
    cursor = base_time
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        event = _parse_one(item, index=index, cursor=cursor, base_time=base_time, source=source,
                           key_prefix=key_prefix)  # fmt: skip
        if extra_attributes:
            for key, value in extra_attributes.items():
                event.attributes.setdefault(key, value)
        events.append(event)
        cursor = event.ended_at or event.started_at
    return events


def _parse_one(
    item: dict[str, Any],
    *,
    index: int,
    cursor: datetime,
    base_time: datetime,
    source: TraceEventSource,
    key_prefix: str,
) -> TraceEventData:
    event_type, original = parse_event_type(item.get("type"))
    attributes: dict[str, Any] = dict(item["attributes"]) if isinstance(item.get("attributes"), dict) else {}
    for name in _ATTRIBUTE_SHORTCUTS:
        if item.get(name) is not None:
            attributes.setdefault(name, item[name])
    if original:
        attributes.setdefault("original_type", original)
    name = str(item.get("name") or attributes.get("tool") or event_type.value)
    if event_type in (TraceEventType.tool_call, TraceEventType.tool_result):
        attributes.setdefault("tool", name)
    started, ended = _timing(item, cursor=cursor, base_time=base_time)
    status = EventStatus.error if str(item.get("status", "ok")).lower() == "error" else EventStatus.ok
    local_id = item.get("id")
    parent_id = item.get("parent_id")
    return TraceEventData(
        type=event_type,
        name=name[:500],
        started_at=started,
        ended_at=ended,
        key=f"{key_prefix}{local_id if local_id not in (None, '') else f'#{index}'}",
        status=status,
        parent_key=f"{key_prefix}{parent_id}" if parent_id not in (None, "") else None,
        input=item.get("input"),
        output=item.get("output"),
        attributes=attributes,
        source=source,
        span_id=str(item["span_id"]) if item.get("span_id") else None,
        parent_span_id=str(item["parent_span_id"]) if item.get("parent_span_id") else None,
    )


def _timing(item: dict[str, Any], *, cursor: datetime, base_time: datetime) -> tuple[datetime, datetime]:
    started = parse_datetime(item.get("started_at"))
    offset = _number(item.get("offset_ms"))
    if started is None:
        started = base_time + timedelta(milliseconds=offset) if offset is not None else cursor
    ended = parse_datetime(item.get("ended_at"))
    duration = _number(item.get("duration_ms"))
    if ended is None:
        ended = started + timedelta(milliseconds=max(0.0, duration or 0.0))
    if ended < started:
        ended = started
    return started, ended


def usage_from_events(events: list[TraceEventData]) -> tuple[TokenUsage, int, float | None]:
    """``(usage, model_calls, cost)`` summed over the ``llm_call`` events of a trace."""
    usage = TokenUsage()
    calls = 0
    cost: float | None = None
    for event in events:
        if event.type != TraceEventType.llm_call:
            continue
        calls += 1
        usage.input_tokens += int(_number(event.attributes.get("input_tokens")) or 0)
        usage.output_tokens += int(_number(event.attributes.get("output_tokens")) or 0)
        event_cost = _number(event.attributes.get("cost"))
        if event_cost is not None:
            cost = (cost or 0.0) + event_cost
    return usage, calls, cost


def parse_usage(data: Any) -> TokenUsage:
    """``{"input_tokens"|"prompt_tokens", "output_tokens"|"completion_tokens"}`` → :class:`TokenUsage`."""
    if not isinstance(data, dict):
        return TokenUsage()
    input_tokens = data.get("input_tokens", data.get("prompt_tokens"))
    output_tokens = data.get("output_tokens", data.get("completion_tokens"))
    return TokenUsage(
        input_tokens=int(_number(input_tokens) or 0), output_tokens=int(_number(output_tokens) or 0)
    )

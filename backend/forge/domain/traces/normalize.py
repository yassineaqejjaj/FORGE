"""Preparation of trace events for persistence (docs §8 step 6).

* events are sorted by ``started_at`` (stable), numbered ``seq`` 1..n (or from ``start_seq``);
* ``offset_ms`` is computed from the start of the run, ``duration_ms`` from start/end;
* parents are resolved from local keys (``parent_key``) or OTel span ids (``parent_span_id``);
  cycles and self-references are dropped;
* payloads (input, output, attribute values) are truncated to ``max_payload_chars``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from forge.domain.enums import EventStatus, TraceEventSource, TraceEventType
from forge.domain.types import TraceEventData

TRUNCATION_MARK = "… [tronqué, {n} caractères]"
#: Maximum number of attributes kept per event (raw OTel attributes can be numerous).
_MAX_ATTRIBUTES = 200


@dataclass(slots=True)
class PlannedEvent:
    """An event ready to be stored: ``parent_index`` points into the planned list (or is ``None``)."""

    seq: int
    type: TraceEventType
    name: str
    source: TraceEventSource
    status: EventStatus
    started_at: datetime
    ended_at: datetime | None
    offset_ms: float
    duration_ms: float | None
    input: Any
    output: Any
    attributes: dict[str, Any] = field(default_factory=dict)
    span_id: str | None = None
    parent_span_id: str | None = None
    parent_index: int | None = None
    #: Parent stored outside this batch (``parent_span_id`` of an already persisted event).
    external_parent_span_id: str | None = None
    key: str = ""


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + TRUNCATION_MARK.format(n=len(text))


def truncate_payload(value: Any, max_chars: int) -> Any:
    """Truncate string leaves; a structure still larger than ``max_chars`` becomes a preview dict."""
    if max_chars <= 0 or value is None:
        return value
    reduced = _truncate_leaves(value, max_chars)
    if isinstance(reduced, dict | list):
        serialized = json.dumps(reduced, ensure_ascii=False, default=str)
        if len(serialized) > max_chars:
            return {"_truncated": True, "original_chars": len(serialized), "preview": serialized[:max_chars]}
    return reduced


def _truncate_leaves(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        return truncate_text(value, max_chars)
    if isinstance(value, dict):
        return {str(k): _truncate_leaves(v, max_chars) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_truncate_leaves(v, max_chars) for v in value]
    if isinstance(value, int | float | bool):
        return value
    return str(value)


def jsonable(value: Any) -> Any:
    """Make a payload JSON-serialisable (datetimes, enums, sets, arbitrary objects → str)."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return str(value)


def order_events(events: list[TraceEventData]) -> list[TraceEventData]:
    """Stable chronological order (ties keep the recording order)."""
    return [e for _, e in sorted(enumerate(events), key=lambda pair: (pair[1].started_at, pair[0]))]


def plan_events(
    events: list[TraceEventData],
    *,
    origin: datetime,
    max_payload_chars: int,
    start_seq: int = 1,
    known_span_ids: set[str] | frozenset[str] = frozenset(),
) -> list[PlannedEvent]:
    """Order, number, resolve parents and truncate. ``known_span_ids`` = spans already persisted."""
    ordered = order_events(events)
    by_key = {e.key: i for i, e in enumerate(ordered) if e.key}
    by_span = {e.span_id: i for i, e in enumerate(ordered) if e.span_id}
    planned: list[PlannedEvent] = []
    for index, event in enumerate(ordered):
        parent_index = _resolve_parent(event, by_key, by_span)
        if parent_index == index:
            parent_index = None
        external = None
        if parent_index is None and event.parent_span_id and event.parent_span_id in known_span_ids:
            external = event.parent_span_id
        ended = event.ended_at
        planned.append(
            PlannedEvent(
                seq=start_seq + index,
                type=event.type,
                name=truncate_text(event.name or event.type.value, 500),
                source=event.source,
                status=event.status,
                started_at=event.started_at,
                ended_at=ended,
                offset_ms=round(max(0.0, (event.started_at - origin).total_seconds() * 1000), 3),
                duration_ms=round(event.duration_ms, 3) if event.duration_ms is not None else None,
                input=truncate_payload(jsonable(event.input), max_payload_chars),
                output=truncate_payload(jsonable(event.output), max_payload_chars),
                attributes=_attributes(event.attributes, max_payload_chars),
                span_id=event.span_id,
                parent_span_id=event.parent_span_id,
                parent_index=parent_index,
                external_parent_span_id=external,
                key=event.key,
            )
        )
    _break_cycles(planned)
    return planned


def _resolve_parent(event: TraceEventData, by_key: dict[str, int], by_span: dict[str, int]) -> int | None:
    if event.parent_key and event.parent_key in by_key:
        return by_key[event.parent_key]
    if event.parent_span_id and event.parent_span_id in by_span:
        return by_span[event.parent_span_id]
    return None


def _attributes(attributes: dict[str, Any], max_chars: int) -> dict[str, Any]:
    items = list((attributes or {}).items())[:_MAX_ATTRIBUTES]
    return {str(k): truncate_payload(jsonable(v), max_chars) for k, v in items}


def _break_cycles(planned: list[PlannedEvent]) -> None:
    """Drop parent links that would create a cycle (malformed agent-reported traces)."""
    for index, event in enumerate(planned):
        seen = {index}
        current = event.parent_index
        while current is not None:
            if current in seen:
                event.parent_index = None
                break
            seen.add(current)
            current = planned[current].parent_index

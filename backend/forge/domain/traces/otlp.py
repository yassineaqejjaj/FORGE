"""OTLP spans (JSON form of ``ExportTraceServiceRequest``) → :class:`TraceEventData` (docs §8.2).

Input is the OTLP/JSON encoding (``resourceSpans[].scopeSpans[].spans[]``, lowerCamelCase). Ids may
be hex (OTLP/JSON) or base64 (generic protobuf → JSON conversion): both are normalised to lowercase
hex. The mapping follows the OpenTelemetry GenAI semantic conventions:

=====================================  ===========================================================
Span                                   Event
=====================================  ===========================================================
``forge.event.type`` attribute         that type (explicit override)
``gen_ai.operation.name`` = chat,      ``llm_call`` (model, input/output tokens, cost)
text_completion, generate_content,
embeddings
``gen_ai.operation.name`` =            ``tool_call`` (``gen_ai.tool.name``, call arguments/result)
execute_tool, or ``gen_ai.tool.name``
``gen_ai.operation.name`` =            ``agent_handoff`` (nested agent) or ``custom`` (root agent)
invoke_agent / create_agent
retrieval / ``db.system`` / vector db  ``retrieval``
other spans                            ``custom`` (``error`` when the span failed)
=====================================  ===========================================================
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from forge.domain.enums import EventStatus, TraceEventSource, TraceEventType
from forge.domain.types import TraceEventData

RUN_ID_ATTRIBUTE = "forge.run_id"
EVENT_TYPE_ATTRIBUTES = ("forge.event.type", "forge.event_type")
STATUS_CODE_ERROR = 2

LLM_OPERATIONS = frozenset({"chat", "text_completion", "generate_content", "embeddings", "completion"})
TOOL_OPERATIONS = frozenset({"execute_tool"})
AGENT_OPERATIONS = frozenset({"invoke_agent", "create_agent"})
RETRIEVAL_OPERATIONS = frozenset({"retrieval", "retrieve", "search_documents"})

_INPUT_TOKENS_KEYS = ("gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt")
_OUTPUT_TOKENS_KEYS = (
    "gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens", "llm.token_count.completion",
)  # fmt: skip
_COST_KEYS = ("gen_ai.usage.cost", "forge.cost", "llm.cost.total")
_INPUT_KEYS = (
    "gen_ai.input.messages", "gen_ai.prompt", "gen_ai.tool.call.arguments", "input.value", "forge.input",
)  # fmt: skip
_OUTPUT_KEYS = (
    "gen_ai.output.messages", "gen_ai.completion", "gen_ai.tool.call.result", "output.value", "forge.output",
)  # fmt: skip
#: Raw attributes kept on the event (besides the well-known keys) — bounded to keep rows small.
_MAX_RAW_ATTRIBUTES = 60


@dataclass(slots=True)
class OtlpSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str | None
    start: datetime
    end: datetime | None
    attributes: dict[str, Any] = field(default_factory=dict)
    resource: dict[str, Any] = field(default_factory=dict)
    scope: str | None = None
    status_code: int = 0
    status_message: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def run_id(self) -> str | None:
        value = self.attributes.get(RUN_ID_ATTRIBUTE) or self.resource.get(RUN_ID_ATTRIBUTE)
        return str(value) if value else None


# --- Decoding helpers -------------------------------------------------------------------------------


def normalize_id(value: Any, length: int) -> str | None:
    """Hex id of ``length`` bytes from hex or base64 text; ``None`` for empty/invalid/all-zero ids."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    candidate: str | None = None
    if len(text) == length * 2:
        try:
            bytes.fromhex(text)
            candidate = text.lower()
        except ValueError:
            candidate = None
    if candidate is None:
        try:
            raw = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            return None
        if len(raw) != length:
            return None
        candidate = raw.hex()
    return None if set(candidate) == {"0"} else candidate


def any_value(value: Any) -> Any:
    """Decode an OTLP ``AnyValue`` (``{"stringValue": …}``, ``{"arrayValue": {"values": […]}}``…)."""
    if not isinstance(value, dict):
        return value
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        try:
            return int(value["intValue"])
        except (TypeError, ValueError):
            return value["intValue"]
    if "doubleValue" in value:
        try:
            return float(value["doubleValue"])
        except (TypeError, ValueError):
            return value["doubleValue"]
    if "arrayValue" in value:
        return [any_value(v) for v in (value["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in value:
        return attributes_dict((value["kvlistValue"] or {}).get("values", []))
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def attributes_dict(items: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("key"):
            result[str(item["key"])] = any_value(item.get("value"))
    return result


def unix_nano(value: Any) -> datetime | None:
    try:
        nanos = int(value)
    except (TypeError, ValueError):
        return None
    if nanos <= 0:
        return None
    return datetime.fromtimestamp(nanos / 1_000_000_000, tz=UTC)


def iter_spans(request: dict[str, Any]) -> Iterator[OtlpSpan]:
    """Yield every well-formed span of an OTLP/JSON export request (malformed spans are skipped)."""
    for resource_spans in (request or {}).get("resourceSpans") or []:
        if not isinstance(resource_spans, dict):
            continue
        resource = attributes_dict((resource_spans.get("resource") or {}).get("attributes"))
        for scope_spans in resource_spans.get("scopeSpans") or []:
            if not isinstance(scope_spans, dict):
                continue
            scope = (scope_spans.get("scope") or {}).get("name")
            for raw in scope_spans.get("spans") or []:
                span = _parse_span(raw, resource=resource, scope=scope)
                if span is not None:
                    yield span


def count_spans(request: dict[str, Any]) -> int:
    total = 0
    for resource_spans in (request or {}).get("resourceSpans") or []:
        for scope_spans in (resource_spans or {}).get("scopeSpans") or []:
            total += len((scope_spans or {}).get("spans") or [])
    return total


def _parse_span(raw: Any, *, resource: dict[str, Any], scope: str | None) -> OtlpSpan | None:
    if not isinstance(raw, dict):
        return None
    trace_id = normalize_id(raw.get("traceId"), 16)
    span_id = normalize_id(raw.get("spanId"), 8)
    start = unix_nano(raw.get("startTimeUnixNano"))
    if trace_id is None or span_id is None or start is None:
        return None
    status = raw.get("status") or {}
    code = status.get("code", 0)
    if isinstance(code, str):
        code = STATUS_CODE_ERROR if code.upper().endswith("ERROR") else 0
    return OtlpSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=normalize_id(raw.get("parentSpanId"), 8),
        name=str(raw.get("name") or "span"),
        kind=str(raw["kind"]) if raw.get("kind") is not None else None,
        start=start,
        end=unix_nano(raw.get("endTimeUnixNano")),
        attributes=attributes_dict(raw.get("attributes")),
        resource=resource,
        scope=scope,
        status_code=int(code or 0),
        status_message=str(status.get("message") or ""),
        events=[e for e in raw.get("events") or [] if isinstance(e, dict)],
    )


# --- Mapping ----------------------------------------------------------------------------------------


def classify_span(span: OtlpSpan, *, root_span_ids: Collection[str] = ()) -> TraceEventType:
    """``root_span_ids``: span ids of the FORGE invocation (``traceparent``) — children are the agent root."""
    attrs = span.attributes
    for key in EVENT_TYPE_ATTRIBUTES:
        explicit = attrs.get(key)
        if explicit:
            try:
                return TraceEventType(str(explicit))
            except ValueError:
                break
    operation = str(attrs.get("gen_ai.operation.name") or "").lower()
    if operation in LLM_OPERATIONS:
        return TraceEventType.llm_call
    if operation in TOOL_OPERATIONS or attrs.get("gen_ai.tool.name"):
        return TraceEventType.tool_call
    if operation in AGENT_OPERATIONS:
        nested = span.parent_span_id is not None and span.parent_span_id not in root_span_ids
        return TraceEventType.agent_handoff if nested else TraceEventType.custom
    if operation in RETRIEVAL_OPERATIONS or attrs.get("db.system") or attrs.get("gen_ai.data_source.id"):
        return TraceEventType.retrieval
    if attrs.get("gen_ai.request.model") or attrs.get("gen_ai.system") or attrs.get("gen_ai.provider.name"):
        return TraceEventType.llm_call
    if span.status_code == STATUS_CODE_ERROR:
        return TraceEventType.error
    return TraceEventType.custom


def span_to_event(
    span: OtlpSpan, *, root_span_ids: Collection[str] = (), source: TraceEventSource = TraceEventSource.otlp
) -> TraceEventData:
    event_type = classify_span(span, root_span_ids=root_span_ids)
    attributes = _well_known_attributes(span, event_type)
    status = EventStatus.error if span.status_code == STATUS_CODE_ERROR else EventStatus.ok
    if status == EventStatus.error and span.status_message:
        attributes.setdefault("error", span.status_message)
    return TraceEventData(
        type=event_type,
        name=_event_name(span, event_type, attributes),
        started_at=span.start,
        ended_at=span.end if span.end and span.end >= span.start else span.start,
        key=f"otlp:{span.span_id}",
        status=status,
        parent_key=f"otlp:{span.parent_span_id}" if span.parent_span_id else None,
        input=_payload(span, _INPUT_KEYS, ("gen_ai.content.prompt", "gen_ai.user.message")),
        output=_payload(span, _OUTPUT_KEYS, ("gen_ai.content.completion", "gen_ai.choice")),
        attributes=attributes,
        source=source,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
    )


def spans_to_events(
    request: dict[str, Any], *, root_span_ids: Collection[str] = ()
) -> list[tuple[OtlpSpan, TraceEventData]]:
    return [(span, span_to_event(span, root_span_ids=root_span_ids)) for span in iter_spans(request)]


def _first(attrs: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if attrs.get(key) not in (None, ""):
            return attrs[key]
    return None


def _well_known_attributes(span: OtlpSpan, event_type: TraceEventType) -> dict[str, Any]:
    attrs = span.attributes
    result: dict[str, Any] = {}
    model = attrs.get("gen_ai.response.model") or attrs.get("gen_ai.request.model")
    if model:
        result["model"] = model
    input_tokens = _first(attrs, _INPUT_TOKENS_KEYS)
    output_tokens = _first(attrs, _OUTPUT_TOKENS_KEYS)
    if input_tokens is not None:
        result["input_tokens"] = _as_int(input_tokens)
    if output_tokens is not None:
        result["output_tokens"] = _as_int(output_tokens)
    cost = _first(attrs, _COST_KEYS)
    if cost is not None:
        result["cost"] = _as_float(cost)
    if attrs.get("gen_ai.tool.name"):
        result["tool"] = attrs["gen_ai.tool.name"]
    if attrs.get("gen_ai.tool.call.arguments") is not None:
        result["arguments"] = _maybe_json(attrs["gen_ai.tool.call.arguments"])
    if attrs.get("gen_ai.agent.name"):
        result["agent"] = attrs["gen_ai.agent.name"]
    if attrs.get("http.response.status_code") is not None:
        result["http_status"] = attrs["http.response.status_code"]
    if attrs.get("error.type"):
        result["error_type"] = attrs["error.type"]
    documents = attrs.get("forge.documents") or attrs.get("gen_ai.retrieval.documents")
    if isinstance(documents, list):
        result["documents"] = [str(d) for d in documents]
        result["documents_count"] = len(documents)
    if event_type == TraceEventType.llm_call and attrs.get("gen_ai.response.finish_reasons"):
        result["finish_reason"] = attrs["gen_ai.response.finish_reasons"]
    result["otel.span_name"] = span.name
    if span.kind:
        result["otel.span_kind"] = span.kind
    if span.scope:
        result["otel.scope"] = span.scope
    service = span.resource.get("service.name")
    if service:
        result["service.name"] = service
    raw = [(k, v) for k, v in attrs.items() if k not in _INPUT_KEYS and k not in _OUTPUT_KEYS]
    for key, value in raw[:_MAX_RAW_ATTRIBUTES]:
        result.setdefault(key, value)
    return result


def _event_name(span: OtlpSpan, event_type: TraceEventType, attributes: dict[str, Any]) -> str:
    if event_type == TraceEventType.tool_call and attributes.get("tool"):
        return str(attributes["tool"])
    if event_type == TraceEventType.agent_handoff and attributes.get("agent"):
        return f"Délégation à {attributes['agent']}"
    return span.name


def _payload(span: OtlpSpan, keys: tuple[str, ...], event_names: tuple[str, ...]) -> Any:
    value = _first(span.attributes, keys)
    if value is not None:
        return _maybe_json(value)
    for event in span.events:
        if event.get("name") in event_names:
            attrs = attributes_dict(event.get("attributes"))
            found = _first(attrs, ("gen_ai.prompt", "gen_ai.completion", "content", "message", "body"))
            if found is not None:
                return _maybe_json(found)
    return None


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

"""OTLP mapping (GenAI semantic conventions) and OTLP/HTTP payload decoding."""

from __future__ import annotations

import base64
import gzip
import json

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span

from forge.domain.enums import EventStatus, TraceEventType
from forge.domain.traces.otlp import classify_span, iter_spans, normalize_id, span_to_event, spans_to_events
from forge.services.trace_ingest import IngestError, IngestResult, decode_otlp, encode_response

TRACE_ID = "5b8efff798038103d269b633813fc60c"
NS = 1_772_355_600_000_000_000  # 2026-03-01T09:00:00Z


def _attr(key: str, value: object) -> dict:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def _span(span_id: str, name: str, attrs: dict, *, parent: str | None = None, start_ms: int = 0,
          duration_ms: int = 100, error: bool = False) -> dict:  # fmt: skip
    span = {
        "traceId": TRACE_ID,
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": str(NS + start_ms * 1_000_000),
        "endTimeUnixNano": str(NS + (start_ms + duration_ms) * 1_000_000),
        "attributes": [_attr(k, v) for k, v in attrs.items()],
    }
    if parent:
        span["parentSpanId"] = parent
    if error:
        span["status"] = {"code": 2, "message": "outil en panne"}
    return span


def _request(*spans: dict) -> dict:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", "agent-x")]},
                "scopeSpans": [{"scope": {"name": "agent"}, "spans": list(spans)}],
            }
        ]
    }


def test_genai_spans_map_to_event_types_and_attributes() -> None:
    request = _request(
        _span("a" * 16, "invoke_agent planner", {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "planner"},
              parent="f" * 16, duration_ms=2000),
        _span("b" * 16, "chat gpt", {"gen_ai.operation.name": "chat", "gen_ai.request.model": "gpt-x",
              "gen_ai.usage.input_tokens": 120, "gen_ai.usage.output_tokens": 30,
              "gen_ai.output.messages": json.dumps([{"role": "assistant", "content": "Bonjour"}])},
              parent="a" * 16, start_ms=10),
        _span("c" * 16, "execute_tool", {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "jira.search",
              "gen_ai.tool.call.arguments": '{"query": "export"}'}, parent="a" * 16, start_ms=200, error=True),
        _span("d" * 16, "invoke_agent writer", {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "writer"},
              parent="a" * 16, start_ms=300),
        _span("e" * 16, "vector search", {"db.system": "qdrant"}, parent="a" * 16, start_ms=400),
        _span("1" * 16, "custom", {"forge.event.type": "decision", "forge.run_id": "run-1"}, start_ms=500),
    )  # fmt: skip
    events = [e for _, e in spans_to_events(request, root_span_ids={"f" * 16})]
    by_span = {e.span_id: e for e in events}
    root, llm, tool, sub, retrieval, decision = (by_span[c * 16] for c in "abcde1")
    assert root.type == TraceEventType.custom  # root agent (parent = FORGE invocation span)
    assert llm.type == TraceEventType.llm_call and llm.attributes["model"] == "gpt-x"
    assert (llm.attributes["input_tokens"], llm.attributes["output_tokens"]) == (120, 30)
    assert llm.output == [{"role": "assistant", "content": "Bonjour"}]
    assert llm.parent_key == root.key and llm.duration_ms == pytest.approx(100)
    assert tool.type == TraceEventType.tool_call and tool.name == "jira.search"
    assert tool.attributes["arguments"] == {"query": "export"} and tool.status == EventStatus.error
    assert tool.attributes["error"] == "outil en panne"
    assert sub.type == TraceEventType.agent_handoff and sub.name == "Délégation à writer"
    assert retrieval.type == TraceEventType.retrieval
    assert decision.type == TraceEventType.decision
    assert root.attributes["service.name"] == "agent-x"
    span = next(s for s in iter_spans(request) if s.span_id == "1" * 16)
    assert span.run_id == "run-1"


def test_ids_accept_hex_and_base64_and_skip_invalid_spans() -> None:
    raw = bytes.fromhex(TRACE_ID)
    assert normalize_id(base64.b64encode(raw).decode(), 16) == TRACE_ID
    assert normalize_id(TRACE_ID.upper(), 16) == TRACE_ID
    assert normalize_id("0" * 32, 16) is None
    assert normalize_id("not-an-id", 16) is None
    request = _request(_span("a" * 16, "ok", {}), {"traceId": TRACE_ID, "name": "sans id"})
    assert [s.span_id for s in iter_spans(request)] == ["a" * 16]


def test_classify_falls_back_to_error_and_custom() -> None:
    (span,) = iter_spans(_request(_span("a" * 16, "x", {}, error=True)))
    assert classify_span(span) == TraceEventType.error
    (span,) = iter_spans(_request(_span("a" * 16, "x", {})))
    assert span_to_event(span).type == TraceEventType.custom


def _protobuf_request() -> ExportTraceServiceRequest:
    message = ExportTraceServiceRequest()
    scope = message.resource_spans.add().scope_spans.add()
    span: Span = scope.spans.add()
    span.trace_id = bytes.fromhex(TRACE_ID)
    span.span_id = bytes.fromhex("a" * 16)
    span.name = "chat"
    span.start_time_unix_nano = NS
    span.end_time_unix_nano = NS + 5_000_000
    span.attributes.append(KeyValue(key="gen_ai.operation.name", value=AnyValue(string_value="chat")))
    span.attributes.append(KeyValue(key="gen_ai.usage.input_tokens", value=AnyValue(int_value=42)))
    return message


def test_decode_protobuf_gzip_and_json() -> None:
    body = gzip.compress(_protobuf_request().SerializeToString())
    data = decode_otlp(body, content_type="application/x-protobuf", content_encoding="gzip", max_bytes=10_000)
    (event,) = [e for _, e in spans_to_events(data)]
    assert event.span_id == "a" * 16 and event.attributes["input_tokens"] == 42
    assert event.type == TraceEventType.llm_call
    as_json = json.dumps(_request(_span("b" * 16, "x", {}))).encode()
    assert decode_otlp(as_json, content_type="application/json; charset=utf-8")["resourceSpans"]


def test_decode_rejects_bad_payloads() -> None:
    with pytest.raises(IngestError) as exc:
        decode_otlp(b"{}", content_type="text/plain")
    assert exc.value.status_code == 415
    with pytest.raises(IngestError):
        decode_otlp(b"not json", content_type="application/json")
    with pytest.raises(IngestError):
        decode_otlp(b"\xff\xff\xff", content_type="application/x-protobuf")
    bomb = gzip.compress(b"0" * 50_000)
    with pytest.raises(IngestError) as exc:
        decode_otlp(bomb, content_type="application/json", content_encoding="gzip", max_bytes=1000)
    assert exc.value.status_code == 413


def test_encode_response_partial_success() -> None:
    ok, media = encode_response(IngestResult(received=2, attached=2), protobuf=False)
    assert json.loads(ok) == {"partialSuccess": {}} and media == "application/json"
    partial, _ = encode_response(IngestResult(received=3, attached=1, orphans=2), protobuf=False)
    body = json.loads(partial)["partialSuccess"]
    assert body["rejectedSpans"] == "2" and "sans run" in body["errorMessage"]
    raw, media = encode_response(IngestResult(received=3, attached=1, orphans=2), protobuf=True)
    parsed = ExportTraceServiceResponse.FromString(raw)
    assert media == "application/x-protobuf" and parsed.partial_success.rejected_spans == 2

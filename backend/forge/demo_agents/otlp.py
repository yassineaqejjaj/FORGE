"""White-box mode: push the agent's steps to FORGE as OTLP/JSON spans (GenAI semantic conventions).

Enabled per agent version with ``adapter_config.parameters.white_box = true``. The spans use the
run's trace id (from ``traceparent``), so FORGE attaches them to the run. Best effort: any failure
is reported to the caller, which then falls back to inline events — the response never fails.

Environment: ``FORGE_OTLP_INGEST_URL`` (e.g. ``http://api:8000/v1/traces``) and ``FORGE_DEMO_OTLP_KEY``
(an API key with the ``traces:write`` scope).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from forge.demo_agents.common import DemoRequest

logger = logging.getLogger("forge.demo_agents.otlp")

PUSH_TIMEOUT_SECONDS = 3.0
_OPERATIONS = {"llm_call": "chat", "tool_call": "execute_tool"}


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        typed: dict[str, Any] = {"boolValue": value}
    elif isinstance(value, int):
        typed = {"intValue": str(value)}
    elif isinstance(value, float):
        typed = {"doubleValue": value}
    elif isinstance(value, str):
        typed = {"stringValue": value}
    else:
        typed = {"stringValue": json.dumps(value, ensure_ascii=False)}
    return {"key": key, "value": typed}


def _nanos(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1_000_000_000))


def parse_traceparent(value: str | None) -> tuple[str, str | None] | None:
    parts = (value or "").split("-")
    if len(parts) != 4 or len(parts[1]) != 32:
        return None
    return parts[1], parts[2] if len(parts[2]) == 16 else None


def build_export(
    request: DemoRequest, *, agent_name: str, model: str, events: list[dict[str, Any]], started_at: datetime
) -> dict[str, Any] | None:
    """OTLP/JSON ``ExportTraceServiceRequest``: one ``invoke_agent`` root span + one span per step."""
    ids = parse_traceparent(request.traceparent)
    if ids is None and request.trace_id and len(str(request.trace_id)) == 32:
        ids = (str(request.trace_id), None)
    if ids is None:
        return None
    trace_id, parent = ids
    root_id = secrets.token_hex(8)
    total_ms = max((e.get("offset_ms", 0) + e.get("duration_ms", 0) for e in events), default=0.0)
    root: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": root_id,
        "name": f"invoke_agent {agent_name}",
        "kind": 1,
        "startTimeUnixNano": _nanos(started_at),
        "endTimeUnixNano": _nanos(started_at + timedelta(milliseconds=total_ms)),
        "attributes": [
            _attr("gen_ai.operation.name", "invoke_agent"),
            _attr("gen_ai.agent.name", agent_name),
            _attr("forge.run_id", request.run_id),
        ],
    }
    if parent:
        root["parentSpanId"] = parent
    spans = [root]
    results = {e.get("parent_id"): e for e in events if e.get("type") == "tool_result"}
    for event in events:
        if event.get("type") == "tool_result":
            continue
        spans.append(
            _span(
                event,
                trace_id=trace_id,
                parent=root_id,
                started_at=started_at,
                model=model,
                result=results.get(event.get("id")),
            )
        )
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", f"demo-{agent_name}")]},
                "scopeSpans": [{"scope": {"name": "forge.demo_agents"}, "spans": spans}],
            }
        ]
    }


def _span(
    event: dict[str, Any],
    *,
    trace_id: str,
    parent: str,
    started_at: datetime,
    model: str,
    result: dict | None,
) -> dict[str, Any]:
    start = started_at + timedelta(milliseconds=float(event.get("offset_ms") or 0))
    end = start + timedelta(milliseconds=float(event.get("duration_ms") or 0))
    attrs = dict(event.get("attributes") or {})
    kind = str(event.get("type"))
    attributes = [_attr("forge.event.type", kind)]
    if kind in _OPERATIONS:
        attributes.append(_attr("gen_ai.operation.name", _OPERATIONS[kind]))
    if kind == "llm_call":
        attributes += [
            _attr("gen_ai.request.model", attrs.get("model") or model),
            _attr("gen_ai.usage.input_tokens", int(attrs.get("input_tokens") or 0)),
            _attr("gen_ai.usage.output_tokens", int(attrs.get("output_tokens") or 0)),
            _attr("gen_ai.usage.cost", float(attrs.get("cost") or 0.0)),
        ]
    if kind == "tool_call":
        attributes += [
            _attr("gen_ai.tool.name", attrs.get("tool") or event.get("name")),
            _attr("gen_ai.tool.call.arguments", event.get("input") or {}),
        ]
        if result is not None:
            attributes.append(_attr("gen_ai.tool.call.result", result.get("output")))
    if attrs.get("documents"):
        attributes.append(
            {
                "key": "forge.documents",
                "value": {"arrayValue": {"values": [{"stringValue": str(d)} for d in attrs["documents"]]}},
            }
        )
    if event.get("output") is not None and kind not in ("tool_call",):
        attributes.append(_attr("forge.output", event["output"]))
    return {
        "traceId": trace_id,
        "spanId": secrets.token_hex(8),
        "parentSpanId": parent,
        "name": str(event.get("name")),
        "kind": 1,
        "startTimeUnixNano": _nanos(start),
        "endTimeUnixNano": _nanos(end),
        "attributes": attributes,
    }


async def push(export: dict[str, Any], *, transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    """POST the export to ``FORGE_OTLP_INGEST_URL``. Returns ``None`` on success, else the reason."""
    url = os.environ.get("FORGE_OTLP_INGEST_URL", "").strip()
    key = os.environ.get("FORGE_DEMO_OTLP_KEY", "").strip()
    if not url or not key:
        return "FORGE_OTLP_INGEST_URL / FORGE_DEMO_OTLP_KEY non configurés"
    try:
        async with httpx.AsyncClient(timeout=PUSH_TIMEOUT_SECONDS, transport=transport) as client:
            response = await client.post(url, json=export, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        logger.warning("OTLP push failed: %s", type(exc).__name__)
        return f"envoi OTLP impossible ({type(exc).__name__})"
    if response.status_code >= 300:
        logger.warning("OTLP push rejected: HTTP %s", response.status_code)
        return f"envoi OTLP refusé (HTTP {response.status_code})"
    return None


def now() -> datetime:
    return datetime.now(UTC)

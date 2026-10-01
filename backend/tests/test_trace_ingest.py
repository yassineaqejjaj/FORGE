"""Trace ingestion API: OTLP/HTTP (JSON, protobuf, gzip), correlation, limits, auth, JSON events."""

from __future__ import annotations

import gzip
import json
import uuid

import httpx
import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from sqlalchemy import inspect, select

from forge.config import settings
from forge.domain.enums import Role, TraceEventSource, TraceEventType
from forge.infra.db import utcnow
from forge.infra.models import ApiKey, EvaluationRun, TraceEvent
from forge.infra.security import generate_api_key
from tests.factories import create_agent_version, create_run, create_scenario_version
from tests.test_execution import otlp_export


async def new_run(session, *, classification: int = 1) -> EvaluationRun:
    av = await create_agent_version(session)
    sv = await create_scenario_version(session)
    run = await create_run(session, sv, av)
    if classification != 1:
        from forge.infra.models import Scenario

        scenario = await session.get(Scenario, run.scenario_id)
        scenario.classification = classification
        run.manifest = {
            **run.manifest,
            "scenario": {**run.manifest["scenario"], "classification": classification},
        }
    run.started_at = utcnow()
    await session.commit()
    return run


async def scoped_key(session, *, clearance: int = 1) -> str:
    generated = generate_api_key()
    session.add(ApiKey(name=f"agent-{uuid.uuid4().hex[:6]}", prefix=generated.prefix, key_hash=generated.key_hash,
                       role=Role.viewer, clearance=clearance, scopes=["traces:write"]))  # fmt: skip
    await session.commit()
    return generated.key


async def events_of(session, run: EvaluationRun) -> list[TraceEvent]:
    run_id = inspect(run).identity[0]  # safe on expired instances (no sync refresh)
    await session.commit()
    session.expire_all()
    return list(
        await session.scalars(select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.seq))
    )


def now_ns() -> int:
    return int(utcnow().timestamp() * 1e9)


async def test_otlp_json_attaches_spans_by_trace_id_and_reports_orphans(db_session, admin_client) -> None:
    run = await new_run(db_session)
    start = now_ns()
    export = otlp_export(run.otel_trace_id, [
        ("a1" * 8, None, "chat", {"gen_ai.operation.name": "chat", "gen_ai.request.model": "gpt-x",
                                  "gen_ai.usage.input_tokens": 10}, start, 30),
        ("a2" * 8, "a1" * 8, "execute_tool", {"gen_ai.tool.name": "jira.search"}, start + 1_000_000, 5),
    ])  # fmt: skip
    orphan = otlp_export("f" * 32, [("b1" * 8, None, "x", {}, start, 1)])
    export["resourceSpans"] += orphan["resourceSpans"]
    response = await admin_client.post("/v1/traces", json=export)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    partial = response.json()["partialSuccess"]
    assert partial["rejectedSpans"] == "1" and response.headers["x-forge-attached-spans"] == "2"
    events = await events_of(db_session, run)
    assert [(e.seq, e.type) for e in events] == [(1, TraceEventType.llm_call), (2, TraceEventType.tool_call)]
    assert events[1].parent_id == events[0].id and events[0].source == TraceEventSource.otlp
    assert events[0].attributes["model"] == "gpt-x"


async def test_otlp_protobuf_gzip_with_scoped_key_and_run_id_attribute(db_session, client) -> None:
    run = await new_run(db_session)
    key = await scoped_key(db_session)
    message = ExportTraceServiceRequest()
    span = message.resource_spans.add().scope_spans.add().spans.add()
    span.trace_id = bytes.fromhex("e" * 32)  # unknown trace id: correlated through forge.run_id
    span.span_id = bytes.fromhex("c" * 16)
    span.name = "chat"
    span.start_time_unix_nano = now_ns()
    span.end_time_unix_nano = span.start_time_unix_nano + 2_000_000
    span.attributes.append(KeyValue(key="forge.run_id", value=AnyValue(string_value=str(run.id))))
    span.attributes.append(KeyValue(key="gen_ai.operation.name", value=AnyValue(string_value="chat")))
    response = await client.post(
        "/v1/traces",
        content=gzip.compress(message.SerializeToString()),
        headers={
            "Content-Type": "application/x-protobuf",
            "Content-Encoding": "gzip",
            "Authorization": f"Bearer {key}",
        },
    )
    assert response.status_code == 200, response.text
    parsed = ExportTraceServiceResponse.FromString(response.content)
    assert not parsed.HasField("partial_success")
    (event,) = await events_of(db_session, run)
    assert event.span_id == "c" * 16 and event.type == TraceEventType.llm_call
    # A traces:write key is refused on the rest of the API.
    assert (await client.get("/api/v1/runs", headers={"Authorization": f"Bearer {key}"})).status_code == 403


async def test_runs_above_clearance_are_never_revealed(db_session, client) -> None:
    secret_run = await new_run(db_session, classification=3)
    secret_id = secret_run.id
    key = await scoped_key(db_session, clearance=1)
    export = otlp_export(secret_run.otel_trace_id, [("d1" * 8, None, "x", {}, now_ns(), 1)])
    response = await client.post("/v1/traces", json=export, headers={"X-Forge-Key": key})
    assert response.json()["partialSuccess"]["rejectedSpans"] == "1"
    assert await events_of(db_session, secret_run) == []
    pushed = await client.post(f"/api/v1/runs/{secret_id}/events", headers={"X-Forge-Key": key},
                               json={"events": [{"type": "message", "name": "x"}]})  # fmt: skip
    assert pushed.status_code == 404


async def test_otlp_limits_content_type_and_auth(
    db_session, client, admin_client, client_as, monkeypatch
) -> None:
    assert (await client.post("/v1/traces", json={})).status_code == 401
    viewer = await client_as(Role.viewer)
    assert (await viewer.post("/v1/traces", json={})).status_code == 403
    response = await admin_client.post("/v1/traces", content=b"x", headers={"Content-Type": "text/plain"})
    assert response.status_code == 415 and response.json()["code"] == "unsupported_media_type"
    bad = await admin_client.post(
        "/v1/traces", content=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert bad.status_code == 400
    monkeypatch.setattr(settings, "otlp_ingest_max_bytes", 64)
    big = await admin_client.post("/v1/traces", content=json.dumps({"resourceSpans": [], "x": "y" * 200}),
                                  headers={"Content-Type": "application/json"})  # fmt: skip
    assert big.status_code == 413


async def test_json_events_endpoint_appends_with_next_seq(db_session, admin_client) -> None:
    run = await new_run(db_session)
    first = await admin_client.post(f"/api/v1/runs/{run.id}/events", json={"events": [
        {"id": "s1", "type": "tool_call", "name": "crm.lookup", "offset_ms": 10, "duration_ms": 40, "input": {"id": 3}},
        {"id": "s2", "parent_id": "s1", "type": "tool_result", "name": "crm.lookup", "offset_ms": 50, "output": {"ok": True}},
    ]})  # fmt: skip
    assert first.status_code == 200, first.text
    assert first.json() == {
        "run_id": str(run.id),
        "accepted": 2,
        "duplicates": 0,
        "first_seq": 1,
        "last_seq": 2,
    }
    second = await admin_client.post(f"/api/v1/runs/{run.id}/events",
                                     json={"events": [{"type": "unknown_kind", "name": "Étape libre"}]})  # fmt: skip
    assert second.json()["first_seq"] == 3
    events = await events_of(db_session, run)
    assert events[1].parent_id == events[0].id and events[0].offset_ms == pytest.approx(10, abs=1)
    assert events[2].type == TraceEventType.custom and events[2].attributes["original_type"] == "unknown_kind"
    assert events[0].source == TraceEventSource.api
    missing = await admin_client.post(
        f"/api/v1/runs/{uuid.uuid4()}/events", json={"events": [{"type": "message"}]}
    )
    assert missing.status_code == 404
    empty = await admin_client.post(f"/api/v1/runs/{inspect(run).identity[0]}/events", json={"events": []})
    assert empty.status_code == 422


async def test_otlp_http_client_roundtrip_against_app(app, db_session) -> None:
    """Spans exported by an OTLP/HTTP JSON client (any language) are accepted at the root path."""
    run = await new_run(db_session)
    key = await scoped_key(db_session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://forge") as otlp_client:
        response = await otlp_client.post(
            "/v1/traces", headers={"Authorization": f"Bearer {key}"},
            json=otlp_export(run.otel_trace_id, [("9" * 16, None, "decision", {"forge.event.type": "decision"}, now_ns(), 1)]),
        )  # fmt: skip
    assert response.status_code == 200
    (event,) = await events_of(db_session, run)
    assert event.type == TraceEventType.decision

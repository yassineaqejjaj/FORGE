"""Agent Runner (docs §8): success, failures, retries, timeouts, budget, context providers, OTLP merge."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import inspect, select, update

from forge.adapters.http import use_transport
from forge.adapters.registry import register_adapter, reset_adapters
from forge.demo_agents.app import app as demo_app
from forge.domain.enums import (
    AdapterKind,
    JobKind,
    JobStatus,
    ProviderKind,
    RunStatus,
    TraceEventSource,
    TraceEventType,
)
from forge.domain.traces.protocol import invocation_span_id
from forge.domain.types import AgentResult, TokenUsage
from forge.infra.db import get_sessionmaker, utcnow
from forge.infra.models import EvaluationRun, ExecutionTrace, Job, ModelConfiguration, TraceEvent
from forge.services import trace_ingest
from forge.services.credentials import create_credential
from forge.services.execution import execute_run_job, invoke_adhoc
from forge.workers.worker import Worker
from tests.factories import create_agent_version, create_run, create_scenario_version

@pytest.fixture(scope="module", autouse=True)
async def custom_plans(app) -> None:
    """Work around a foundation bug (reported): ``enqueue_job(dedupe_key=…)`` uses ``ON CONFLICT … WHERE``
    with bound parameters, which Postgres can no longer match to the partial unique index once the
    prepared statement switches to a generic plan (6th execution on a connection)."""
    await force_custom_plans()


async def force_custom_plans() -> None:
    import asyncpg

    from forge.infra.db import dispose_engine
    from tests.conftest import PG_SERVER_URL, TEST_DATABASE

    conn = await asyncpg.connect(f"{PG_SERVER_URL}/{TEST_DATABASE}")
    try:
        await conn.execute(f'ALTER DATABASE "{TEST_DATABASE}" SET plan_cache_mode = force_custom_plan')
    finally:
        await conn.close()
    await dispose_engine()


DOCS = [
    {
        "id": "d1",
        "title": "Entretiens",
        "content": "Les clients demandent un export CSV planifié chaque semaine.",
    }
]


async def run_execution_jobs() -> int:
    return await Worker(queues=["execution"], concurrency=1, worker_id="test-exec").run_until_idle()


async def start_run(session, *, script: dict[str, Any] | None = None, **agent_kwargs: Any) -> EvaluationRun:
    context_config = agent_kwargs.pop("context_config", None)
    model_configuration_id = agent_kwargs.pop("model_configuration_id", None)
    credential_id = agent_kwargs.pop("credential_id", None)
    if script is not None:
        agent_kwargs["adapter_config"] = {"script": script}
    av = await create_agent_version(session, **agent_kwargs)
    if context_config is not None:
        av.context_config = context_config
    av.model_configuration_id = model_configuration_id
    av.credential_id = credential_id
    sv = await create_scenario_version(session, context={"documents": DOCS})
    run = await create_run(session, sv, av, enqueue=True)
    await session.commit()
    return run


async def reload(
    session, run: EvaluationRun
) -> tuple[EvaluationRun, ExecutionTrace | None, list[TraceEvent]]:
    run_id = inspect(run).identity[0]  # never triggers a (sync) refresh of an expired instance
    await session.commit()
    session.expire_all()
    fresh = await session.get(EvaluationRun, run_id)
    trace = await session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run_id))
    events = list(
        await session.scalars(select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.seq))
    )
    return fresh, trace, events


async def test_mock_run_is_executed_traced_and_handed_to_evaluation(db_session) -> None:
    script = {
        "output": "PRD pour {{input.prompt}}",
        "events": [
            {"type": "llm_call", "name": "Génération", "duration_ms": 20,
             "attributes": {"model": "mock-1", "input_tokens": 1200, "output_tokens": 300, "cost": 0.004}},
            {"type": "tool_call", "name": "jira.search", "input": {"query": "export"}},
        ],
    }  # fmt: skip
    run = await start_run(db_session, script=script)
    assert await run_execution_jobs() == 1
    run, trace, events = await reload(db_session, run)
    assert run.status == RunStatus.evaluating and run.error is None and run.started_at and run.executed_at
    assert trace.output_text.startswith("PRD pour Rédige un PRD")
    assert (trace.input_tokens, trace.output_tokens, trace.total_tokens) == (1200, 300, 1500)
    assert trace.estimated_cost == pytest.approx(0.004) and trace.metadata_["cost_source"] == "agent"
    assert trace.tool_calls == 1 and trace.model_calls == 1 and trace.event_count == len(events)
    assert trace.input["context"]["documents"] == DOCS and "expected_output" not in trace.input
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    types = [e.type for e in events]
    assert types[:2] == [TraceEventType.run_started, TraceEventType.context_prepared]
    assert types[-2:] == [TraceEventType.final_answer, TraceEventType.run_completed]
    assert events[1].attributes["context_source"] == "scenario" and events[1].attributes["documents"] == [
        "d1"
    ]
    assert all(e.offset_ms >= 0 for e in events) and events[0].source == TraceEventSource.runner
    jobs = {(j.kind, j.status) for j in await db_session.scalars(select(Job).where(Job.run_id == run.id))}
    assert (JobKind.evaluate_run, JobStatus.queued) in jobs and (
        JobKind.execute_run,
        JobStatus.succeeded,
    ) in jobs


async def test_estimated_cost_uses_model_pricing(db_session) -> None:
    mc = ModelConfiguration(name="tarif", provider="mock", model="mock-1", input_cost_per_mtok=2.0,
                            output_cost_per_mtok=10.0, content_hash=f"sha256:{uuid.uuid4().hex}")  # fmt: skip
    db_session.add(mc)
    await db_session.flush()
    run = await start_run(db_session, script={"output": "ok", "usage": {"input_tokens": 500_000, "output_tokens": 100_000},
                                              "cost": 99.0}, model_configuration_id=mc.id)  # fmt: skip
    await run_execution_jobs()
    _, trace, _ = await reload(db_session, run)
    assert trace.estimated_cost == pytest.approx(2.0) and trace.metadata_["cost_source"] == "pricing"


async def test_permanent_failure_keeps_partial_trace_and_is_still_evaluated(db_session) -> None:
    script = {"events": [{"type": "reasoning", "name": "Analyse", "output": "début"}],
              "error": {"message": "Agent en panne", "error_type": "EXECUTION_ERROR"}}  # fmt: skip
    run = await start_run(db_session, script=script)
    await run_execution_jobs()
    run, trace, events = await reload(db_session, run)
    assert (
        run.status == RunStatus.evaluating
        and run.error_type == "EXECUTION_ERROR"
        and "Agent en panne" in run.error
    )
    assert trace.output_text is None and trace.errors[0]["type"] == "EXECUTION_ERROR"
    assert [e.type for e in events][-3:] == [
        TraceEventType.reasoning,
        TraceEventType.error,
        TraceEventType.run_completed,
    ]


async def test_retryable_failure_requeues_then_succeeds(db_session) -> None:
    run = await start_run(db_session, script={"output": "ok", "fail_on_attempts": [1]})
    await run_execution_jobs()
    run_row, trace, events = await reload(db_session, run)
    job = await db_session.scalar(select(Job).where(Job.run_id == run.id, Job.kind == JobKind.execute_run))
    assert job.status == JobStatus.queued and job.attempts == 1 and "transitoire" in job.error
    assert run_row.status == RunStatus.running and trace is None and events == []
    await db_session.execute(update(Job).where(Job.id == job.id).values(run_after=utcnow()))
    await db_session.commit()
    await run_execution_jobs()
    run_row, trace, events = await reload(db_session, run)
    assert run_row.status == RunStatus.evaluating and trace.output_text == "ok"
    assert events[0].attributes["attempt"] == 2


async def test_retryable_failure_on_last_attempt_becomes_final(db_session) -> None:
    run = await start_run(db_session, script={"error": {"message": "quota", "retryable": True}})
    await db_session.execute(update(Job).where(Job.run_id == run.id).values(attempts=2))
    await db_session.commit()
    await run_execution_jobs()
    run_row, trace, _ = await reload(db_session, run)
    assert run_row.status == RunStatus.evaluating and "quota" in run_row.error and trace is not None


async def test_timeout_and_budget_exceeded(db_session) -> None:
    slow = await start_run(db_session, script={"output": "trop tard", "latency_ms": 3000},
                           budget={"timeout_seconds": 0.2})  # fmt: skip
    greedy = await start_run(db_session, script={"output": "x", "usage": {"input_tokens": 900, "output_tokens": 200}},
                             budget={"max_tokens": 1000})  # fmt: skip
    await run_execution_jobs()
    slow_run, slow_trace, _ = await reload(db_session, slow)
    assert slow_run.error_type == "TIMEOUT" and "délai" in slow_run.error and slow_trace.output_text is None
    greedy_run, _, _ = await reload(db_session, greedy)
    assert greedy_run.error_type == "BUDGET_EXCEEDED" and greedy_run.status == RunStatus.evaluating


async def test_cancelled_run_is_not_executed(db_session) -> None:
    run = await start_run(db_session, script={"output": "ok"})
    job = await db_session.scalar(select(Job).where(Job.run_id == run.id))
    run.status = RunStatus.cancelled
    await db_session.commit()
    await execute_run_job(db_session, job)
    run_row, trace, _ = await reload(db_session, run)
    assert run_row.status == RunStatus.cancelled and trace is None


async def test_custom_api_against_demo_agents(db_session) -> None:
    run = await start_run(
        db_session,
        adapter_kind=AdapterKind.custom_api,
        endpoint="http://demo-agents.invalid/agents/product-agent/1.3/invoke",
        adapter_config={"parameters": {"latency_scale": 0}},
    )
    with use_transport(httpx.ASGITransport(app=demo_app)):
        await run_execution_jobs()
    run_row, trace, events = await reload(db_session, run)
    assert run_row.status == RunStatus.evaluating, run_row.error
    assert trace.output_text.startswith("# PRD") and "[d1]" in trace.output_text
    assert trace.total_tokens > 0 and trace.estimated_cost > 0 and trace.metadata_["cost_source"] == "agent"
    agent_events = [e for e in events if e.source == TraceEventSource.adapter]
    assert {TraceEventType.reasoning, TraceEventType.retrieval, TraceEventType.llm_call} <= {
        e.type for e in agent_events
    }
    assert trace.metadata_["agent"]["agent"] == "product-agent"


async def test_events_pushed_during_the_call_are_merged_then_late_ones_appended(db_session) -> None:
    class PushingAdapter:
        kind = AdapterKind.mock

        async def invoke(self, request, recorder) -> AgentResult:
            span_root = invocation_span_id(request.run_id, 1)
            now_ns = int(utcnow().timestamp() * 1e9)
            export = otlp_export(request.otel_trace_id, [
                ("aa" * 8, span_root, "invoke_agent", {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "crew"}, now_ns, 50),
                ("bb" * 8, "aa" * 8, "chat", {"gen_ai.operation.name": "chat", "gen_ai.usage.input_tokens": 70,
                                              "gen_ai.usage.output_tokens": 30}, now_ns + 5_000_000, 20),
            ])  # fmt: skip
            async with get_sessionmaker()() as other:
                await trace_ingest.ingest_otlp(other, export)
                await other.commit()
            return AgentResult(output_text="réponse")

    register_adapter(PushingAdapter())
    try:
        run = await start_run(db_session, script={})
        await run_execution_jobs()
    finally:
        reset_adapters()
    run_row, trace, events = await reload(db_session, run)
    assert run_row.status == RunStatus.evaluating and trace.metadata_["pushed_events"] == 2
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    by_span = {e.span_id: e for e in events if e.span_id}
    assert by_span["bb" * 8].parent_id == by_span["aa" * 8].id
    assert by_span["aa" * 8].type == TraceEventType.custom  # root agent span (parent = FORGE invocation)
    assert trace.total_tokens == 100 and trace.model_calls == 1  # usage taken from the pushed spans
    late = otlp_export(run_row.otel_trace_id, [("cc" * 8, "aa" * 8, "late", {"forge.event.type": "message"},
                                                int(utcnow().timestamp() * 1e9), 1)])  # fmt: skip
    result = await trace_ingest.ingest_otlp(db_session, late)
    await db_session.commit()
    assert result.attached == 1 and result.first_seq == len(events) + 1
    duplicate = await trace_ingest.ingest_otlp(db_session, late)
    assert duplicate.attached == 0 and duplicate.duplicates == 1
    _, trace, events = await reload(db_session, run)
    assert events[-1].parent_id == by_span["aa" * 8].id and trace.event_count == len(events)


def otlp_export(trace_id: str, spans: list[tuple]) -> dict[str, Any]:
    def attr(key: str, value: Any) -> dict[str, Any]:
        if isinstance(value, int):
            return {"key": key, "value": {"intValue": str(value)}}
        return {"key": key, "value": {"stringValue": str(value)}}

    return {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": trace_id, "spanId": span_id, "parentSpanId": parent, "name": name,
         "startTimeUnixNano": str(start), "endTimeUnixNano": str(start + duration_ms * 1_000_000),
         "attributes": [attr(k, v) for k, v in attrs.items()]}
        for span_id, parent, name, attrs, start, duration_ms in spans
    ]}]}]}  # fmt: skip


# --- Context providers --------------------------------------------------------------------------------


async def orbit_credential(session) -> uuid.UUID:
    credential = await create_credential(session, name=f"orbit-{uuid.uuid4().hex[:6]}", kind=ProviderKind.orbit,
                                         secret="orbit-agent-key-123", base_url="https://orbit.example")  # fmt: skip
    return credential.id


@respx.mock
async def test_orbit_snapshot_context_is_resolved_and_recorded(db_session) -> None:
    route = respx.get("https://orbit.example/api/v1/projects/acme/snapshots/discovery/latest").mock(
        return_value=httpx.Response(200, json={"version": 7, "content_hash": "sha256:abc",
                                               "documents": [{"id": "orbit-1", "title": "Note ORBIT", "content": "Contexte."}]})
    )  # fmt: skip
    credential_id = await orbit_credential(db_session)
    config = {
        "source": "orbit_snapshot",
        "orbit": {"project": "acme", "snapshot": "discovery", "credential_id": str(credential_id)},
    }
    run = await start_run(db_session, script={"output": "ok"}, context_config=config, credential_id=None)
    await run_execution_jobs()
    run_row, trace, events = await reload(db_session, run)
    assert route.calls.last.request.headers["authorization"] == "Bearer orbit-agent-key-123"
    assert run_row.status == RunStatus.evaluating and run_row.error is None
    assert [d["id"] for d in trace.input["context"]["documents"]] == ["d1", "orbit-1"]
    assert (
        trace.metadata_["context"]["snapshot_version"] == "7"
        and trace.metadata_["context_source"] == "orbit_snapshot"
    )
    prepared = next(e for e in events if e.type == TraceEventType.context_prepared)
    assert (
        prepared.attributes["snapshot_hash"] == "sha256:abc" and prepared.attributes["documents_count"] == 2
    )


@respx.mock
async def test_orbit_live_records_request_id(db_session) -> None:
    route = respx.post("https://orbit.example/api/v1/projects/acme/context").mock(
        return_value=httpx.Response(
            200, json={"request_id": "req-42", "items": [{"id": "m1", "content": "Mémoire"}]}
        )
    )
    config = {"source": "orbit_live", "orbit": {"project": "acme", "credential_id": str(await orbit_credential(db_session)),
                                                "merge": False}}  # fmt: skip
    run = await start_run(db_session, script={"output": "ok"}, context_config=config)
    await run_execution_jobs()
    _, trace, _ = await reload(db_session, run)
    import json

    assert json.loads(route.calls.last.request.content)["task"].startswith("Rédige un PRD")
    assert trace.metadata_["context"]["orbit_request_id"] == "req-42"
    assert [d["id"] for d in trace.input["context"]["documents"]] == ["m1"]


@respx.mock
async def test_orbit_failure_fails_run_unless_optional(db_session) -> None:
    respx.get(url__regex=r"https://orbit\.example/.*").mock(
        return_value=httpx.Response(404, json={"detail": "absent"})
    )
    base = {"project": "acme", "snapshot": "x", "credential_id": str(await orbit_credential(db_session))}
    strict = await start_run(
        db_session, script={"output": "ok"}, context_config={"source": "orbit_snapshot", "orbit": base}
    )
    lenient = await start_run(db_session, script={"output": "ok"},
                              context_config={"source": "orbit_snapshot", "orbit": {**base, "optional": True}})  # fmt: skip
    await run_execution_jobs()
    strict_run, strict_trace, _ = await reload(db_session, strict)
    assert "Préparation du contexte ORBIT impossible" in strict_run.error and strict_trace.output_text is None
    lenient_run, lenient_trace, _ = await reload(db_session, lenient)
    assert lenient_run.error is None and lenient_trace.output_text == "ok"
    assert lenient_trace.metadata_["warnings"] and lenient_trace.metadata_["context_source"] == "scenario"


async def test_invoke_adhoc(db_session) -> None:
    av = await create_agent_version(db_session, adapter_config={"script": {"output": "Bonjour {{input.prompt}}",
                                                                           "usage": {"input_tokens": 5, "output_tokens": 2}}})  # fmt: skip
    await db_session.commit()
    result = await invoke_adhoc(db_session, av, input={"prompt": "test"}, context={"documents": DOCS})
    data = result.to_dict()
    assert data["status"] == "succeeded" and data["output_text"] == "Bonjour test"
    assert data["token_usage"]["total_tokens"] == 7 and "result" not in data
    assert [e["type"] for e in data["events"]][0] == "run_started" and data["events"][-1][
        "type"
    ] == "run_completed"
    failing = await create_agent_version(db_session, adapter_config={"script": {"error": {"message": "non"}}})
    failed = await invoke_adhoc(db_session, failing, input={"prompt": "x"})
    assert failed.status == "failed" and "non" in failed.error and failed.output_text is None
    assert isinstance(TokenUsage(), TokenUsage)

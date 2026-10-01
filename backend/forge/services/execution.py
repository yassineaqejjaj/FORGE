"""Agent Runner (file ``execution``) — docs/ARCHITECTURE.md §8.

:func:`execute_run_job` executes one run from its frozen manifest:

1. load the run (nothing to do when it is no longer pending/running), ``runs.mark_running``;
2. specs from the manifest, secrets injected from ``agent.credential_id``;
3. context preparation (``context_providers``) → ``context_prepared`` event;
4. ``cache.concurrency_slot`` per agent version, timeout ``budget.timeout_seconds``, budget checked
   by the recorder;
5. ``traceparent`` / ``X-Forge-*`` headers propagated, ``adapter.invoke(request, recorder)``;
6. grace period for late OTLP spans, then ``ExecutionTrace`` + ``TraceEvent`` persisted (events
   already pushed by the agent during the call are merged and renumbered);
7. ``runs.mark_evaluating``. A non-retryable failure is persisted (partial trace, ``run.error``) and
   still evaluated; a retryable one raises ``RetryableJobError`` while attempts remain.

:func:`invoke_adhoc` runs an agent version outside any run (``POST /agent-versions/{id}/test``).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.adapters.base import (
    HEADER_ATTEMPT,
    HEADER_REPETITION,
    HEADER_RUN_ID,
    HEADER_SCENARIO_VERSION,
    HEADER_TRACEPARENT,
)
from forge.adapters.registry import UnknownAdapterError, get_adapter
from forge.config import settings
from forge.domain.enums import (
    AdapterKind,
    BuiltinErrorType,
    Difficulty,
    EventStatus,
    RunStatus,
    ScenarioVisibility,
    TraceEventSource,
    TraceEventType,
)
from forge.domain.traces.costs import resolve_cost
from forge.domain.traces.normalize import PlannedEvent, plan_events, truncate_payload, truncate_text
from forge.domain.traces.protocol import invocation_span_id, usage_from_events
from forge.domain.traces.recorder import InMemoryTraceRecorder
from forge.domain.types import (
    AgentExecutionError,
    AgentRequest,
    AgentResult,
    AgentSpec,
    ScenarioSpec,
    TokenUsage,
    TraceEventData,
    to_dict,
)
from forge.infra import cache
from forge.infra.db import utcnow
from forge.infra.models import AgentVersion, EvaluationRun, ExecutionTrace, Job, TraceEvent
from forge.infra.observability.metrics import RUN_EXECUTION_SECONDS
from forge.infra.observability.tracing import get_tracer
from forge.infra.queue import RetryableJobError
from forge.infra.security import SecretDecryptionError
from forge.services import runs as run_service
from forge.services.context_providers import ContextPreparationError, PreparedContext, prepare_context
from forge.services.credentials import resolve_credentials
from forge.services.mapping import load_agent_spec, specs_from_manifest

logger = logging.getLogger("forge.runner")

#: Adapters calling remote agents that may push OTLP spans: the runner waits for late spans.
_REMOTE_ADAPTERS = frozenset({AdapterKind.custom_api, AdapterKind.nova})
_ACTIVE_STATUSES = frozenset({RunStatus.pending, RunStatus.running})


@dataclass(slots=True)
class ExecutionOutcome:
    """What happened during one agent call (success or captured failure)."""

    recorder: InMemoryTraceRecorder
    started_at: datetime
    result: AgentResult | None = None
    error: AgentExecutionError | None = None
    prepared: PreparedContext | None = None
    finished_at: datetime | None = None
    context_ms: float = 0.0
    invocation_ms: float = 0.0
    queue_wait_ms: float = 0.0
    span_id: str = ""
    retry_after: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def latency_ms(self) -> float:
        return round(self.context_ms + self.invocation_ms, 3)


@dataclass(slots=True)
class TraceTotals:
    usage: TokenUsage
    model_calls: int
    tool_calls: int
    cost: float | None
    cost_source: str | None


# =====================================================================================================
# Shared pipeline
# =====================================================================================================


def trace_headers(
    *, run_id: str, trace_id: str, span_id: str, scenario_version_id: str, repetition: int, attempt: int
) -> dict[str, str]:
    return {
        HEADER_TRACEPARENT: f"00-{trace_id}-{span_id}-01",
        HEADER_RUN_ID: run_id,
        HEADER_SCENARIO_VERSION: scenario_version_id,
        HEADER_REPETITION: str(repetition),
        HEADER_ATTEMPT: str(attempt),
    }


def timeout_seconds(agent: AgentSpec) -> float:
    configured = agent.budget.timeout_seconds
    return float(configured) if configured and configured > 0 else settings.runner_default_timeout_seconds


async def run_agent(
    session: AsyncSession,
    scenario: ScenarioSpec,
    agent: AgentSpec,
    *,
    run_id: str,
    trace_id: str,
    repetition: int = 0,
    attempt: int = 1,
    base_context: dict[str, Any] | None = None,
) -> ExecutionOutcome:
    """Steps 2–5 of §8: secrets, context, limits, timeout, adapter call. Never raises for agent failures."""
    recorder = InMemoryTraceRecorder(budget=agent.budget, model=agent.model, source=TraceEventSource.adapter)
    outcome = ExecutionOutcome(
        recorder=recorder, started_at=recorder.clock(), span_id=invocation_span_id(run_id, attempt)
    )
    recorder.event(
        TraceEventType.run_started,
        "Démarrage du run",
        source=TraceEventSource.runner,
        attributes={
            "agent": agent.label,
            "adapter": agent.adapter_kind.value,
            "scenario_version_id": scenario.scenario_version_id,
            "repetition": repetition,
            "attempt": attempt,
        },
    )
    try:
        agent.credentials = await resolve_credentials(session, agent.credential_id)
        await _prepare(session, scenario, agent, outcome, run_id=run_id, base_context=base_context)
        await _invoke(scenario, agent, outcome, run_id=run_id, trace_id=trace_id, repetition=repetition,
                      attempt=attempt)  # fmt: skip
    except AgentExecutionError as exc:
        outcome.error = exc
    except SecretDecryptionError as exc:
        outcome.error = AgentExecutionError(f"Identifiants de l'agent illisibles : {exc}")
    finally:
        agent.credentials = {}
    outcome.finished_at = recorder.clock()
    return outcome


async def _prepare(
    session: AsyncSession,
    scenario: ScenarioSpec,
    agent: AgentSpec,
    outcome: ExecutionOutcome,
    *,
    run_id: str,
    base_context: dict[str, Any] | None,
) -> None:
    recorder = outcome.recorder
    started = time.perf_counter()
    try:
        with recorder.span(
            TraceEventType.context_prepared, "Préparation du contexte", source=TraceEventSource.runner
        ) as handle:
            prepared = await prepare_context(
                session, scenario, agent, run_id=run_id, base_context=base_context
            )
            handle.set_attributes(
                context_source=prepared.source.value,
                documents_count=prepared.documents_count,
                documents=[
                    str(d.get("id")) for d in prepared.context.get("documents") or [] if isinstance(d, dict)
                ],
                **{k: v for k, v in prepared.metadata.items() if v is not None},
            )
            if prepared.warnings:
                handle.set_attributes(warnings=prepared.warnings)
    except ContextPreparationError as exc:
        raise AgentExecutionError(str(exc), retryable=exc.retryable) from exc
    finally:
        outcome.context_ms = (time.perf_counter() - started) * 1000
    outcome.prepared = prepared
    outcome.warnings += prepared.warnings


async def _invoke(
    scenario: ScenarioSpec,
    agent: AgentSpec,
    outcome: ExecutionOutcome,
    *,
    run_id: str,
    trace_id: str,
    repetition: int,
    attempt: int,
) -> None:
    assert outcome.prepared is not None
    try:
        adapter = get_adapter(agent.adapter_kind)
    except UnknownAdapterError as exc:
        raise AgentExecutionError(str(exc)) from exc
    request = AgentRequest(
        run_id=run_id,
        scenario=scenario,
        agent=agent,
        context=outcome.prepared.context,
        trace_headers=trace_headers(
            run_id=run_id,
            trace_id=trace_id,
            span_id=outcome.span_id,
            scenario_version_id=scenario.scenario_version_id,
            repetition=repetition,
            attempt=attempt,
        ),
        otel_trace_id=trace_id,
    )
    limit = agent.max_concurrency or settings.runner_default_concurrency
    waited = time.perf_counter()
    try:
        async with cache.concurrency_slot(f"agent:{agent.agent_version_id}", limit):
            outcome.queue_wait_ms = (time.perf_counter() - waited) * 1000
            await _call_adapter(adapter, request, agent, outcome)
    except cache.RateLimitExceeded as exc:
        outcome.retry_after = exc.retry_after
        raise AgentExecutionError(
            f"Concurrence maximale atteinte pour l'agent ({limit} appels simultanés)", retryable=True
        ) from exc


async def _call_adapter(
    adapter: Any, request: AgentRequest, agent: AgentSpec, outcome: ExecutionOutcome
) -> None:
    recorder = outcome.recorder
    timeout = timeout_seconds(agent)
    started = time.perf_counter()
    tracer = get_tracer("forge.runner")
    with tracer.start_as_current_span("agent.invoke") as span:
        span.set_attribute("forge.run_id", request.run_id)
        span.set_attribute("forge.adapter", agent.adapter_kind.value)
        try:
            outcome.result = await asyncio.wait_for(adapter.invoke(request, recorder), timeout=timeout)
        except TimeoutError as exc:
            message = f"L'agent n'a pas répondu dans le délai imparti ({timeout:g} s)"
            recorder.close_open_spans(message, error_type=BuiltinErrorType.TIMEOUT)
            raise AgentExecutionError(message, error_type=BuiltinErrorType.TIMEOUT) from exc
        except AgentExecutionError:
            raise
        except Exception as exc:
            logger.exception("Unexpected adapter failure (%s, run %s)", agent.adapter_kind, request.run_id)
            raise AgentExecutionError(f"Erreur inattendue de l'adapter {agent.adapter_kind.value} "
                                      f"({type(exc).__name__})") from exc  # fmt: skip
        finally:
            outcome.invocation_ms = (time.perf_counter() - started) * 1000
            RUN_EXECUTION_SECONDS.labels(adapter=agent.adapter_kind.value).observe(
                outcome.invocation_ms / 1000
            )


def record_conclusion(outcome: ExecutionOutcome, totals: TraceTotals) -> None:
    """``final_answer`` (or ``error``) and ``run_completed`` events recorded by the runner."""
    recorder = outcome.recorder
    if outcome.result is not None and outcome.error is None:
        recorder.event(
            TraceEventType.final_answer,
            "Réponse finale",
            output=outcome.result.output_text,
            attributes={"has_json": outcome.result.output_json is not None},
            source=TraceEventSource.runner,
        )
    if outcome.error is not None:
        recorder.event(
            TraceEventType.error,
            "Échec de l'exécution",
            output=str(outcome.error),
            status=EventStatus.error,
            attributes={"error": str(outcome.error), "error_type": outcome.error.error_type,
                        "retryable": outcome.error.retryable},
            source=TraceEventSource.runner,
        )  # fmt: skip
    recorder.event(
        TraceEventType.run_completed,
        "Fin du run",
        status=EventStatus.error if outcome.error else EventStatus.ok,
        attributes={
            "total_tokens": totals.usage.total_tokens,
            "cost": totals.cost,
            "latency_ms": outcome.latency_ms,
            "model_calls": totals.model_calls,
            "tool_calls": totals.tool_calls,
        },
        source=TraceEventSource.runner,
    )


def compute_totals(outcome: ExecutionOutcome, agent: AgentSpec, extra: list[TraceEventData]) -> TraceTotals:
    """Tokens / calls / cost: adapter result, else recorder counters, else pushed (OTLP/API) events."""
    result, recorder = outcome.result, outcome.recorder
    pushed_usage, pushed_calls, pushed_cost = usage_from_events(extra)
    usage = result.token_usage if result and result.token_usage.total_tokens else recorder.usage
    if usage.total_tokens == 0:
        usage = pushed_usage
    model_calls = (result.model_calls if result else 0) or recorder.model_calls or pushed_calls
    tool_calls = (
        (result.tool_calls if result else 0)
        or recorder.tool_calls
        or sum(1 for e in extra if e.type == TraceEventType.tool_call)
    )
    reported = result.estimated_cost if result and result.estimated_cost is not None else recorder.cost
    if reported is None:
        reported = pushed_cost
    cost, source = resolve_cost(agent.model, usage, reported)
    return TraceTotals(
        TokenUsage(usage.input_tokens, usage.output_tokens), model_calls, tool_calls, cost, source
    )


# =====================================================================================================
# Run job
# =====================================================================================================


async def execute_run_job(session: AsyncSession, job: Job) -> None:
    """Handler of ``execute_run`` jobs (see module docstring)."""
    if job.run_id is None:
        return
    run = await session.get(EvaluationRun, job.run_id, populate_existing=True)
    if run is None or run.status not in _ACTIVE_STATUSES:
        return
    attempt = int(job.attempts or 1)
    await run_service.mark_running(
        session, run, f"Exécution en cours (tentative {attempt}/{job.max_attempts})"
    )
    await _discard_previous_attempt(session, run)
    await session.commit()

    specs = specs_from_manifest(run.manifest)
    scenario, agent = specs.scenario, specs.agent
    if await run_service.is_cancelled(session, run.id):
        return
    outcome = await run_agent(
        session, scenario, agent, run_id=str(run.id), trace_id=run.otel_trace_id,
        repetition=run.repetition, attempt=attempt,
    )  # fmt: skip
    error = outcome.error
    if error is not None and error.retryable and job.attempts < job.max_attempts:
        run.status_detail = f"Nouvel essai prévu après un échec transitoire : {error}"[:1000]
        await session.commit()
        logger.warning("Run %s attempt %d failed (retryable): %s", run.id, attempt, error)
        raise RetryableJobError(str(error), delay_seconds=outcome.retry_after)
    if error is None and _expects_late_spans(agent) and settings.trace_grace_seconds > 0:
        await asyncio.sleep(settings.trace_grace_seconds)
    await _finish(session, run, scenario, agent, outcome)


def _expects_late_spans(agent: AgentSpec) -> bool:
    return agent.adapter_kind in _REMOTE_ADAPTERS or bool(agent.adapter_config.get("otlp"))


async def _discard_previous_attempt(session: AsyncSession, run: EvaluationRun) -> None:
    """Events pushed during a failed previous attempt (no trace persisted yet) must not leak into this one."""
    persisted = await session.scalar(select(ExecutionTrace.id).where(ExecutionTrace.run_id == run.id))
    if persisted is None:
        await session.execute(delete(TraceEvent).where(TraceEvent.run_id == run.id))


async def _finish(
    session: AsyncSession,
    run: EvaluationRun,
    scenario: ScenarioSpec,
    agent: AgentSpec,
    outcome: ExecutionOutcome,
) -> None:
    # Serialise with trace ingestion (same row lock) and observe a concurrent cancellation.
    await session.execute(select(EvaluationRun.id).where(EvaluationRun.id == run.id).with_for_update())
    await session.refresh(run)
    await persist_trace(session, run, scenario, agent, outcome)
    if run.status == RunStatus.cancelled:
        await session.commit()
        logger.info("Run %s cancelled during execution: trace kept, not evaluated", run.id)
        return
    if outcome.error is not None:
        run.error = str(outcome.error)[:4000]
        run.error_type = outcome.error.error_type
        logger.info("Run %s execution failed (%s): %s", run.id, outcome.error.error_type, outcome.error)
    else:
        run.error = None
        run.error_type = None
    await run_service.mark_evaluating(session, run)
    await session.commit()


async def persist_trace(
    session: AsyncSession,
    run: EvaluationRun,
    scenario: ScenarioSpec,
    agent: AgentSpec,
    outcome: ExecutionOutcome,
) -> ExecutionTrace:
    """Merge recorder events with events pushed during the call, renumber and store the trace."""
    staged = list(
        await session.scalars(select(TraceEvent).where(TraceEvent.run_id == run.id).order_by(TraceEvent.seq))
    )
    pushed = [_row_to_data(row) for row in staged]
    totals = compute_totals(outcome, agent, pushed)
    record_conclusion(outcome, totals)
    planned = plan_events(
        list(outcome.recorder.events) + pushed,
        origin=outcome.started_at,
        max_payload_chars=settings.max_event_payload_chars,
    )
    if staged:
        await session.execute(delete(TraceEvent).where(TraceEvent.run_id == run.id))
    await _insert_events(session, run.id, planned)
    trace = await session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run.id))
    if trace is None:
        trace = ExecutionTrace(run_id=run.id, started_at=outcome.started_at)
        session.add(trace)
    _fill_trace(trace, scenario, outcome, totals, event_count=len(planned), pushed=len(pushed))
    await session.flush()
    return trace


def _row_to_data(row: TraceEvent) -> TraceEventData:
    return TraceEventData(
        type=row.type,
        name=row.name,
        started_at=row.started_at,
        ended_at=row.ended_at,
        key=f"db:{row.id}",
        status=row.status,
        parent_key=f"db:{row.parent_id}" if row.parent_id else None,
        input=row.input,
        output=row.output,
        attributes=dict(row.attributes or {}),
        source=row.source,
        span_id=row.span_id,
        parent_span_id=row.parent_span_id,
    )


async def _insert_events(
    session: AsyncSession, run_id: uuid.UUID, planned: list[PlannedEvent]
) -> list[TraceEvent]:
    """Insert rows, then link parents (two flushes: parents may sort after their children)."""
    rows = [
        TraceEvent(
            id=uuid.uuid4(),
            run_id=run_id,
            seq=p.seq,
            type=p.type,
            name=p.name,
            source=p.source,
            status=p.status,
            started_at=p.started_at,
            ended_at=p.ended_at,
            offset_ms=p.offset_ms,
            duration_ms=p.duration_ms,
            input=p.input,
            output=p.output,
            attributes=p.attributes,
            span_id=p.span_id,
            parent_span_id=p.parent_span_id,
        )
        for p in planned
    ]
    session.add_all(rows)
    await session.flush()
    linked = False
    for row, plan in zip(rows, planned, strict=True):
        if plan.parent_index is not None:
            row.parent_id = rows[plan.parent_index].id
            linked = True
    if linked:
        await session.flush()
    return rows


def _fill_trace(
    trace: ExecutionTrace,
    scenario: ScenarioSpec,
    outcome: ExecutionOutcome,
    totals: TraceTotals,
    *,
    event_count: int,
    pushed: int,
) -> None:
    result = outcome.result if outcome.error is None else None
    view = scenario.agent_view()
    if outcome.prepared is not None:
        view["context"] = outcome.prepared.context
    trace.started_at = outcome.started_at
    trace.completed_at = outcome.finished_at
    trace.total_latency_ms = outcome.latency_ms
    trace.input = truncate_payload(view, settings.max_output_chars)
    trace.output_text = truncate_text(result.output_text, settings.max_output_chars) if result else None
    trace.output_json = truncate_payload(result.output_json, settings.max_output_chars) if result else None
    trace.messages = truncate_payload(list(result.messages), settings.max_output_chars) if result else []
    trace.input_tokens = totals.usage.input_tokens
    trace.output_tokens = totals.usage.output_tokens
    trace.total_tokens = totals.usage.total_tokens
    trace.estimated_cost = totals.cost
    trace.model_calls = totals.model_calls
    trace.tool_calls = totals.tool_calls
    trace.event_count = event_count
    trace.errors = (
        [{"type": outcome.error.error_type, "message": str(outcome.error), "at": utcnow().isoformat()}]
        if outcome.error
        else []
    )
    trace.metadata_ = _trace_metadata(outcome, totals, pushed)


def _trace_metadata(outcome: ExecutionOutcome, totals: TraceTotals, pushed: int) -> dict[str, Any]:
    prepared = outcome.prepared
    metadata: dict[str, Any] = {
        "context_source": prepared.source.value if prepared else None,
        "context": {k: v for k, v in (prepared.metadata if prepared else {}).items() if v is not None},
        "traceparent_span_id": outcome.span_id,
        "context_ms": round(outcome.context_ms, 3),
        "invocation_ms": round(outcome.invocation_ms, 3),
        "queue_wait_ms": round(outcome.queue_wait_ms, 3),
        "cost_source": totals.cost_source,
        "pushed_events": pushed,
        "warnings": outcome.warnings,
    }
    if outcome.result is not None:
        metadata["agent"] = truncate_payload(
            to_dict(outcome.result.metadata), settings.max_event_payload_chars
        )
    return metadata


# =====================================================================================================
# Ad-hoc invocation (POST /agent-versions/{id}/test)
# =====================================================================================================


@dataclass(slots=True)
class AdhocInvocation:
    """Result of an ad-hoc call: nothing is persisted. ``to_dict()`` is JSON-ready."""

    status: str  # "succeeded" | "failed"
    output_text: str | None
    output_json: Any
    token_usage: dict[str, int]
    estimated_cost: float | None
    latency_ms: float
    model_calls: int
    tool_calls: int
    events: list[dict[str, Any]]
    context: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None
    retryable: bool = False
    warnings: list[str] = field(default_factory=list)
    result: AgentResult | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        data = to_dict(self)
        data.pop("result", None)
        return data


def adhoc_scenario(input: dict[str, Any], context: dict[str, Any] | None) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="adhoc",
        scenario_version_id="adhoc",
        slug="adhoc",
        name="Test ad hoc",
        version=0,
        category="adhoc",
        difficulty=Difficulty.medium,
        visibility=ScenarioVisibility.public,
        input=dict(input or {}),
        context=dict(context or {}),
        constraints=[str(c) for c in (input or {}).get("constraints") or []],
    )


async def invoke_adhoc(
    session: AsyncSession,
    agent_version: AgentVersion,
    *,
    input: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> AdhocInvocation:
    """Invoke an agent version on a free input (no run, no persistence, no retry)."""
    agent = await load_agent_spec(session, agent_version)
    scenario = adhoc_scenario(input, context)
    run_id = f"adhoc-{uuid.uuid4()}"
    outcome = await run_agent(session, scenario, agent, run_id=run_id, trace_id=secrets.token_hex(16))
    totals = compute_totals(outcome, agent, [])
    record_conclusion(outcome, totals)
    planned = plan_events(
        list(outcome.recorder.events),
        origin=outcome.started_at,
        max_payload_chars=settings.max_event_payload_chars,
    )
    result = outcome.result if outcome.error is None else None
    return AdhocInvocation(
        status="failed" if outcome.error else "succeeded",
        output_text=truncate_text(result.output_text, settings.max_output_chars) if result else None,
        output_json=result.output_json if result else None,
        token_usage=totals.usage.as_dict(),
        estimated_cost=totals.cost,
        latency_ms=outcome.latency_ms,
        model_calls=totals.model_calls,
        tool_calls=totals.tool_calls,
        events=[_planned_dict(p, planned) for p in planned],
        context=outcome.prepared.metadata | {"source": outcome.prepared.source.value}
        if outcome.prepared
        else {},
        error=str(outcome.error) if outcome.error else None,
        error_type=outcome.error.error_type if outcome.error else None,
        retryable=bool(outcome.error and outcome.error.retryable),
        warnings=list(outcome.warnings),
        result=result,
    )


def _planned_dict(event: PlannedEvent, planned: list[PlannedEvent]) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "parent_seq": planned[event.parent_index].seq if event.parent_index is not None else None,
        "type": event.type.value,
        "name": event.name,
        "source": event.source.value,
        "status": event.status.value,
        "started_at": event.started_at.astimezone(UTC).isoformat(),
        "offset_ms": event.offset_ms,
        "duration_ms": event.duration_ms,
        "input": event.input,
        "output": event.output,
        "attributes": event.attributes,
    }

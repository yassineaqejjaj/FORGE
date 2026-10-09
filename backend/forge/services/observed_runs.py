"""Observed runs: a run executed by an external system, ingested for evaluation only
(``POST /runs/observed``, docs/OBSERVED_RUNS.md).

The run is built exactly like an ad-hoc one (:func:`forge.services.runs.create_runs`: frozen manifest,
current scenario version, agent version, evaluation configuration) with ``origin=observed`` and no
``execute_run`` job. The execution trace is written from what the caller reports (input, outputs,
usage, timestamps) with the same minimal events as a real execution (``run_started``, ``final_answer``
or ``error``, ``run_completed``), then the run moves to ``evaluating`` so the normal ``evaluate_run``
job scores it. A reported failure behaves like a captured execution failure: the run carries
``error`` / ``error_type``, judges are skipped, the composite is forced to 0 and the run ends ``failed``
(the outputs the caller did report are kept on the trace for diagnosis).

Idempotency: ``external_id`` is unique per agent. Replaying a call returns the existing run.
Flushes only: the caller commits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import (
    BuiltinErrorType,
    EventStatus,
    RunOrigin,
    TraceEventSource,
    TraceEventType,
)
from forge.domain.traces.costs import resolve_cost
from forge.domain.traces.normalize import plan_events, truncate_payload, truncate_text
from forge.domain.types import TokenUsage, TraceEventData
from forge.infra.models import AgentVersion, EvaluationRun, ExecutionTrace, Scenario, ScenarioVersion
from forge.services import access, audit, runs
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.execution import insert_events
from forge.services.mapping import specs_from_manifest
from forge.services.run_queries import get_visible_run, resolve_config
from forge.services.taxonomy import InvalidError, NotFoundError

DEFAULT_FAILURE_MESSAGE = "Exécution en échec (rapportée par le système externe)"


@dataclass(slots=True)
class ObservedRunData:
    """Validated payload of ``POST /runs/observed`` (see ``ObservedRunIn``)."""

    agent_version_id: uuid.UUID
    scenario_id: uuid.UUID
    input: dict[str, Any]
    execution_status: str  # "completed" | "failed"
    started_at: datetime
    completed_at: datetime
    external_id: str
    evaluation_config_id: uuid.UUID | None = None
    output_text: str | None = None
    output_json: dict[str, Any] | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tags: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.execution_status == "failed"

    @property
    def latency_ms(self) -> float:
        return round(max(0.0, (self.completed_at - self.started_at).total_seconds() * 1000), 3)


async def find_existing(
    session: AsyncSession, viewer: Viewer, agent_id: uuid.UUID, external_id: str
) -> EvaluationRun | None:
    """Run already ingested under ``(agent, external_id)`` (404 if its scenario is above the clearance)."""
    run_id = await session.scalar(
        select(EvaluationRun.id).where(
            EvaluationRun.agent_id == agent_id, EvaluationRun.external_id == external_id
        )
    )
    if run_id is None:
        return None
    run, _ = await get_visible_run(session, viewer, run_id)
    return run


async def _current_scenario_version(
    session: AsyncSession, viewer: Viewer, scenario_id: uuid.UUID
) -> ScenarioVersion:
    row = (
        await session.execute(
            select(ScenarioVersion)
            .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
            .where(
                Scenario.id == scenario_id,
                ScenarioVersion.version == Scenario.latest_version,
                access.classification_condition(viewer),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Scénario {scenario_id} introuvable")
    return row


async def ingest_observed_run(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    data: ObservedRunData,
    *,
    created_by: uuid.UUID | None = None,
) -> tuple[EvaluationRun, bool]:
    """Create (or find) the observed run. Returns ``(run, created)``."""
    agent_version = await session.get(AgentVersion, data.agent_version_id)
    if agent_version is None:
        raise NotFoundError("Version d'agent introuvable")
    existing = await find_existing(session, viewer, agent_version.agent_id, data.external_id)
    if existing is not None:
        return existing, False
    scenario_version = await _current_scenario_version(session, viewer, data.scenario_id)
    config = await resolve_config(session, data.evaluation_config_id)
    tags = list(dict.fromkeys(t.strip() for t in data.tags if t and t.strip()))
    try:
        # Savepoint: a concurrent call with the same external_id loses the unique index race and
        # must get the winner's run back instead of an error.
        async with session.begin_nested():
            (run,) = await runs.create_runs(
                session,
                [runs.RunPlan(scenario_version_id=scenario_version.id, agent_version_id=agent_version.id)],
                evaluation_config=config,
                origin=RunOrigin.observed,
                created_by=created_by,
                tags=tags,
                enqueue=False,
                external_id=data.external_id,
            )
    except IntegrityError:
        winner = await find_existing(session, viewer, agent_version.agent_id, data.external_id)
        if winner is None:
            raise
        return winner, False
    except runs.RunCreationError as exc:
        message = str(exc)
        if "introuvable" in message:
            raise NotFoundError(message) from exc
        raise InvalidError(message) from exc

    run.started_at = data.started_at
    run.executed_at = data.completed_at
    if data.failed:
        run.error = (data.error or DEFAULT_FAILURE_MESSAGE)[:4000]
        run.error_type = BuiltinErrorType.EXECUTION_ERROR.value
    await _persist_trace(session, run, data)
    await audit.record(
        session,
        actor,
        "run.observe",
        "evaluation_run",
        run.id,
        summary=f"Run observé ingéré ({data.execution_status}) : {data.external_id}",
        details={
            "external_id": data.external_id,
            "agent_version_id": data.agent_version_id,
            "scenario_version_id": scenario_version.id,
            "evaluation_config_id": config.id,
            "execution_status": data.execution_status,
        },
    )
    await runs.mark_evaluating(session, run, enqueue=True)
    return run, True


async def _persist_trace(session: AsyncSession, run: EvaluationRun, data: ObservedRunData) -> ExecutionTrace:
    agent = specs_from_manifest(run.manifest).agent
    usage = TokenUsage(data.input_tokens, data.output_tokens)
    cost, cost_source = resolve_cost(agent.model, usage, None)
    latency_ms = data.latency_ms
    events = [
        TraceEventData(
            type=TraceEventType.run_started,
            name="Démarrage du run (exécuté hors de FORGE)",
            started_at=data.started_at,
            key="run_started",
            source=TraceEventSource.api,
            attributes={"origin": RunOrigin.observed.value, "external_id": data.external_id},
        )
    ]
    if data.failed:
        events.append(
            TraceEventData(
                type=TraceEventType.error,
                name="Échec de l'exécution",
                started_at=data.completed_at,
                key="error",
                status=EventStatus.error,
                output=run.error,
                attributes={"error": run.error, "error_type": run.error_type, "retryable": False},
                source=TraceEventSource.api,
            )
        )
    else:
        events.append(
            TraceEventData(
                type=TraceEventType.final_answer,
                name="Réponse finale",
                started_at=data.completed_at,
                key="final_answer",
                output=data.output_text,
                attributes={"has_json": data.output_json is not None},
                source=TraceEventSource.api,
            )
        )
    events.append(
        TraceEventData(
            type=TraceEventType.run_completed,
            name="Fin du run",
            started_at=data.completed_at,
            key="run_completed",
            status=EventStatus.error if data.failed else EventStatus.ok,
            attributes={
                "total_tokens": usage.total_tokens,
                "cost": cost,
                "latency_ms": latency_ms,
                "model_calls": data.model_calls,
                "tool_calls": 0,
            },
            source=TraceEventSource.api,
        )
    )
    planned = plan_events(events, origin=data.started_at, max_payload_chars=settings.max_event_payload_chars)
    await insert_events(session, run.id, planned)
    trace = ExecutionTrace(
        run_id=run.id,
        started_at=data.started_at,
        completed_at=data.completed_at,
        total_latency_ms=latency_ms,
        input=truncate_payload(data.input, settings.max_output_chars),
        output_text=truncate_text(data.output_text, settings.max_output_chars)
        if data.output_text is not None
        else None,
        output_json=truncate_payload(data.output_json, settings.max_output_chars),
        messages=[],
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        estimated_cost=cost,
        model_calls=data.model_calls,
        tool_calls=0,
        event_count=len(planned),
        errors=(
            [{"type": run.error_type, "message": run.error, "at": data.completed_at.isoformat()}]
            if data.failed
            else []
        ),
        metadata_={
            "origin": RunOrigin.observed.value,
            "external_id": data.external_id,
            "cost_source": cost_source,
            "invocation_ms": latency_ms,
        },
    )
    session.add(trace)
    await session.flush()
    return trace


__all__ = ["DEFAULT_FAILURE_MESSAGE", "ObservedRunData", "find_existing", "ingest_observed_run"]

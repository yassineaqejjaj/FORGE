"""Evaluation run lifecycle shared by every module (docs/ARCHITECTURE.md §8).

``PENDING → RUNNING → EVALUATING → COMPLETED`` (or ``FAILED`` / ``CANCELLED``).

* :func:`create_runs` materialises runs (frozen manifest) and enqueues their ``execute_run`` jobs;
* :func:`mark_running` / :func:`mark_evaluating` / :func:`mark_completed` / :func:`mark_failed`
  are the only functions allowed to change ``evaluation_runs.status``;
* :func:`on_run_terminal` updates benchmark-execution / experiment progress and enqueues their
  ``finalize_*`` job (deduplicated) once every run is terminal.

All functions flush only: the caller commits.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import (
    TERMINAL_RUN_STATUSES,
    ExecutionStatus,
    ExperimentArm,
    JobKind,
    RunOrigin,
    RunStatus,
)
from forge.domain.types import AgentSpec, ScenarioSpec
from forge.infra.db import utcnow
from forge.infra.models import (
    AgentVersion,
    BenchmarkExecution,
    EvaluationConfig,
    EvaluationRun,
    Experiment,
    ScenarioVersion,
)
from forge.infra.observability.metrics import record_run_terminal
from forge.infra.queue import PRIORITY_FINALIZE, PRIORITY_INTERACTIVE, cancel_jobs_for_runs, enqueue_job
from forge.services.mapping import (
    RunSpecs,
    build_manifest,
    load_agent_spec,
    load_criteria_catalog,
    load_score_config,
    scenario_spec,
)


@dataclass(slots=True)
class RunPlan:
    scenario_version_id: uuid.UUID
    agent_version_id: uuid.UUID
    repetition: int = 0
    arm: ExperimentArm | None = None


class RunCreationError(ValueError):
    """Invalid plan (unknown version, archived scenario…). Message is user-facing (French)."""


def new_otel_trace_id() -> str:
    return secrets.token_hex(16)


async def create_runs(
    session: AsyncSession,
    plans: Sequence[RunPlan],
    *,
    evaluation_config: EvaluationConfig,
    origin: RunOrigin,
    benchmark_execution_id: uuid.UUID | None = None,
    experiment_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    priority: int = PRIORITY_INTERACTIVE,
    tags: Sequence[str] = (),
    enqueue: bool = True,
) -> list[EvaluationRun]:
    """Create one run per plan with its immutable manifest and (optionally) enqueue execution."""
    from forge.infra.models import Scenario  # local: avoid widening the module import surface

    catalog = await load_criteria_catalog(session)
    config_spec = await load_score_config(session, evaluation_config)
    scenario_cache: dict[uuid.UUID, tuple[Scenario, ScenarioVersion, ScenarioSpec]] = {}
    agent_cache: dict[uuid.UUID, tuple[AgentVersion, AgentSpec]] = {}
    runs: list[EvaluationRun] = []
    now = utcnow()
    for plan in plans:
        if plan.scenario_version_id not in scenario_cache:
            found_sv = await session.get(ScenarioVersion, plan.scenario_version_id)
            if found_sv is None:
                raise RunCreationError("Version de scénario introuvable")
            found_scenario = await session.get(Scenario, found_sv.scenario_id)
            assert found_scenario is not None
            if found_scenario.archived:
                raise RunCreationError(f"Le scénario « {found_scenario.name} » est archivé")
            scenario_cache[plan.scenario_version_id] = (
                found_scenario,
                found_sv,
                scenario_spec(found_scenario, found_sv, catalog),
            )
        if plan.agent_version_id not in agent_cache:
            found_av = await session.get(AgentVersion, plan.agent_version_id)
            if found_av is None:
                raise RunCreationError("Version d'agent introuvable")
            agent_cache[plan.agent_version_id] = (found_av, await load_agent_spec(session, found_av))
        scenario, sv, s_spec = scenario_cache[plan.scenario_version_id]
        av, a_spec = agent_cache[plan.agent_version_id]
        run_id = uuid.uuid4()
        trace_id = new_otel_trace_id()
        manifest, manifest_hash = build_manifest(
            RunSpecs(scenario=s_spec, agent=a_spec, config=config_spec),
            {
                "run_id": str(run_id),
                "origin": origin,
                "repetition": plan.repetition,
                "arm": plan.arm,
                "benchmark_execution_id": str(benchmark_execution_id) if benchmark_execution_id else None,
                "experiment_id": str(experiment_id) if experiment_id else None,
                "otel_trace_id": trace_id,
                "created_at": now,
            },
        )
        run = EvaluationRun(
            id=run_id,
            origin=origin,
            benchmark_execution_id=benchmark_execution_id,
            experiment_id=experiment_id,
            arm=plan.arm,
            scenario_id=scenario.id,
            scenario_version_id=sv.id,
            agent_id=av.agent_id,
            agent_version_id=av.id,
            evaluation_config_id=evaluation_config.id,
            repetition=plan.repetition,
            status=RunStatus.pending,
            manifest=manifest,
            manifest_hash=manifest_hash,
            otel_trace_id=trace_id,
            tags=list(tags),
            created_by=created_by,
            queued_at=now if enqueue else None,
        )
        session.add(run)
        runs.append(run)
    await session.flush()
    if enqueue:
        for run in runs:
            await enqueue_job(session, JobKind.execute_run, run_id=run.id, priority=priority, max_attempts=3)
    return runs


# --- Transitions -------------------------------------------------------------------------------------


async def mark_running(session: AsyncSession, run: EvaluationRun, detail: str | None = None) -> None:
    run.status = RunStatus.running
    run.status_detail = detail
    run.started_at = run.started_at or utcnow()
    await session.flush()


async def mark_evaluating(session: AsyncSession, run: EvaluationRun, *, enqueue: bool = True) -> None:
    """Execution finished (success or captured failure): hand over to the evaluation queue."""
    run.status = RunStatus.evaluating
    run.status_detail = "Évaluation en attente"
    run.executed_at = run.executed_at or utcnow()
    await session.flush()
    if enqueue:
        await enqueue_job(
            session,
            JobKind.evaluate_run,
            run_id=run.id,
            priority=PRIORITY_INTERACTIVE if run.origin == RunOrigin.adhoc else 20,
            max_attempts=3,
            dedupe_key=f"evaluate_run:{run.id}",
        )


async def mark_completed(session: AsyncSession, run: EvaluationRun) -> None:
    run.status = RunStatus.completed
    run.status_detail = None
    run.evaluated_at = utcnow()
    run.finished_at = run.evaluated_at
    await session.flush()
    await on_run_terminal(session, run)


async def mark_failed(
    session: AsyncSession, run: EvaluationRun, error: str, *, error_type: str = "EXECUTION_ERROR"
) -> None:
    run.status = RunStatus.failed
    run.error = error[:4000]
    run.error_type = error_type
    run.status_detail = None
    run.finished_at = utcnow()
    await session.flush()
    await on_run_terminal(session, run)


async def cancel_runs(session: AsyncSession, runs: Sequence[EvaluationRun]) -> int:
    """Cancel non-terminal runs (queued jobs are cancelled; a running agent call finishes first)."""
    active = [r for r in runs if r.status not in TERMINAL_RUN_STATUSES]
    await cancel_jobs_for_runs(session, [r.id for r in active])
    now = utcnow()
    for run in active:
        run.status = RunStatus.cancelled
        run.status_detail = None
        run.finished_at = now
    await session.flush()
    for run in active:
        await on_run_terminal(session, run)
    return len(active)


async def is_cancelled(session: AsyncSession, run_id: uuid.UUID) -> bool:
    status = await session.scalar(select(EvaluationRun.status).where(EvaluationRun.id == run_id))
    return status == RunStatus.cancelled


# --- Terminal hook -------------------------------------------------------------------------------------


async def on_run_terminal(session: AsyncSession, run: EvaluationRun) -> None:
    """Refresh parent progress counters and enqueue its finalisation when every run is terminal."""
    record_run_terminal(run.status.value, run.origin.value)
    if run.benchmark_execution_id is not None:
        await _refresh_progress(
            session, BenchmarkExecution, run.benchmark_execution_id, "benchmark_execution_id"
        )
    if run.experiment_id is not None:
        await _refresh_progress(session, Experiment, run.experiment_id, "experiment_id")


async def _refresh_progress(
    session: AsyncSession,
    model: type[BenchmarkExecution] | type[Experiment],
    parent_id: uuid.UUID,
    column: str,
) -> None:
    # Serialise concurrent terminal transitions of sibling runs: without this lock, two runs finishing
    # at the same time each count the other as still active and nobody enqueues the finalisation.
    # Under READ COMMITTED the count below runs after the lock is granted, so it sees the sibling's
    # committed status.
    await session.execute(select(model.id).where(model.id == parent_id).with_for_update())
    col = getattr(EvaluationRun, column)
    counts = dict(
        (
            await session.execute(
                select(EvaluationRun.status, func.count())
                .where(col == parent_id)
                .group_by(EvaluationRun.status)
            )
        ).all()
    )
    total = sum(counts.values())
    completed = int(counts.get(RunStatus.completed, 0))
    failed = int(counts.get(RunStatus.failed, 0)) + int(counts.get(RunStatus.cancelled, 0))
    await session.execute(
        update(model).where(model.id == parent_id).values(completed_runs=completed, failed_runs=failed)
    )
    if total and completed + failed >= total:
        parent: BenchmarkExecution | Experiment | None = await session.get(model, parent_id)
        if parent is not None and parent.status in (ExecutionStatus.queued, ExecutionStatus.running):
            parent.status = ExecutionStatus.aggregating
        kind = JobKind.finalize_execution if model is BenchmarkExecution else JobKind.finalize_experiment
        await enqueue_job(
            session,
            kind,
            payload={"id": str(parent_id)},
            priority=PRIORITY_FINALIZE,
            dedupe_key=f"{kind.value}:{parent_id}",
        )
    await session.flush()


async def sweep_stalled_parents(session: AsyncSession) -> int:
    """Safety net (worker loop): finalise executions / experiments whose runs are all terminal but whose
    finalisation was never enqueued (crash between a run's completion and its parent refresh). Commits."""
    active_parent = (ExecutionStatus.queued, ExecutionStatus.running, ExecutionStatus.aggregating)
    swept = 0
    for model, column in ((BenchmarkExecution, "benchmark_execution_id"), (Experiment, "experiment_id")):
        col = getattr(EvaluationRun, column)
        pending_runs = (
            select(EvaluationRun.id)
            .where(col == model.id, EvaluationRun.status.not_in(list(TERMINAL_RUN_STATUSES)))
            .exists()
        )
        any_run = select(EvaluationRun.id).where(col == model.id).exists()
        ids = list(
            await session.scalars(
                select(model.id).where(model.status.in_(active_parent), any_run, ~pending_runs)
            )
        )
        for parent_id in ids:
            await _refresh_progress(session, model, parent_id, column)
            swept += 1
        await session.commit()
    return swept

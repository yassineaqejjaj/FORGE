"""Dashboard and errors explorer (docs/ARCHITECTURE.md §12 — analytics).

Everything is computed with set-based SQL aggregates (no per-run Python loop) and restricted to
the scenarios within the caller's clearance. Error descriptions and evidence of private scenarios
are masked for non-maintainers (``forge.domain.redaction``).

Definitions used by the dashboard (window = last ``days`` days, by run creation date):

* ``average_composite`` — mean composite of terminal evaluated runs (completed + failed);
* ``pass_rate`` — passed / evaluated runs;
* ``error_rate`` — share of evaluated runs with at least one detected error (current round);
* ``failure_rate`` — failed runs / terminal runs (completed + failed + cancelled);
* averages of cost and latency over executed runs (execution trace present).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Date, case, cast, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import ErrorSeverity, RunStatus
from forge.domain.redaction import redact_error
from forge.infra.db import utcnow
from forge.infra.models import (
    Agent,
    AgentVersion,
    ErrorType,
    EvaluationRun,
    ExecutionTrace,
    RunError,
    Scenario,
)
from forge.infra.queue import queue_depth
from forge.services import access
from forge.services.access import Viewer
from forge.services.benchmarks import recent_executions
from forge.services.experiments import recent_experiments

EVALUATED = (RunStatus.completed, RunStatus.failed)
TERMINAL = (RunStatus.completed, RunStatus.failed, RunStatus.cancelled)
SEVERITY_ORDER = [s.value for s in ErrorSeverity]


def _current_round() -> ColumnElement[bool]:
    return or_(RunError.round.is_(None), RunError.round == EvaluationRun.evaluation_round)


def _has_error() -> ColumnElement[bool]:
    return exists(select(RunError.id).where(RunError.run_id == EvaluationRun.id, _current_round()))


def _ratio(numerator: Any, denominator: Any) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


async def dashboard(session: AsyncSession, viewer: Viewer, *, days: int = 30) -> dict[str, Any]:
    now = utcnow()
    since = now - timedelta(days=days)
    visible = access.classification_condition(viewer)
    window = [EvaluationRun.created_at >= since, visible]

    counts = {
        "agents": await session.scalar(
            select(func.count()).select_from(Agent).where(Agent.archived.is_(False))
        ),
        "agent_versions": await session.scalar(
            select(func.count())
            .select_from(AgentVersion)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(Agent.archived.is_(False))
        ),
        "scenarios": await session.scalar(
            select(func.count()).select_from(Scenario).where(Scenario.archived.is_(False), visible)
        ),
    }

    evaluated = EvaluationRun.status.in_(EVALUATED)
    stats_cols = (
        func.count(),
        func.count().filter(EvaluationRun.status == RunStatus.completed),
        func.count().filter(EvaluationRun.status == RunStatus.failed),
        func.count().filter(EvaluationRun.status == RunStatus.cancelled),
        func.count().filter(evaluated),
        func.avg(EvaluationRun.composite_score).filter(evaluated),
        func.count().filter(evaluated, EvaluationRun.passed.is_(True)),
        func.count().filter(evaluated, _has_error()),
        func.avg(ExecutionTrace.estimated_cost),
        func.avg(ExecutionTrace.total_latency_ms),
        func.sum(ExecutionTrace.estimated_cost),
    )
    base = (
        select(*stats_cols)
        .select_from(EvaluationRun)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .outerjoin(ExecutionTrace, ExecutionTrace.run_id == EvaluationRun.id)
        .where(*window)
    )
    total, completed, failed, cancelled, n_eval, avg_comp, n_passed, n_err, avg_cost, avg_lat, sum_cost = (
        await session.execute(base)
    ).one()
    status_rows = await session.execute(
        select(EvaluationRun.status, func.count())
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .where(*window)
        .group_by(EvaluationRun.status)
    )
    by_status = {s.value: 0 for s in RunStatus}
    for status, count in status_rows.all():
        by_status[str(status.value if hasattr(status, "value") else status)] = int(count)

    day = cast(func.date_trunc("day", EvaluationRun.created_at), Date).label("day")
    trend_rows = await session.execute(
        select(day, *stats_cols)
        .select_from(EvaluationRun)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .outerjoin(ExecutionTrace, ExecutionTrace.run_id == EvaluationRun.id)
        .where(*window)
        .group_by(day)
    )
    trend_by_day: dict[date, Any] = {row[0]: row for row in trend_rows.all()}
    trends: list[dict[str, Any]] = []
    start = since.date()
    for offset in range((now.date() - start).days + 1):
        current = start + timedelta(days=offset)
        row = trend_by_day.get(current)
        if row is None:
            trends.append(
                {
                    "date": current.isoformat(),
                    "runs": 0,
                    "completed": 0,
                    "failed": 0,
                    "average_composite": None,
                    "pass_rate": None,
                    "error_rate": None,
                    "average_cost": None,
                    "average_latency_ms": None,
                }
            )
            continue
        _, t_total, t_completed, t_failed, _t_cancel, t_eval, t_comp, t_passed, t_err, t_cost, t_lat, _ = row
        trends.append(
            {
                "date": current.isoformat(),
                "runs": int(t_total),
                "completed": int(t_completed),
                "failed": int(t_failed),
                "average_composite": _float(t_comp),
                "pass_rate": _ratio(t_passed, t_eval),
                "error_rate": _ratio(t_err, t_eval),
                "average_cost": _float(t_cost),
                "average_latency_ms": _float(t_lat),
            }
        )

    error_rows = await session.execute(
        select(RunError.error_type, ErrorType.label, func.count(), func.count(distinct(RunError.run_id)))
        .join(EvaluationRun, EvaluationRun.id == RunError.run_id)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .outerjoin(ErrorType, ErrorType.code == RunError.error_type)
        .where(*window, _current_round())
        .group_by(RunError.error_type, ErrorType.label)
        .order_by(func.count().desc(), RunError.error_type)
        .limit(10)
    )
    top_errors = [
        {"error_type": t, "label": label or t, "count": int(c), "runs_affected": int(r)}
        for t, label, c, r in error_rows.all()
    ]

    executions = []
    for execution, benchmark in await recent_executions(session, limit=5):
        ranking = (execution.summary or {}).get("ranking") or []
        leader = ranking[0] if ranking else None
        executions.append(
            {
                "id": execution.id,
                "benchmark_id": benchmark.id,
                "benchmark_name": benchmark.name,
                "number": execution.number,
                "status": execution.status.value,
                "total_runs": execution.total_runs,
                "completed_runs": execution.completed_runs,
                "failed_runs": execution.failed_runs,
                "created_at": execution.created_at,
                "finished_at": execution.finished_at,
                "leader_label": leader.get("agent_label") if leader else None,
                "leader_score": leader.get("group_composite") if leader else None,
            }
        )
    experiments = []
    for listing in await recent_experiments(session, limit=5):
        exp = listing.experiment
        comparison = exp.comparison or {}
        experiments.append(
            {
                "id": exp.id,
                "name": exp.name,
                "status": exp.status.value,
                "baseline_label": listing.baseline["label"] if listing.baseline else None,
                "candidate_label": listing.candidate["label"] if listing.candidate else None,
                "recommendation": exp.recommendation,
                "confidence": (comparison.get("recommendation") or {}).get("confidence"),
                "composite_delta": (comparison.get("composite") or {}).get("delta"),
                "total_runs": exp.total_runs,
                "completed_runs": exp.completed_runs,
                "failed_runs": exp.failed_runs,
                "created_at": exp.created_at,
            }
        )

    return {
        "days": days,
        "since": since,
        "generated_at": now,
        "counts": {
            "agents": int(counts["agents"] or 0),
            "agent_versions": int(counts["agent_versions"] or 0),
            "scenarios": int(counts["scenarios"] or 0),
            "runs": int(total or 0),
        },
        "runs_by_status": by_status,
        "kpis": {
            "average_composite": _float(avg_comp),
            "pass_rate": _ratio(n_passed, n_eval),
            "error_rate": _ratio(n_err, n_eval),
            "failure_rate": _ratio(failed, (completed or 0) + (failed or 0) + (cancelled or 0)),
            "average_cost": _float(avg_cost),
            "total_cost": _float(sum_cost),
            "average_latency_ms": _float(avg_lat),
            "evaluated_runs": int(n_eval or 0),
        },
        "trends": trends,
        "top_error_types": top_errors,
        "recent_benchmark_executions": executions,
        "recent_experiments": experiments,
        "queue_depth": await queue_depth(session),
    }


# =====================================================================================================
# Errors explorer
# =====================================================================================================


@dataclass(slots=True)
class ErrorFilters:
    error_type: Sequence[str] | None = None
    severity: Sequence[str] | None = None
    agent_id: uuid.UUID | None = None
    agent_version_id: uuid.UUID | None = None
    scenario_id: uuid.UUID | None = None
    category: str | None = None
    benchmark_execution_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _error_conditions(viewer: Viewer, filters: ErrorFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [access.classification_condition(viewer), _current_round()]
    if filters.error_type:
        conditions.append(RunError.error_type.in_(list(filters.error_type)))
    if filters.severity:
        conditions.append(RunError.severity.in_([ErrorSeverity(s) for s in filters.severity]))
    if filters.agent_id:
        conditions.append(EvaluationRun.agent_id == filters.agent_id)
    if filters.agent_version_id:
        conditions.append(EvaluationRun.agent_version_id == filters.agent_version_id)
    if filters.scenario_id:
        conditions.append(EvaluationRun.scenario_id == filters.scenario_id)
    if filters.category:
        conditions.append(Scenario.category == filters.category)
    if filters.benchmark_execution_id:
        conditions.append(EvaluationRun.benchmark_execution_id == filters.benchmark_execution_id)
    if filters.experiment_id:
        conditions.append(EvaluationRun.experiment_id == filters.experiment_id)
    if filters.run_id:
        conditions.append(EvaluationRun.id == filters.run_id)
    if filters.date_from:
        conditions.append(RunError.created_at >= filters.date_from)
    if filters.date_to:
        conditions.append(RunError.created_at <= filters.date_to)
    return conditions


def _joined(stmt: Any) -> Any:
    return (
        stmt.join(EvaluationRun, EvaluationRun.id == RunError.run_id)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .join(AgentVersion, AgentVersion.id == EvaluationRun.agent_version_id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
    )


async def explore_errors(
    session: AsyncSession, viewer: Viewer, filters: ErrorFilters, *, offset: int = 0, limit: int = 25
) -> dict[str, Any]:
    conditions = _error_conditions(viewer, filters)
    total = await session.scalar(_joined(select(func.count()).select_from(RunError)).where(*conditions))
    rows = await session.execute(
        _joined(select(RunError, EvaluationRun, Scenario, AgentVersion.version, Agent.name, ErrorType.label))
        .outerjoin(ErrorType, ErrorType.code == RunError.error_type)
        .where(*conditions)
        .order_by(RunError.created_at.desc(), RunError.id)
        .offset(offset)
        .limit(limit)
    )
    items: list[dict[str, Any]] = []
    for error, run, scenario, version, agent_name, label in rows.all():
        item: dict[str, Any] = {
            "id": error.id,
            "run_id": run.id,
            "error_type": error.error_type,
            "label": label or error.error_type,
            "severity": error.severity.value,
            "description": error.description,
            "evidence": list(error.evidence or []),
            "criterion_key": error.criterion_key,
            "evaluator_kind": error.evaluator_kind.value if error.evaluator_kind else None,
            "evaluator_key": error.evaluator_key,
            "trace_event_id": error.trace_event_id,
            "round": error.round,
            "created_at": error.created_at,
            "run_status": run.status.value,
            "origin": run.origin.value,
            "benchmark_execution_id": run.benchmark_execution_id,
            "experiment_id": run.experiment_id,
            "scenario": {
                "id": scenario.id,
                "slug": scenario.slug,
                "name": scenario.name,
                "category": scenario.category,
                "visibility": scenario.visibility.value,
                "classification": int(scenario.classification),
            },
            "agent": {"id": run.agent_id, "name": agent_name},
            "agent_version": {
                "id": run.agent_version_id,
                "version": version,
                "label": f"{agent_name} v{version}",
            },
            "redacted": False,
        }
        if access.must_redact(viewer, scenario.visibility):
            item = redact_error(item)
        items.append(item)

    async def grouped(*columns: Any, order_limit: int | None = None) -> list[Any]:
        stmt = (
            _joined(
                select(*columns, func.count(), func.count(distinct(RunError.run_id))).select_from(RunError)
            )
            .where(*conditions)
            .group_by(*columns)
            .order_by(func.count().desc())
        )
        if order_limit:
            stmt = stmt.limit(order_limit)
        return list((await session.execute(stmt)).all())

    by_type_rows = await session.execute(
        _joined(
            select(
                RunError.error_type, ErrorType.label, func.count(), func.count(distinct(RunError.run_id))
            ).select_from(RunError)
        )
        .outerjoin(ErrorType, ErrorType.code == RunError.error_type)
        .where(*conditions)
        .group_by(RunError.error_type, ErrorType.label)
        .order_by(func.count().desc(), RunError.error_type)
    )
    by_severity = {s: 0 for s in SEVERITY_ORDER}
    for severity, count, _runs in await grouped(RunError.severity):
        by_severity[severity.value] = int(count)
    by_agent_version = [
        {"agent_version_id": av, "label": f"{name} v{version}", "count": int(c), "runs_affected": int(r)}
        for av, name, version, c, r in await grouped(AgentVersion.id, Agent.name, AgentVersion.version)
    ]
    by_scenario = [
        {"scenario_id": sid, "slug": slug, "name": name, "count": int(c), "runs_affected": int(r)}
        for sid, slug, name, c, r in await grouped(Scenario.id, Scenario.slug, Scenario.name, order_limit=20)
    ]
    critical = case((RunError.severity == ErrorSeverity.critical, 1), else_=0)
    runs_affected = await session.scalar(
        _joined(select(func.count(distinct(RunError.run_id))).select_from(RunError)).where(*conditions)
    )
    n_critical = await session.scalar(
        _joined(select(func.sum(critical)).select_from(RunError)).where(*conditions)
    )
    return {
        "items": items,
        "total": int(total or 0),
        "aggregations": {
            "total": int(total or 0),
            "runs_affected": int(runs_affected or 0),
            "critical": int(n_critical or 0),
            "by_type": [
                {"error_type": t, "label": label or t, "count": int(c), "runs_affected": int(r)}
                for t, label, c, r in by_type_rows.all()
            ],
            "by_severity": by_severity,
            "by_agent_version": by_agent_version,
            "by_scenario": by_scenario,
        },
    }


__all__ = ["ErrorFilters", "dashboard", "explore_errors"]

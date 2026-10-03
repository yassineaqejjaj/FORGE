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

from forge.domain.enums import ErrorSeverity, ExecutionStatus, Recommendation, RunStatus
from forge.domain.redaction import redact_error
from forge.infra.db import utcnow
from forge.infra.models import (
    Agent,
    AgentVersion,
    BenchmarkExecution,
    ErrorType,
    EvaluationRun,
    ExecutionTrace,
    Experiment,
    RunError,
    Scenario,
    TraceEvent,
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


def _has_critical_error() -> ColumnElement[bool]:
    return exists(
        select(RunError.id).where(
            RunError.run_id == EvaluationRun.id,
            _current_round(),
            RunError.severity == ErrorSeverity.critical,
        )
    )


def _ratio(numerator: Any, denominator: Any) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


async def dashboard(
    session: AsyncSession, viewer: Viewer, *, days: int = 30, agent_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Vue d'ensemble: KPIs of the window (and of the previous window of the same length, for the
    variations), daily trends, items needing an action, error causes and recent experiments.
    ``agent_id`` restricts everything to one evaluated system."""
    now = utcnow()
    since = now - timedelta(days=days)
    previous_since = since - timedelta(days=days)
    visible = access.classification_condition(viewer)
    scope = [visible] + ([EvaluationRun.agent_id == agent_id] if agent_id else [])
    window = [EvaluationRun.created_at >= since, *scope]
    previous_window = [EvaluationRun.created_at >= previous_since, EvaluationRun.created_at < since, *scope]

    agent_scope = [Agent.archived.is_(False)] + ([Agent.id == agent_id] if agent_id else [])
    counts = {
        "agents": await session.scalar(select(func.count()).select_from(Agent).where(*agent_scope)),
        "agent_versions": await session.scalar(
            select(func.count())
            .select_from(AgentVersion)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(*agent_scope)
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
    reliability_cols = (
        func.count().filter(evaluated, EvaluationRun.gate_failed.is_(False), ~_has_critical_error()),
        func.count().filter(evaluated, EvaluationRun.gate_failed.is_(True)),
        func.count().filter(evaluated, _has_critical_error()),
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
    reliability_stmt = (
        select(*reliability_cols)
        .select_from(EvaluationRun)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
    )
    n_reliable, n_gate_failed, n_critical = (await session.execute(reliability_stmt.where(*window))).one()

    previous = (
        await session.execute(
            select(*stats_cols, *reliability_cols)
            .select_from(EvaluationRun)
            .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
            .outerjoin(ExecutionTrace, ExecutionTrace.run_id == EvaluationRun.id)
            .where(*previous_window)
        )
    ).one()
    p_total, _pc, _pf, _pcan, p_eval, p_comp, p_passed, p_err, p_cost, p_lat, _ps, p_reliable, _pg, _pcr = (
        previous
    )
    previous_kpis = (
        {
            "runs": int(p_total),
            "evaluated_runs": int(p_eval or 0),
            "average_composite": _float(p_comp),
            "pass_rate": _ratio(p_passed, p_eval),
            "reliability_rate": _ratio(p_reliable, p_eval),
            "error_rate": _ratio(p_err, p_eval),
            "average_cost": _float(p_cost),
            "average_latency_ms": _float(p_lat),
        }
        if p_total
        else None
    )
    first_activity = await session.scalar(
        select(func.min(EvaluationRun.created_at))
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .where(*window)
    )
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

    severity_rank = case(
        *[(RunError.severity == sev, rank) for rank, sev in enumerate(SEVERITY_ORDER)], else_=0
    )
    error_rows = await session.execute(
        select(
            RunError.error_type,
            ErrorType.label,
            func.count(),
            func.count(distinct(RunError.run_id)),
            func.max(severity_rank),
        )
        .join(EvaluationRun, EvaluationRun.id == RunError.run_id)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .outerjoin(ErrorType, ErrorType.code == RunError.error_type)
        .where(*window, _current_round())
        .group_by(RunError.error_type, ErrorType.label)
        .order_by(func.count().desc(), RunError.error_type)
    )
    all_errors = [
        {
            "error_type": t,
            "label": label or t,
            "count": int(c),
            "runs_affected": int(r),
            "max_severity": SEVERITY_ORDER[int(rank or 0)],
        }
        for t, label, c, r, rank in error_rows.all()
    ]
    top_errors = all_errors[:10]

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
    for listing in await recent_experiments(session, limit=5, agent_id=agent_id):
        exp = listing.experiment
        comparison = exp.comparison or {}
        regressions = comparison.get("regressions") or []
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
                "regressions": len(regressions),
                "critical_regressions": sum(1 for r in regressions if r.get("severity") == "critical"),
                "total_runs": exp.total_runs,
                "completed_runs": exp.completed_runs,
                "failed_runs": exp.failed_runs,
                "created_at": exp.created_at,
            }
        )

    attention = await _attention(
        session,
        since=since,
        agent_id=agent_id,
        gate_failed=int(n_gate_failed or 0),
        interrupted=int(failed or 0),
        critical_runs=int(n_critical or 0),
        errors=all_errors,
    )
    comparisons_completed = await session.scalar(
        select(func.count())
        .select_from(BenchmarkExecution)
        .where(
            BenchmarkExecution.status == ExecutionStatus.completed, BenchmarkExecution.finished_at >= since
        )
    )

    return {
        "days": days,
        "since": since,
        "generated_at": now,
        "agent_id": agent_id,
        "first_activity": first_activity,
        "previous_kpis": previous_kpis,
        "attention": attention,
        "error_types_total": len(all_errors),
        "comparisons_completed": int(comparisons_completed or 0),
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
            "reliability_rate": _ratio(n_reliable, n_eval),
            "completed_runs": int(completed or 0),
            "interrupted_runs": int(failed or 0),
            "gate_failed_runs": int(n_gate_failed or 0),
            "critical_error_runs": int(n_critical or 0),
        },
        "trends": trends,
        "top_error_types": top_errors,
        "recent_benchmark_executions": executions,
        "recent_experiments": experiments,
        "queue_depth": await queue_depth(session),
    }


async def _attention(
    session: AsyncSession,
    *,
    since: datetime,
    agent_id: uuid.UUID | None,
    gate_failed: int,
    interrupted: int,
    critical_runs: int,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Facts that call for an action (the UI decides how to phrase and order them)."""
    stmt = select(Experiment).where(
        Experiment.created_at >= since, Experiment.status == ExecutionStatus.completed
    )
    if agent_id is not None:
        stmt = stmt.join(AgentVersion, AgentVersion.id == Experiment.baseline_version_id).where(
            AgentVersion.agent_id == agent_id
        )
    regressing = []
    for experiment in await session.scalars(stmt.order_by(Experiment.created_at.desc())):
        regressions = (experiment.comparison or {}).get("regressions") or []
        critical = sum(1 for r in regressions if r.get("severity") == "critical")
        if critical or experiment.recommendation == Recommendation.do_not_ship.value:
            regressing.append(
                {"id": experiment.id, "name": experiment.name, "critical_regressions": critical}
            )
    return {
        "experiments_with_regression": len(regressing),
        "latest_regression": regressing[0] if regressing else None,
        "gate_failed_runs": gate_failed,
        "interrupted_runs": interrupted,
        "critical_error_runs": critical_runs,
        "critical_errors": [e for e in errors if e["max_severity"] == ErrorSeverity.critical.value][:3],
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
            "trace_event_seq": None,
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
    event_ids = [i["trace_event_id"] for i in items if i.get("trace_event_id")]
    if event_ids:
        seqs = dict(
            (
                await session.execute(
                    select(TraceEvent.id, TraceEvent.seq).where(TraceEvent.id.in_(event_ids))
                )
            ).all()
        )
        for item in items:
            event_id = item.get("trace_event_id")
            item["trace_event_seq"] = seqs.get(event_id) if event_id else None

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


# --- Results overview (« Analyser › Résultats ») ------------------------------------------------------

RESULTS_MAX_RUNS = 5000
RESULTS_RESAMPLES = 2000


async def results_overview(
    session: AsyncSession,
    viewer: Viewer,
    *,
    days: int = 30,
    agent_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Evaluated runs of the window aggregated per agent version (any origin: ad hoc, benchmark,
    experiment), with the error breakdown. Same statistics as a benchmark execution, so the numbers
    of the Résultats page and of the Comparaisons pages are computed identically."""
    from forge.domain.benchmarks.aggregation import aggregate_agent, error_breakdown
    from forge.domain.defaults import DEFAULT_DIMENSION_WEIGHTS
    from forge.domain.types import to_dict
    from forge.infra.models import EvaluationConfig
    from forge.services.run_summaries import load_run_summaries

    since = utcnow() - timedelta(days=days)
    conditions: list[ColumnElement[bool]] = [
        EvaluationRun.created_at >= since,
        EvaluationRun.status.in_(list(EVALUATED)),
    ]
    if agent_id is not None:
        conditions.append(EvaluationRun.agent_id == agent_id)
    recent_ids = list(
        await session.scalars(
            select(EvaluationRun.id)
            .where(*conditions)
            .order_by(EvaluationRun.created_at.desc())
            .limit(RESULTS_MAX_RUNS)
        )
    )
    summaries = await load_run_summaries(session, run_ids=recent_ids, viewer=viewer) if recent_ids else []
    default_config = await session.scalar(
        select(EvaluationConfig).where(
            EvaluationConfig.is_default.is_(True), EvaluationConfig.is_latest.is_(True)
        )
    )
    weights = dict(default_config.dimension_weights) if default_config else dict(DEFAULT_DIMENSION_WEIGHTS)

    per_version: dict[str, list[Any]] = {}
    for summary in summaries:
        per_version.setdefault(summary.agent_version_id, []).append(summary)
    agents = [
        aggregate_agent(runs, dimension_weights=weights, n_resamples=RESULTS_RESAMPLES)
        for runs in per_version.values()
    ]
    agents.sort(key=lambda a: (a.composite.mean is None, -(a.composite.mean or 0.0), a.agent_label))
    rows = []
    for agent in agents:
        rows.append(
            {
                "agent_version_id": agent.agent_version_id,
                "agent_id": agent.agent_id,
                "agent_label": agent.agent_label,
                "model": agent.model,
                "n_runs": agent.n_runs,
                "n_scored": agent.n_scored,
                "n_failed": agent.n_failed,
                "composite_mean": agent.composite.mean,
                "composite_ci_low": agent.composite.ci_low,
                "composite_ci_high": agent.composite.ci_high,
                "pass_rate": agent.pass_rate,
                "gate_failure_rate": agent.gate_failure_rate,
                "error_rate": agent.error_rate,
                "dimensions": dict(agent.dimensions),
                "cost_mean": agent.cost.mean,
                "latency_mean": agent.latency.mean,
                "latency_p95": agent.latency.p95,
                "tokens_mean": agent.tokens.mean,
                "errors_by_type": dict(agent.errors_by_type),
            }
        )
    return {
        "days": days,
        "since": since,
        "n_runs": len(summaries),
        "truncated": len(recent_ids) >= RESULTS_MAX_RUNS,
        "agents": rows,
        "errors": [to_dict(row) for row in error_breakdown(summaries)][:12],
    }

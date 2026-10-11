"""Production monitoring queries (ORION): results per release, agent health, risk of a run in flight.

Rules live in ``forge.domain.monitoring``; this module only gathers the runs and events they need.
*Production-like* runs are the ones that do not come from a test harness: observed runs and ad hoc runs
(captures of real executions), never benchmark or experiment runs.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import EventStatus, RunOrigin, RunStatus, TraceEventType
from forge.domain.monitoring import (
    Budget,
    Progress,
    Reference,
    ToolStep,
    WindowStats,
    assess_risk,
    health_verdict,
    percentile,
    summarize,
)
from forge.infra.db import utcnow
from forge.infra.models import Agent, EvaluationRun, ExecutionTrace, TraceEvent
from forge.services.access import Viewer
from forge.services.mapping import specs_from_manifest
from forge.services.run_queries import get_visible_run
from forge.services.run_summaries import load_run_summaries
from forge.services.taxonomy import NotFoundError

PRODUCTION_ORIGINS = (RunOrigin.observed, RunOrigin.adhoc)
#: Release attribution only holds for runs that *are* what happened in production. An ad hoc capture is a
#: re-execution under whatever version is active when FORGE runs it, so it says nothing about a release.
RELEASE_ORIGINS = (RunOrigin.observed,)
EVALUATED = (RunStatus.completed, RunStatus.failed)
MAX_RUNS = 2000
REFERENCE_RUNS = 100
NO_RELEASE = "(sans release)"


async def releases_overview(
    session: AsyncSession, viewer: Viewer, *, days: int = 30, agent_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Evaluated observed runs of the window, grouped by the release that produced them."""
    since = utcnow() - timedelta(days=days)
    conditions = [
        EvaluationRun.created_at >= since,
        EvaluationRun.status.in_(list(EVALUATED)),
        EvaluationRun.origin.in_(list(RELEASE_ORIGINS)),
    ]
    if agent_id is not None:
        conditions.append(EvaluationRun.agent_id == agent_id)
    ids = list(
        await session.scalars(
            select(EvaluationRun.id)
            .where(*conditions)
            .order_by(EvaluationRun.created_at.desc())
            .limit(MAX_RUNS)
        )
    )
    summaries = await load_run_summaries(session, run_ids=ids, viewer=viewer) if ids else []
    release_rows = (
        await session.execute(
            select(EvaluationRun.id, EvaluationRun.release_id).where(EvaluationRun.id.in_(ids))
        )
        if ids
        else None
    )
    release_of = {str(rid): rel for rid, rel in release_rows.all()} if release_rows is not None else {}
    groups: dict[str | None, list[Any]] = {}
    for summary in summaries:
        groups.setdefault(release_of.get(summary.run_id), []).append(summary)
    reference = summarize(groups.get(None, []))
    rows = []
    for release, runs in groups.items():
        stats = summarize(runs)
        row: dict[str, Any] = {"release_id": release, "label": release or NO_RELEASE, **asdict(stats)}
        if release is not None and reference.n_runs:
            row["vs_no_release"] = {
                "composite_delta": _delta(stats.composite_mean, reference.composite_mean),
                "pass_rate_delta": _delta(stats.pass_rate, reference.pass_rate),
                "cost_per_success_delta": _delta(stats.cost_per_success, reference.cost_per_success),
            }
        rows.append(row)
    rows.sort(key=lambda r: (r["release_id"] is None, -(r["n_runs"])))
    return {
        "days": days,
        "since": since,
        "n_runs": len(summaries),
        "truncated": len(ids) >= MAX_RUNS,
        "releases": rows,
    }


def _delta(recent: float | None, base: float | None) -> float | None:
    return round(recent - base, 4) if recent is not None and base is not None else None


async def _window(
    session: AsyncSession, viewer: Viewer, agent_id: uuid.UUID, start: Any, end: Any
) -> WindowStats:
    ids = list(
        await session.scalars(
            select(EvaluationRun.id)
            .where(
                EvaluationRun.agent_id == agent_id,
                EvaluationRun.origin.in_(list(PRODUCTION_ORIGINS)),
                EvaluationRun.status.in_(list(EVALUATED)),
                EvaluationRun.created_at > start,
                EvaluationRun.created_at <= end,
            )
            .limit(MAX_RUNS)
        )
    )
    return summarize(await load_run_summaries(session, run_ids=ids, viewer=viewer) if ids else [])


async def agent_health(
    session: AsyncSession,
    viewer: Viewer,
    agent_id: uuid.UUID,
    *,
    window_hours: int = 24,
    baseline_hours: int = 168,
) -> dict[str, Any]:
    """Recent window against the one before it for one agent (all its versions)."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise NotFoundError("Agent introuvable")
    now = utcnow()
    recent_start = now - timedelta(hours=window_hours)
    previous_start = recent_start - timedelta(hours=baseline_hours)
    health = health_verdict(
        await _window(session, viewer, agent_id, recent_start, now),
        await _window(session, viewer, agent_id, previous_start, recent_start),
    )
    return {
        "agent_id": agent_id,
        "agent": agent.name,
        "status": health.status,
        "reason": health.reason,
        "window_hours": window_hours,
        "baseline_hours": baseline_hours,
        "recent": asdict(health.recent),
        "previous": asdict(health.previous),
        "alerts": [asdict(a) for a in health.alerts],
    }


def _tokens_of(attributes: dict[str, Any]) -> int:
    for key in ("total_tokens", "tokens"):
        if isinstance(attributes.get(key), int | float):
            return int(attributes[key])
    return int(attributes.get("input_tokens") or 0) + int(attributes.get("output_tokens") or 0)


async def run_risk(session: AsyncSession, viewer: Viewer, run_id: uuid.UUID) -> dict[str, Any]:
    """Failure risk of a run, from the steps it reported so far, against successful runs of its version."""
    run, _ = await get_visible_run(session, viewer, run_id)
    events = list(
        await session.scalars(select(TraceEvent).where(TraceEvent.run_id == run.id).order_by(TraceEvent.seq))
    )
    steps: list[ToolStep] = []
    tokens, cost, errors, final = 0, 0.0, 0, False
    for event in events:
        attrs = dict(event.attributes or {})
        if event.type == TraceEventType.tool_call:
            steps.append(ToolStep(event.name, event.input, failed=event.status == EventStatus.error))
        elif event.type == TraceEventType.tool_result and event.status == EventStatus.error:
            for step in reversed(steps):
                if step.name == event.name and not step.failed:
                    step.failed = True
                    break
        elif event.type == TraceEventType.error:
            errors += 1
        elif event.type == TraceEventType.final_answer:
            final = True
        if event.type == TraceEventType.llm_call:
            tokens += _tokens_of(attrs)
        if isinstance(attrs.get("cost"), int | float):
            cost += float(attrs["cost"])
    finished = final or run.status in (
        RunStatus.completed,
        RunStatus.failed,
        RunStatus.cancelled,
        RunStatus.evaluating,
    )
    started = run.started_at or run.created_at
    elapsed = max(0.0, ((run.executed_at or utcnow()) - started).total_seconds() * 1000) if started else 0.0

    refs = (
        await session.execute(
            select(ExecutionTrace.total_latency_ms, ExecutionTrace.total_tokens)
            .join(EvaluationRun, EvaluationRun.id == ExecutionTrace.run_id)
            .where(
                EvaluationRun.agent_version_id == run.agent_version_id,
                EvaluationRun.status == RunStatus.completed,
                EvaluationRun.passed.is_(True),
            )
            .order_by(EvaluationRun.created_at.desc())
            .limit(REFERENCE_RUNS)
        )
    ).all()
    reference = Reference(
        n_runs=len(refs),
        latency_p95_ms=percentile([float(r[0]) for r in refs if r[0] is not None], 0.95),
        tokens_p95=percentile([float(r[1]) for r in refs if r[1] is not None], 0.95),
    )
    spec = specs_from_manifest(run.manifest).agent.budget
    risk = assess_risk(
        Progress(
            elapsed_ms=elapsed,
            tokens=tokens,
            cost=cost,
            tool_steps=steps,
            error_events=errors,
            has_final_answer=finished,
        ),
        reference,
        Budget(max_tokens=spec.max_tokens, max_cost=spec.max_cost, timeout_seconds=spec.timeout_seconds),
    )
    return {
        "run_id": run.id,
        "run_status": run.status.value,
        "level": risk.level,
        "score": risk.score,
        "finished": risk.finished,
        "signals": [asdict(s) for s in risk.signals],
        "observed": {
            "events": len(events),
            "tool_calls": len(steps),
            "tokens": tokens,
            "elapsed_ms": round(elapsed),
        },
        "reference_runs": reference.n_runs,
    }


async def release_health(
    session: AsyncSession,
    viewer: Viewer,
    release_id: str,
    *,
    baseline_release_id: str | None = None,
    days: int = 14,
) -> dict[str, Any]:
    """A release against its baseline (another release, or the runs without any release): same rules as
    agent health — a drop must be statistically significant *and* large enough, too few runs never alarm."""
    since = utcnow() - timedelta(days=days)

    async def stats(release: str | None) -> WindowStats:
        condition = EvaluationRun.release_id == release if release else EvaluationRun.release_id.is_(None)
        ids = list(
            await session.scalars(
                select(EvaluationRun.id)
                .where(
                    condition,
                    EvaluationRun.origin.in_(list(RELEASE_ORIGINS)),
                    EvaluationRun.status.in_(list(EVALUATED)),
                    EvaluationRun.created_at >= since,
                )
                .limit(MAX_RUNS)
            )
        )
        return summarize(await load_run_summaries(session, run_ids=ids, viewer=viewer) if ids else [])

    health = health_verdict(await stats(release_id), await stats(baseline_release_id))
    return {
        "release_id": release_id,
        "baseline_release_id": baseline_release_id,
        "days": days,
        "status": health.status,
        "reason": health.reason,
        "release": asdict(health.recent),
        "baseline": asdict(health.previous),
        "alerts": [asdict(a) for a in health.alerts],
    }

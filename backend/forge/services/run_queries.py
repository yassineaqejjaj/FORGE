"""Read side of evaluation runs (``/runs``): lists, Run Detail, trace, timeline, manifest, plus the
ad-hoc run creation / retry / cancellation wrappers (docs/ARCHITECTURE.md §3.3, §3.4, §6.2).

Runs of scenarios above the viewer's clearance are never revealed (``NotFoundError``); private
scenario content (scenario fields, agent input/output, trace payloads) is redacted for non-maintainers.
Labels come from the frozen manifest (what was actually evaluated), not from live rows.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import (
    TERMINAL_RUN_STATUSES,
    ExperimentArm,
    RunOrigin,
    RunStatus,
    ScenarioVisibility,
    TraceEventType,
    classification_warning,
)
from forge.domain.redaction import (
    REDACTED_TEXT,
    redact_event,
    redact_rules,
    redact_scenario_content,
)
from forge.domain.types import TraceEventView, to_dict
from forge.infra.models import (
    BenchmarkExecution,
    CompositeScore,
    EvaluationConfig,
    EvaluationRun,
    ExecutionTrace,
    Experiment,
    FeedbackReport,
    RunError,
    Scenario,
    ScenarioVersion,
    TraceEvent,
)
from forge.infra.models import Evaluation as EvaluationRow
from forge.infra.queue import PRIORITY_INTERACTIVE
from forge.services import access, audit, runs
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.taxonomy import ConflictError, InvalidError, NotFoundError

logger = logging.getLogger("forge.run_queries")

MAX_RUNS_PER_REQUEST = 500
RETRY_TAG_PREFIX = "retry-of:"
SORTS = ("created_at", "-created_at", "composite", "-composite", "latency", "-latency")

_M = EvaluationRun.manifest
SCENARIO_NAME = _M[("scenario", "name")].astext
SCENARIO_SLUG = _M[("scenario", "slug")].astext
SCENARIO_VERSION = _M[("scenario", "version")].astext
SCENARIO_CATEGORY = _M[("scenario", "category")].astext
SCENARIO_DIFFICULTY = _M[("scenario", "difficulty")].astext
AGENT_NAME = _M[("agent", "agent_name")].astext
AGENT_VERSION = _M[("agent", "version")].astext
AGENT_MODEL = _M[("agent", "model", "model")].astext


# =====================================================================================================
# Access
# =====================================================================================================


async def get_visible_run(
    session: AsyncSession, viewer: Viewer, run_id: uuid.UUID
) -> tuple[EvaluationRun, Scenario]:
    row = (
        await session.execute(
            select(EvaluationRun, Scenario)
            .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
            .where(EvaluationRun.id == run_id, access.classification_condition(viewer))
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Run introuvable")
    return row[0], row[1]


def run_visibility(run: EvaluationRun, scenario: Scenario | None = None) -> str:
    return access.manifest_visibility(run.manifest or {}) or (
        scenario.visibility.value if scenario else "public"
    )


def must_redact_run(viewer: Viewer, run: EvaluationRun, scenario: Scenario | None = None) -> bool:
    """Private if the scenario was private when the run was created *or* is private now."""
    private_now = scenario is not None and scenario.visibility == ScenarioVisibility.private
    return access.must_redact(viewer, run_visibility(run, scenario)) or (
        private_now and not viewer.can_see_private
    )


# =====================================================================================================
# Lists
# =====================================================================================================


@dataclass(slots=True)
class RunFilters:
    status: Sequence[RunStatus] = ()
    origin: RunOrigin | None = None
    agent_id: uuid.UUID | None = None
    agent_version_id: uuid.UUID | None = None
    scenario_id: uuid.UUID | None = None
    scenario_version_id: uuid.UUID | None = None
    benchmark_execution_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    arm: ExperimentArm | None = None
    passed: bool | None = None
    gate_failed: bool | None = None
    min_composite: float | None = None
    max_composite: float | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    tag: str | None = None
    external_id: str | None = None
    q: str | None = None


@dataclass(slots=True)
class RunRow:
    run: EvaluationRun
    scenario: Scenario
    latency_ms: float | None
    cost: float | None
    total_tokens: int | None


def _conditions(viewer: Viewer, f: RunFilters) -> list[Any]:
    c: list[Any] = [access.classification_condition(viewer)]
    if f.status:
        c.append(EvaluationRun.status.in_(list(f.status)))
    for column, value in (
        (EvaluationRun.origin, f.origin),
        (EvaluationRun.agent_id, f.agent_id),
        (EvaluationRun.agent_version_id, f.agent_version_id),
        (EvaluationRun.scenario_id, f.scenario_id),
        (EvaluationRun.scenario_version_id, f.scenario_version_id),
        (EvaluationRun.benchmark_execution_id, f.benchmark_execution_id),
        (EvaluationRun.experiment_id, f.experiment_id),
        (EvaluationRun.arm, f.arm),
    ):
        if value is not None:
            c.append(column == value)
    if f.passed is not None:
        c.append(EvaluationRun.passed.is_(f.passed))
    if f.gate_failed is not None:
        c.append(EvaluationRun.gate_failed.is_(f.gate_failed))
    if f.min_composite is not None:
        c.append(EvaluationRun.composite_score >= f.min_composite)
    if f.max_composite is not None:
        c.append(EvaluationRun.composite_score <= f.max_composite)
    if f.created_from is not None:
        c.append(EvaluationRun.created_at >= f.created_from)
    if f.created_to is not None:
        c.append(EvaluationRun.created_at <= f.created_to)
    if f.tag:
        c.append(EvaluationRun.tags.contains([f.tag]))
    if f.external_id:
        c.append(EvaluationRun.external_id == f.external_id)
    if f.q and f.q.strip():
        pattern = f"%{f.q.strip()}%"
        c.append(or_(SCENARIO_NAME.ilike(pattern), SCENARIO_SLUG.ilike(pattern), AGENT_NAME.ilike(pattern)))
    return c


async def list_runs(
    session: AsyncSession,
    viewer: Viewer,
    filters: RunFilters,
    *,
    sort: str = "-created_at",
    offset: int = 0,
    limit: int = 25,
    run_ids: Sequence[uuid.UUID] | None = None,
) -> tuple[list[RunRow], int]:
    if sort not in SORTS:
        raise InvalidError(f"Tri inconnu « {sort} » (attendu : {', '.join(SORTS)})")
    conditions = _conditions(viewer, filters)
    if run_ids is not None:
        conditions.append(EvaluationRun.id.in_(list(run_ids)))
    base = select(func.count(EvaluationRun.id)).join(Scenario, Scenario.id == EvaluationRun.scenario_id)
    total = await session.scalar(base.where(*conditions))
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    column: Any = {
        "created_at": EvaluationRun.created_at,
        "composite": EvaluationRun.composite_score,
        "latency": ExecutionTrace.total_latency_ms,
    }[key]
    order = column.desc().nulls_last() if descending else column.asc().nulls_last()
    rows = (
        await session.execute(
            select(
                EvaluationRun,
                Scenario,
                ExecutionTrace.total_latency_ms,
                ExecutionTrace.estimated_cost,
                ExecutionTrace.total_tokens,
            )
            .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
            .outerjoin(ExecutionTrace, ExecutionTrace.run_id == EvaluationRun.id)
            .where(*conditions)
            .order_by(order, EvaluationRun.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [RunRow(r, s, lat, cost, tok) for r, s, lat, cost, tok in rows], int(total or 0)


def run_summary(row: RunRow) -> dict[str, Any]:
    run, scenario = row.run, row.scenario
    manifest = run.manifest or {}
    s = manifest.get("scenario") or {}
    a = manifest.get("agent") or {}
    model = (a.get("model") or {}).get("model") if isinstance(a.get("model"), dict) else None
    return {
        "id": run.id,
        "status": run.status,
        "status_detail": run.status_detail,
        "origin": run.origin,
        "arm": run.arm,
        "repetition": run.repetition,
        "tags": list(run.tags or []),
        "external_id": run.external_id,
        "scenario_id": run.scenario_id,
        "scenario_version_id": run.scenario_version_id,
        "scenario_slug": s.get("slug") or scenario.slug,
        "scenario_name": s.get("name") or scenario.name,
        "scenario_version": s.get("version"),
        "category": s.get("category") or scenario.category,
        "difficulty": s.get("difficulty"),
        "visibility": s.get("visibility") or scenario.visibility.value,
        "classification": int(scenario.classification),
        "agent_id": run.agent_id,
        "agent_version_id": run.agent_version_id,
        "agent_name": a.get("agent_name"),
        "agent_version": a.get("version"),
        "agent_label": f"{a.get('agent_name')} v{a.get('version')}" if a.get("agent_name") else None,
        "model": model,
        "evaluation_config_id": run.evaluation_config_id,
        "evaluation_round": run.evaluation_round,
        "composite_score": run.composite_score,
        "passed": run.passed,
        "gate_failed": run.gate_failed,
        "error_type": run.error_type,
        "latency_ms": row.latency_ms,
        "cost": row.cost,
        "total_tokens": row.total_tokens,
        "benchmark_execution_id": run.benchmark_execution_id,
        "experiment_id": run.experiment_id,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


# =====================================================================================================
# Run detail
# =====================================================================================================


def scenario_content_view(
    viewer: Viewer, manifest_scenario: dict[str, Any], *, redact: bool
) -> dict[str, Any]:
    data = dict(manifest_scenario)
    if viewer.can_see_private:
        data["redacted"] = False
        return data
    data = redact_scenario_content(data, private=redact)
    data["canary"] = None
    return data


def agent_summary(agent: dict[str, Any]) -> dict[str, Any]:
    model = agent.get("model") if isinstance(agent.get("model"), dict) else None
    return {
        "agent_id": agent.get("agent_id"),
        "agent_version_id": agent.get("agent_version_id"),
        "name": agent.get("agent_name"),
        "slug": agent.get("agent_slug"),
        "version": agent.get("version"),
        "label": f"{agent.get('agent_name')} v{agent.get('version')}",
        "adapter_kind": agent.get("adapter_kind"),
        "endpoint": agent.get("endpoint"),
        "model": {
            k: model.get(k) for k in ("provider", "model", "model_version", "temperature", "max_tokens")
        }
        if model
        else None,
        "prompt_name": agent.get("prompt_name"),
        "prompt_version": agent.get("prompt_version"),
        "tools": [t.get("name") for t in agent.get("tools") or [] if isinstance(t, dict)],
        "tool_configuration": agent.get("tool_configuration"),
        "context_source": (agent.get("context_config") or {}).get("source") or "scenario",
        "budget": agent.get("budget") or {},
        "content_hash": agent.get("content_hash"),
    }


def config_summary(config: dict[str, Any], row: EvaluationConfig | None) -> dict[str, Any]:
    return {
        "id": config.get("config_id") or (str(row.id) if row else None),
        "key": config.get("key"),
        "version": config.get("version"),
        "name": config.get("name"),
        "pass_threshold": config.get("pass_threshold"),
        "dimension_weights": config.get("dimension_weights") or {},
        "use_human_scores": config.get("use_human_scores"),
        "aggregation": (config.get("aggregation") or {}).get("method"),
        "judges": [
            {k: j.get(k) for k in ("judge_id", "key", "version", "name", "provider", "model")}
            for j in config.get("judges") or []
            if isinstance(j, dict)
        ],
        "gates": [g.get("id") for g in config.get("gates") or [] if isinstance(g, dict)],
        "content_hash": config.get("content_hash"),
    }


def trace_summary(trace: ExecutionTrace | None, *, redact: bool) -> dict[str, Any] | None:
    if trace is None:
        return None
    return {
        "id": trace.id,
        "started_at": trace.started_at,
        "completed_at": trace.completed_at,
        "latency_ms": trace.total_latency_ms,
        "input_tokens": trace.input_tokens,
        "output_tokens": trace.output_tokens,
        "total_tokens": trace.total_tokens,
        "cost": trace.estimated_cost,
        "model_calls": trace.model_calls,
        "tool_calls": trace.tool_calls,
        "event_count": trace.event_count,
        "errors": [
            {
                "type": e.get("type"),
                "message": REDACTED_TEXT if redact else e.get("message"),
                "at": e.get("at"),
            }
            for e in trace.errors or []
            if isinstance(e, dict)
        ],
        "output_text": None if redact else trace.output_text,
        "output_json": None if redact else trace.output_json,
        "redacted": redact,
    }


async def run_detail(session: AsyncSession, viewer: Viewer, run_id: uuid.UUID) -> dict[str, Any]:
    run, scenario = await get_visible_run(session, viewer, run_id)
    redact = must_redact_run(viewer, run, scenario)
    manifest = run.manifest or {}
    s = manifest.get("scenario") or {}
    trace = await session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run.id))
    composite = await session.scalar(
        select(CompositeScore).where(
            CompositeScore.run_id == run.id,
            CompositeScore.round == run.evaluation_round,
            CompositeScore.evaluation_config_id == run.evaluation_config_id,
        )
    )
    round_cond = or_(EvaluationRow.round == run.evaluation_round, EvaluationRow.round.is_(None))
    evaluations = await session.scalar(
        select(func.count()).select_from(EvaluationRow).where(EvaluationRow.run_id == run.id, round_cond)
    )
    human = await session.scalar(
        select(func.count(func.distinct(EvaluationRow.human_user_id))).where(
            EvaluationRow.run_id == run.id, EvaluationRow.human_user_id.is_not(None)
        )
    )
    errors = await session.scalar(
        select(func.count())
        .select_from(RunError)
        .where(
            RunError.run_id == run.id, or_(RunError.round == run.evaluation_round, RunError.round.is_(None))
        )
    )
    feedback_id = await session.scalar(
        select(FeedbackReport.id)
        .where(FeedbackReport.run_id == run.id)
        .order_by(FeedbackReport.round.desc().nulls_last(), FeedbackReport.created_at.desc())
        .limit(1)
    )
    benchmark_id = None
    if run.benchmark_execution_id:
        benchmark_id = await session.scalar(
            select(BenchmarkExecution.benchmark_id).where(BenchmarkExecution.id == run.benchmark_execution_id)
        )
    experiment_name = None
    if run.experiment_id:
        experiment_name = await session.scalar(
            select(Experiment.name).where(Experiment.id == run.experiment_id)
        )
    config_row = await session.get(EvaluationConfig, run.evaluation_config_id)
    return {
        "id": run.id,
        "status": run.status,
        "status_detail": run.status_detail,
        "origin": run.origin,
        "arm": run.arm,
        "repetition": run.repetition,
        "tags": list(run.tags or []),
        "external_id": run.external_id,
        "error": (REDACTED_TEXT if redact and run.error else run.error),
        "error_type": run.error_type,
        "otel_trace_id": run.otel_trace_id,
        "manifest_hash": run.manifest_hash,
        "evaluation_round": run.evaluation_round,
        "composite_score": run.composite_score,
        "passed": run.passed,
        "gate_failed": run.gate_failed,
        "created_by": run.created_by,
        "created_at": run.created_at,
        "queued_at": run.queued_at,
        "started_at": run.started_at,
        "executed_at": run.executed_at,
        "evaluated_at": run.evaluated_at,
        "finished_at": run.finished_at,
        "redacted": redact,
        "scenario": {
            "id": run.scenario_id,
            "version_id": run.scenario_version_id,
            "slug": s.get("slug") or scenario.slug,
            "name": s.get("name") or scenario.name,
            "version": s.get("version"),
            "category": s.get("category") or scenario.category,
            "difficulty": s.get("difficulty"),
            "visibility": s.get("visibility") or scenario.visibility.value,
            "classification": int(scenario.classification),
            "classification_warning": classification_warning(int(scenario.classification)),
            "family_id": s.get("family_id") or str(scenario.family_id),
            "variant_label": s.get("variant_label"),
            "tags": s.get("tags") or [],
            "content": scenario_content_view(viewer, s, redact=redact),
        },
        "agent": agent_summary(manifest.get("agent") or {}),
        "evaluation_config": config_summary(manifest.get("evaluation") or {}, config_row),
        "trace": trace_summary(trace, redact=redact),
        "composite": {
            "round": composite.round,
            "value": composite.value,
            "raw_value": composite.raw_value,
            "passed": composite.passed,
            "gate_failed": composite.gate_failed,
            "dimensions": composite.dimensions,
            "gates": composite.gates,
            "missing_dimensions": composite.missing_dimensions,
            "formula": composite.formula,
        }
        if composite
        else None,
        "counts": {
            "evaluations": int(evaluations or 0),
            "errors": int(errors or 0),
            "human_evaluations": int(human or 0),
        },
        "feedback_report_id": feedback_id,
        "benchmark_execution_id": run.benchmark_execution_id,
        "benchmark_id": benchmark_id,
        "experiment_id": run.experiment_id,
        "experiment_name": experiment_name,
    }


# =====================================================================================================
# Trace, timeline, manifest
# =====================================================================================================


def _event_dict(event: TraceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "seq": event.seq,
        "parent_id": event.parent_id,
        "type": event.type,
        "name": event.name,
        "source": event.source,
        "status": event.status,
        "started_at": event.started_at,
        "ended_at": event.ended_at,
        "offset_ms": event.offset_ms,
        "duration_ms": event.duration_ms,
        "input": event.input,
        "output": event.output,
        "attributes": dict(event.attributes or {}),
        "span_id": event.span_id,
        "parent_span_id": event.parent_span_id,
        "redacted": False,
    }


async def _events(session: AsyncSession, run_id: uuid.UUID) -> list[TraceEvent]:
    return list(
        await session.scalars(select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.seq))
    )


def _derive(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Messages, tool calls (with their results) and model calls derived from the events."""
    messages, tool_calls, model_calls = [], [], []
    results_by_parent: dict[Any, dict[str, Any]] = {}
    for e in events:
        if e["type"] == TraceEventType.tool_result and e.get("parent_id"):
            results_by_parent[e["parent_id"]] = e
    pending_results = [
        e for e in events if e["type"] == TraceEventType.tool_result and not e.get("parent_id")
    ]
    for e in events:
        attrs = e.get("attributes") or {}
        if e["type"] in (TraceEventType.message, TraceEventType.final_answer):
            messages.append(
                {
                    "seq": e["seq"],
                    "role": attrs.get("role")
                    or ("assistant" if e["type"] == TraceEventType.final_answer else None),
                    "content": e.get("output") if e.get("output") is not None else e.get("input"),
                    "offset_ms": e["offset_ms"],
                    "redacted": e.get("redacted", False),
                }
            )
        elif e["type"] == TraceEventType.tool_call:
            result = results_by_parent.get(e["id"])
            if result is None:
                tool = attrs.get("tool") or e["name"]
                result = next(
                    (r for r in pending_results if (r.get("attributes") or {}).get("tool") == tool), None
                )
                if result is not None:
                    pending_results.remove(result)
            tool_calls.append(
                {
                    "seq": e["seq"],
                    "event_id": e["id"],
                    "tool": attrs.get("tool") or e["name"],
                    "arguments": attrs.get("arguments", e.get("input")),
                    "result": (result or {}).get("output") if result else e.get("output"),
                    "result_seq": result["seq"] if result else None,
                    "status": e["status"],
                    "duration_ms": e.get("duration_ms"),
                    "offset_ms": e["offset_ms"],
                    "redacted": e.get("redacted", False),
                }
            )
        elif e["type"] == TraceEventType.llm_call:
            model_calls.append(
                {
                    "seq": e["seq"],
                    "event_id": e["id"],
                    "model": attrs.get("model"),
                    "input_tokens": attrs.get("input_tokens"),
                    "output_tokens": attrs.get("output_tokens"),
                    "cost": attrs.get("cost"),
                    "duration_ms": e.get("duration_ms"),
                    "status": e["status"],
                    "offset_ms": e["offset_ms"],
                }
            )
    return messages, tool_calls, model_calls


async def run_trace(session: AsyncSession, viewer: Viewer, run_id: uuid.UUID) -> dict[str, Any]:
    run, scenario = await get_visible_run(session, viewer, run_id)
    redact = must_redact_run(viewer, run, scenario)
    trace = await session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run.id))
    events = [_event_dict(e) for e in await _events(session, run.id)]
    if redact:
        events = [redact_event(e) for e in events]
    messages, tool_calls, model_calls = _derive(events)
    summary = trace_summary(trace, redact=redact)
    if summary is not None and trace is not None:
        summary["input"] = None if redact else trace.input
        summary["messages"] = [] if redact else list(trace.messages or [])
        summary["metadata"] = {} if redact else dict(trace.metadata_ or {})
    if trace is not None and trace.messages and not redact:
        messages = list(trace.messages)
    return {
        "run_id": run.id,
        "status": run.status,
        "redacted": redact,
        "trace": summary,
        "events": events,
        "messages": messages,
        "tool_calls": tool_calls,
        "model_calls": model_calls,
    }


def _view(event: TraceEvent, *, redact: bool) -> TraceEventView:
    data = _event_dict(event)
    if redact:
        data = redact_event(data)
    return TraceEventView(
        id=str(event.id),
        seq=event.seq,
        type=event.type,
        name=event.name,
        offset_ms=event.offset_ms,
        duration_ms=event.duration_ms,
        status=event.status,
        input=data["input"],
        output=data["output"],
        attributes=data["attributes"],
        parent_id=str(event.parent_id) if event.parent_id else None,
    )


async def run_timeline(session: AsyncSession, viewer: Viewer, run_id: uuid.UUID) -> dict[str, Any]:
    run, scenario = await get_visible_run(session, viewer, run_id)
    redact = must_redact_run(viewer, run, scenario)
    views = [_view(e, redact=redact) for e in await _events(session, run.id)]
    try:
        from forge.domain.traces.timeline import build_timeline
    except ImportError:  # execution module not available: plain list
        build_timeline = None  # type: ignore[assignment]
    timeline: dict[str, Any]
    if build_timeline is not None:
        try:
            timeline = to_dict(build_timeline(views))
        except (TypeError, AttributeError, KeyError, ValueError):
            logger.warning(
                "build_timeline failed for run %s, falling back to a plain list", run.id, exc_info=True
            )
            timeline = {"items": [to_dict(v) for v in views]}
    else:
        timeline = {"items": [to_dict(v) for v in views]}
    if not isinstance(timeline, dict):
        timeline = {"items": timeline}
    timeline["run_id"] = str(run.id)
    timeline["redacted"] = redact
    return timeline


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_secrets(v) for k, v in value.items() if k != "credentials"}
    if isinstance(value, list):
        return [_strip_secrets(v) for v in value]
    return value


async def run_manifest(session: AsyncSession, viewer: Viewer, run_id: uuid.UUID) -> dict[str, Any]:
    """Full manifest for maintainers, redacted otherwise (private content, hidden rules, canary)."""
    run, scenario = await get_visible_run(session, viewer, run_id)
    manifest = _strip_secrets(dict(run.manifest or {}))
    if viewer.can_see_private:
        return {
            "run_id": str(run.id),
            "manifest_hash": run.manifest_hash,
            "redacted": False,
            "manifest": manifest,
        }
    redact = must_redact_run(viewer, run, scenario)
    manifest["scenario"] = redact_scenario_content(dict(manifest.get("scenario") or {}), private=redact)
    manifest["scenario"]["canary"] = None
    evaluation = dict(manifest.get("evaluation") or {})
    if "rules" in evaluation:
        evaluation["rules"] = redact_rules(list(evaluation.get("rules") or []), private=False)
    manifest["evaluation"] = evaluation
    return {"run_id": str(run.id), "manifest_hash": run.manifest_hash, "redacted": True, "manifest": manifest}


# =====================================================================================================
# Creation, retry, cancellation
# =====================================================================================================


@dataclass(slots=True)
class RunRequest:
    agent_version_id: uuid.UUID
    scenario_ids: Sequence[uuid.UUID] = ()
    scenario_version_ids: Sequence[uuid.UUID] = ()
    repetitions: int = 1
    evaluation_config_id: uuid.UUID | None = None
    tags: Sequence[str] = field(default_factory=list)


async def default_evaluation_config(session: AsyncSession) -> EvaluationConfig:
    config = await session.scalar(
        select(EvaluationConfig)
        .where(EvaluationConfig.is_default.is_(True), EvaluationConfig.is_latest.is_(True))
        .order_by(EvaluationConfig.created_at.desc())
        .limit(1)
    )
    if config is None:
        raise ConflictError("Aucune configuration d'évaluation par défaut (données de référence manquantes)")
    return config


async def resolve_config(session: AsyncSession, config_id: uuid.UUID | None) -> EvaluationConfig:
    if config_id is None:
        return await default_evaluation_config(session)
    config = await session.get(EvaluationConfig, config_id)
    if config is None:
        raise NotFoundError("Configuration d'évaluation introuvable")
    return config


async def create_adhoc_runs(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    request: RunRequest,
    *,
    created_by: uuid.UUID | None = None,
) -> list[EvaluationRun]:
    if not 1 <= request.repetitions <= 20:
        raise InvalidError("Le nombre de répétitions doit être compris entre 1 et 20")
    if not request.scenario_ids and not request.scenario_version_ids:
        raise InvalidError("Précisez au moins un scénario (scenario_ids ou scenario_version_ids)")
    version_ids: list[uuid.UUID] = []
    if request.scenario_ids:
        rows = (
            await session.execute(
                select(Scenario, ScenarioVersion.id)
                .outerjoin(
                    ScenarioVersion,
                    and_(
                        ScenarioVersion.scenario_id == Scenario.id,
                        ScenarioVersion.version == Scenario.latest_version,
                    ),
                )
                .where(Scenario.id.in_(list(request.scenario_ids)), access.classification_condition(viewer))
            )
        ).all()
        found = {s.id: v for s, v in rows}
        for sid in request.scenario_ids:
            if sid not in found or found[sid] is None:
                raise NotFoundError(f"Scénario {sid} introuvable")
            version_ids.append(found[sid])
    if request.scenario_version_ids:
        rows2 = (
            await session.execute(
                select(ScenarioVersion.id)
                .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
                .where(
                    ScenarioVersion.id.in_(list(request.scenario_version_ids)),
                    access.classification_condition(viewer),
                )
            )
        ).all()
        visible = {r[0] for r in rows2}
        for vid in request.scenario_version_ids:
            if vid not in visible:
                raise NotFoundError(f"Version de scénario {vid} introuvable")
            version_ids.append(vid)
    version_ids = list(dict.fromkeys(version_ids))
    total = len(version_ids) * request.repetitions
    if total > MAX_RUNS_PER_REQUEST:
        raise InvalidError(f"Trop de runs demandés ({total}) : maximum {MAX_RUNS_PER_REQUEST} par requête")
    config = await resolve_config(session, request.evaluation_config_id)
    plans = [
        runs.RunPlan(scenario_version_id=vid, agent_version_id=request.agent_version_id, repetition=rep)
        for vid in version_ids
        for rep in range(request.repetitions)
    ]
    tags = [t.strip() for t in request.tags if t and t.strip()]
    try:
        created = await runs.create_runs(
            session,
            plans,
            evaluation_config=config,
            origin=RunOrigin.adhoc,
            created_by=created_by,
            priority=PRIORITY_INTERACTIVE,
            tags=list(dict.fromkeys(tags)),
        )
    except runs.RunCreationError as exc:
        message = str(exc)
        if "introuvable" in message:
            raise NotFoundError(message) from exc
        raise InvalidError(message) from exc
    await audit.record(
        session,
        actor,
        "run.create",
        "evaluation_run",
        created[0].id if len(created) == 1 else None,
        summary=f"Lancement de {len(created)} run(s) ad hoc",
        details={
            "run_ids": [r.id for r in created],
            "agent_version_id": request.agent_version_id,
            "scenario_version_ids": version_ids,
            "repetitions": request.repetitions,
            "evaluation_config_id": config.id,
        },
    )
    return created


async def retry_run(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    run_id: uuid.UUID,
    *,
    created_by: uuid.UUID | None = None,
) -> EvaluationRun:
    run, _ = await get_visible_run(session, viewer, run_id)
    if run.origin == RunOrigin.observed:
        raise ConflictError("Un run observé ne peut pas être relancé : il a été exécuté hors de FORGE")
    if run.status not in TERMINAL_RUN_STATUSES:
        raise ConflictError("Le run est encore en cours : annulez-le ou attendez sa fin avant de le relancer")
    config = await session.get(EvaluationConfig, run.evaluation_config_id)
    assert config is not None
    tags = [t for t in run.tags or [] if not t.startswith(RETRY_TAG_PREFIX)] + [f"{RETRY_TAG_PREFIX}{run.id}"]
    try:
        (new_run,) = await runs.create_runs(
            session,
            [runs.RunPlan(run.scenario_version_id, run.agent_version_id, run.repetition)],
            evaluation_config=config,
            origin=RunOrigin.adhoc,
            created_by=created_by,
            priority=PRIORITY_INTERACTIVE,
            tags=tags,
        )
    except runs.RunCreationError as exc:
        raise InvalidError(str(exc)) from exc
    await audit.record(
        session,
        actor,
        "run.retry",
        "evaluation_run",
        new_run.id,
        summary=f"Relance du run {run.id}",
        details={"retry_of": run.id},
    )
    return new_run


async def cancel_run(
    session: AsyncSession, viewer: Viewer, actor: ActorLike, run_id: uuid.UUID
) -> EvaluationRun:
    run, _ = await get_visible_run(session, viewer, run_id)
    if run.status in TERMINAL_RUN_STATUSES:
        raise ConflictError("Le run est déjà terminé")
    await runs.cancel_runs(session, [run])
    await audit.record(
        session,
        actor,
        "run.cancel",
        "evaluation_run",
        run.id,
        summary=f"Annulation du run {run.id}",
    )
    return run

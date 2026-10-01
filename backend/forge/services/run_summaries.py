"""Flatten evaluated runs into ``RunSummary`` objects for the analytics domain (docs §9).

Four set-based queries whatever the number of runs (no N+1):

1. runs + execution trace metrics + labels extracted from the frozen manifest (JSONB paths, the
   manifest itself is never loaded);
2. composite scores of the **current round** (``composite_scores.round = run.evaluation_round``)
   for the run's own configuration (or ``evaluation_config_id`` when given);
3. criterion scores used in that composite;
4. classified errors of the current round plus execution errors (``round IS NULL``).

Labels (scenario name, category, difficulty, visibility, family, agent name/version, model) come
from the manifest so that later edits of a scenario or an agent never change past results.

Conventions: a ``failed`` run without a stored composite counts as ``0`` (a crash is a result,
docs §7.1); a ``cancelled`` run never has a composite.

The module also hosts the error types shared by the analytics services.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import ExperimentArm, RunStatus, ScenarioVisibility
from forge.domain.types import RunSummary
from forge.infra.models import CompositeScore, EvaluationRun, ExecutionTrace, RunError, Scenario, Score
from forge.services import access
from forge.services.access import Viewer

# --- Errors shared by the analytics services ------------------------------------------------------


class AnalyticsError(Exception):
    """Base class; the message is user-facing (French)."""


class AnalyticsNotFound(AnalyticsError):
    """→ 404"""


class AnalyticsConflict(AnalyticsError):
    """→ 409"""


class AnalyticsInvalid(AnalyticsError):
    """→ 422"""


# --- Loading ---------------------------------------------------------------------------------------


def run_filters(
    *,
    benchmark_execution_id: uuid.UUID | None = None,
    experiment_id: uuid.UUID | None = None,
    run_ids: Sequence[uuid.UUID] | None = None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if benchmark_execution_id is not None:
        filters.append(EvaluationRun.benchmark_execution_id == benchmark_execution_id)
    if experiment_id is not None:
        filters.append(EvaluationRun.experiment_id == experiment_id)
    if run_ids is not None:
        filters.append(EvaluationRun.id.in_(list(run_ids)))
    return filters


def _scoped(stmt: Select[Any], filters: Sequence[ColumnElement[bool]], viewer: Viewer | None) -> Select[Any]:
    if viewer is not None:
        stmt = stmt.join(Scenario, Scenario.id == EvaluationRun.scenario_id).where(
            access.classification_condition(viewer)
        )
    return stmt.where(*filters)


def _visibility(value: str | None) -> ScenarioVisibility:
    try:
        return ScenarioVisibility(value or "public")
    except ValueError:
        return ScenarioVisibility.public


async def load_run_summaries(
    session: AsyncSession,
    *,
    benchmark_execution_id: uuid.UUID | None = None,
    experiment_id: uuid.UUID | None = None,
    run_ids: Sequence[uuid.UUID] | None = None,
    evaluation_config_id: uuid.UUID | None = None,
    viewer: Viewer | None = None,
    conditions: Sequence[ColumnElement[bool]] = (),
) -> list[RunSummary]:
    """Runs matching every given filter, flattened (ordered by creation).

    ``viewer`` restricts to scenarios within its clearance; ``conditions`` are extra SQL conditions
    on ``EvaluationRun`` (date range, arm…). At least one filter is required.
    """
    filters = [
        *run_filters(
            benchmark_execution_id=benchmark_execution_id, experiment_id=experiment_id, run_ids=run_ids
        ),
        *conditions,
    ]
    if not filters:
        raise ValueError("load_run_summaries needs at least one filter")
    if run_ids is not None and not run_ids:
        return []

    manifest = EvaluationRun.manifest
    scenario = manifest["scenario"]
    agent = manifest["agent"]
    base = select(
        EvaluationRun.id,
        EvaluationRun.scenario_id,
        EvaluationRun.scenario_version_id,
        EvaluationRun.agent_id,
        EvaluationRun.agent_version_id,
        EvaluationRun.repetition,
        EvaluationRun.status,
        EvaluationRun.composite_score,
        EvaluationRun.passed,
        EvaluationRun.gate_failed,
        EvaluationRun.arm,
        EvaluationRun.created_at,
        EvaluationRun.evaluation_config_id,
        scenario["slug"].astext,
        scenario["name"].astext,
        scenario["family_id"].astext,
        scenario["category"].astext,
        scenario["difficulty"].astext,
        scenario["visibility"].astext,
        agent["agent_name"].astext,
        agent["version"].astext,
        agent["model"]["model"].astext,
        ExecutionTrace.estimated_cost,
        ExecutionTrace.total_latency_ms,
        ExecutionTrace.total_tokens,
    ).outerjoin(ExecutionTrace, ExecutionTrace.run_id == EvaluationRun.id)
    rows = (
        await session.execute(
            _scoped(base, filters, viewer).order_by(EvaluationRun.created_at, EvaluationRun.id)
        )
    ).all()
    if not rows:
        return []

    config_match = (
        CompositeScore.evaluation_config_id == evaluation_config_id
        if evaluation_config_id is not None
        else CompositeScore.evaluation_config_id == EvaluationRun.evaluation_config_id
    )
    composite_stmt = select(
        CompositeScore.run_id,
        CompositeScore.value,
        CompositeScore.passed,
        CompositeScore.gate_failed,
        CompositeScore.dimensions,
    ).join(
        EvaluationRun,
        and_(
            CompositeScore.run_id == EvaluationRun.id,
            CompositeScore.round == EvaluationRun.evaluation_round,
            config_match,
        ),
    )
    composites = {r[0]: r for r in (await session.execute(_scoped(composite_stmt, filters, viewer))).all()}

    score_config = (
        Score.evaluation_config_id == evaluation_config_id
        if evaluation_config_id is not None
        else Score.evaluation_config_id == EvaluationRun.evaluation_config_id
    )
    score_stmt = (
        select(Score.run_id, Score.criterion_key, Score.value)
        .join(
            EvaluationRun,
            and_(
                Score.run_id == EvaluationRun.id, Score.round == EvaluationRun.evaluation_round, score_config
            ),
        )
        .where(Score.used_in_composite.is_(True))
    )
    criteria: dict[uuid.UUID, dict[str, float]] = defaultdict(dict)
    for run_id, key, value in (await session.execute(_scoped(score_stmt, filters, viewer))).all():
        criteria[run_id][key] = float(value)

    error_stmt = (
        select(RunError.run_id, RunError.error_type, RunError.severity)
        .join(EvaluationRun, RunError.run_id == EvaluationRun.id)
        .where(or_(RunError.round.is_(None), RunError.round == EvaluationRun.evaluation_round))
        .order_by(RunError.created_at, RunError.id)
    )
    errors: dict[uuid.UUID, list[tuple[str, str]]] = defaultdict(list)
    for run_id, error_type, severity in (await session.execute(_scoped(error_stmt, filters, viewer))).all():
        errors[run_id].append((str(error_type), str(severity)))

    summaries: list[RunSummary] = []
    for row in rows:
        (
            run_id,
            scenario_id,
            scenario_version_id,
            agent_id,
            agent_version_id,
            repetition,
            status,
            run_composite,
            run_passed,
            run_gate_failed,
            arm,
            created_at,
            run_config_id,
            slug,
            name,
            family_id,
            category,
            difficulty,
            visibility,
            agent_name,
            agent_version,
            model,
            cost,
            latency,
            tokens,
        ) = row
        comp = composites.get(run_id)
        dimensions: dict[str, float] = {}
        if comp is not None:
            composite: float | None = float(comp[1])
            passed: bool | None = bool(comp[2])
            gate_failed = bool(comp[3])
            for item in comp[4] or []:
                if (
                    isinstance(item, dict)
                    and item.get("dimension") is not None
                    and item.get("value") is not None
                ):
                    dimensions[str(item["dimension"])] = float(item["value"])
        elif evaluation_config_id is None or evaluation_config_id == run_config_id:
            composite = float(run_composite) if run_composite is not None else None
            passed, gate_failed = run_passed, bool(run_gate_failed)
        else:
            composite, passed, gate_failed = None, None, False
        if status == RunStatus.cancelled:
            composite, passed = None, None
        elif status == RunStatus.failed and composite is None:
            composite, passed = 0.0, False
        summaries.append(
            RunSummary(
                run_id=str(run_id),
                scenario_id=str(scenario_id),
                scenario_version_id=str(scenario_version_id),
                scenario_slug=slug or "",
                scenario_name=name or slug or "",
                family_id=family_id or str(scenario_id),
                category=category or "",
                difficulty=difficulty or "",
                visibility=_visibility(visibility),
                agent_id=str(agent_id),
                agent_version_id=str(agent_version_id),
                agent_label=f"{agent_name or 'Agent'} v{agent_version or '?'}",
                model=model or None,
                repetition=int(repetition or 0),
                status=str(status.value if hasattr(status, "value") else status),
                composite=composite,
                passed=passed,
                gate_failed=gate_failed,
                dimensions=dimensions,
                criteria=criteria.get(run_id, {}),
                cost=float(cost) if cost is not None else None,
                latency_ms=float(latency) if latency is not None else None,
                tokens=int(tokens) if tokens is not None else None,
                errors=errors.get(run_id, []),
                arm=ExperimentArm(arm) if arm else None,
                created_at=created_at,
            )
        )
    return summaries

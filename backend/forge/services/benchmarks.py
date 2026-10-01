"""Benchmarks (docs/ARCHITECTURE.md §9.1): CRUD, launch, finalisation, results, cancellation.

A benchmark is a reusable definition (scenarios with an optional pinned version × agent versions
× repetitions + an evaluation configuration). Each launch creates a :class:`BenchmarkExecution`
with a sequential number and a frozen matrix, and materialises the N × M × K runs through
:func:`forge.services.runs.create_runs` (``origin=benchmark``, ``PRIORITY_BENCHMARK``). Runs are
created repetition by repetition, scenario by scenario, every agent version in turn: the queue
(FIFO within a priority) therefore makes all agent versions progress together, and a partial
execution stays comparable.

When every run is terminal, ``finalize_execution_job`` aggregates the runs
(:func:`forge.domain.benchmarks.aggregate_benchmark`) into ``execution.summary`` and asks the
evaluation module for one benchmark ``FeedbackReport`` per agent version.

Access: scenarios above the caller's clearance are never revealed. When an execution contains
such scenarios, its summary is recomputed on the fly from the visible runs only (``restricted``).
Services only flush; routers and job handlers commit.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.benchmarks import GROUP_BY_VALUES, aggregate_benchmark, error_breakdown, group_runs
from forge.domain.benchmarks.robustness import DEFAULT_ROBUSTNESS_MAX_STD
from forge.domain.enums import (
    TERMINAL_RUN_STATUSES,
    ExecutionStatus,
    FeedbackScope,
    RunOrigin,
    RunStatus,
)
from forge.domain.types import RunSummary, to_dict
from forge.infra.db import utcnow
from forge.infra.models import (
    Agent,
    AgentVersion,
    Benchmark,
    BenchmarkAgent,
    BenchmarkExecution,
    BenchmarkScenario,
    EvaluationConfig,
    EvaluationRun,
    FeedbackReport,
    Job,
    Scenario,
    ScenarioVersion,
)
from forge.infra.queue import PRIORITY_BENCHMARK
from forge.services import audit, runs
from forge.services.access import Viewer
from forge.services.audit import Actor, ActorLike
from forge.services.run_summaries import (
    AnalyticsConflict,
    AnalyticsInvalid,
    AnalyticsNotFound,
    load_run_summaries,
)

logger = logging.getLogger("forge.benchmarks")

ACTIVE_EXECUTION_STATUSES = (ExecutionStatus.queued, ExecutionStatus.running, ExecutionStatus.aggregating)
CANCELLABLE_STATUSES = (ExecutionStatus.draft, ExecutionStatus.queued, ExecutionStatus.running)


# =====================================================================================================
# Shared helpers (also used by experiments)
# =====================================================================================================


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:80] or "benchmark"


def parse_ref(ref: str | uuid.UUID) -> uuid.UUID | None:
    if isinstance(ref, uuid.UUID):
        return ref
    try:
        return uuid.UUID(str(ref))
    except ValueError:
        return None


@dataclass(slots=True)
class ScenarioSelection:
    scenario_id: uuid.UUID
    #: Pinned version; ``None`` = latest version at each launch.
    scenario_version_id: uuid.UUID | None = None


@dataclass(slots=True)
class ResolvedScenario:
    scenario: Scenario
    version: ScenarioVersion
    pinned: bool


async def resolve_scenarios(
    session: AsyncSession,
    selections: Sequence[ScenarioSelection],
    *,
    viewer: Viewer | None,
    allow_archived: bool = False,
) -> list[ResolvedScenario]:
    """Resolve the scenario version of each selection (pinned or latest), preserving order.

    Raises :class:`AnalyticsInvalid` for unknown / archived scenarios or a pinned version of
    another scenario. Scenarios above the viewer's clearance are reported as unknown.
    """
    if not selections:
        return []
    ids = list(dict.fromkeys(s.scenario_id for s in selections))
    if len(ids) != len(selections):
        raise AnalyticsInvalid("Un même scénario est sélectionné plusieurs fois")
    scenarios = {s.id: s for s in await session.scalars(select(Scenario).where(Scenario.id.in_(ids)))}
    pinned_ids = [s.scenario_version_id for s in selections if s.scenario_version_id]
    versions: dict[uuid.UUID, ScenarioVersion] = {}
    if pinned_ids:
        versions = {
            v.id: v
            for v in await session.scalars(select(ScenarioVersion).where(ScenarioVersion.id.in_(pinned_ids)))
        }
    latest_ids = [
        s.scenario_id for s in selections if not s.scenario_version_id and s.scenario_id in scenarios
    ]
    latest: dict[uuid.UUID, ScenarioVersion] = {}
    if latest_ids:
        rows = await session.scalars(
            select(ScenarioVersion)
            .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
            .where(
                ScenarioVersion.scenario_id.in_(latest_ids),
                ScenarioVersion.version == Scenario.latest_version,
            )
        )
        latest = {v.scenario_id: v for v in rows}
    resolved: list[ResolvedScenario] = []
    for selection in selections:
        scenario = scenarios.get(selection.scenario_id)
        if scenario is None or (viewer is not None and int(scenario.classification) > int(viewer.clearance)):
            raise AnalyticsInvalid(f"Scénario {selection.scenario_id} introuvable")
        if scenario.archived and not allow_archived:
            raise AnalyticsInvalid(f"Le scénario « {scenario.name} » est archivé")
        if selection.scenario_version_id:
            version = versions.get(selection.scenario_version_id)
            if version is None or version.scenario_id != scenario.id:
                raise AnalyticsInvalid(f"Version de scénario invalide pour « {scenario.name} »")
            resolved.append(ResolvedScenario(scenario, version, pinned=True))
        else:
            version = latest.get(scenario.id)
            if version is None:
                raise AnalyticsInvalid(f"Le scénario « {scenario.name} » n'a aucune version")
            resolved.append(ResolvedScenario(scenario, version, pinned=False))
    return resolved


async def agent_version_labels(
    session: AsyncSession, version_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """``{agent_version_id: {agent_id, agent_name, agent_slug, version, label, content_hash}}``."""
    if not version_ids:
        return {}
    rows = await session.execute(
        select(
            AgentVersion.id,
            AgentVersion.agent_id,
            Agent.name,
            Agent.slug,
            AgentVersion.version,
            AgentVersion.content_hash,
        )
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersion.id.in_(list(version_ids)))
    )
    return {
        row[0]: {
            "agent_version_id": row[0],
            "agent_id": row[1],
            "agent_name": row[2],
            "agent_slug": row[3],
            "version": row[4],
            "label": f"{row[2]} v{row[4]}",
            "content_hash": row[5],
        }
        for row in rows.all()
    }


async def require_agent_versions(
    session: AsyncSession, version_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    unique = list(dict.fromkeys(version_ids))
    if len(unique) != len(version_ids):
        raise AnalyticsInvalid("Une même version d'agent est sélectionnée plusieurs fois")
    labels = await agent_version_labels(session, unique)
    missing = [str(v) for v in unique if v not in labels]
    if missing:
        raise AnalyticsInvalid(f"Version(s) d'agent introuvable(s) : {', '.join(missing)}")
    return labels


async def resolve_config(session: AsyncSession, config_id: uuid.UUID | None) -> EvaluationConfig:
    if config_id is not None:
        config = await session.get(EvaluationConfig, config_id)
        if config is None:
            raise AnalyticsInvalid("Configuration d'évaluation introuvable")
        return config
    config = await session.scalar(
        select(EvaluationConfig)
        .where(EvaluationConfig.is_default.is_(True), EvaluationConfig.is_latest.is_(True))
        .order_by(EvaluationConfig.version.desc())
        .limit(1)
    )
    if config is None:
        raise AnalyticsInvalid("Aucune configuration d'évaluation par défaut n'est définie")
    return config


def robustness_max_std(config: EvaluationConfig | None) -> float:
    try:
        value = float((config.normalization or {}).get("robustness_max_std", DEFAULT_ROBUSTNESS_MAX_STD))  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_ROBUSTNESS_MAX_STD
    return value if value > 0 else DEFAULT_ROBUSTNESS_MAX_STD


def dimension_weights(config: EvaluationConfig | None) -> dict[str, float]:
    if config is None:
        return {}
    return {str(k): float(v) for k, v in (config.dimension_weights or {}).items()}


async def hidden_scenario_count(
    session: AsyncSession, viewer: Viewer, scenario_version_ids: Sequence[str]
) -> int:
    """Number of the given scenario versions whose scenario is above the viewer's clearance."""
    ids = [u for u in (parse_ref(v) for v in scenario_version_ids) if u is not None]
    if not ids:
        return 0
    count = await session.scalar(
        select(func.count())
        .select_from(ScenarioVersion)
        .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
        .where(ScenarioVersion.id.in_(ids), Scenario.classification > int(viewer.clearance))
    )
    return int(count or 0)


def user_id_of(actor: ActorLike) -> uuid.UUID | None:
    """User id behind a principal / actor (``None`` for API keys and the system)."""
    user_id = getattr(actor, "user_id", None)
    if isinstance(user_id, uuid.UUID):
        return user_id
    resolved = audit.resolve_actor(actor)
    return resolved.id if resolved.type.value == "user" else None


async def guarded_feedback(session: AsyncSession, **kwargs: Any) -> uuid.UUID | None:
    """Ask the evaluation module for an aggregate FeedbackReport without risking the aggregation."""
    from forge.services import feedback

    try:
        async with session.begin_nested():
            report = await feedback.create_aggregate_feedback(session, **kwargs)
    except NotImplementedError:
        logger.info("Aggregate feedback not available on this instance (%s)", kwargs.get("scope"))
        return None
    except Exception:
        logger.exception("Aggregate feedback failed (%s): aggregation kept", kwargs.get("scope"))
        return None
    report_id = getattr(report, "id", None)
    return report_id if isinstance(report_id, uuid.UUID) else None


def date_conditions(date_from: datetime | None, date_to: datetime | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if date_from is not None:
        conditions.append(EvaluationRun.created_at >= date_from)
    if date_to is not None:
        conditions.append(EvaluationRun.created_at <= date_to)
    return conditions


# =====================================================================================================
# Benchmarks CRUD
# =====================================================================================================


@dataclass(slots=True)
class BenchmarkListing:
    benchmark: Benchmark
    n_scenarios: int
    n_agents: int
    n_executions: int
    last_execution: BenchmarkExecution | None


@dataclass(slots=True)
class BenchmarkComposition:
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    agents: list[dict[str, Any]] = field(default_factory=list)
    hidden_scenarios: int = 0


async def get_benchmark(session: AsyncSession, ref: str | uuid.UUID) -> Benchmark:
    """Benchmark by id or slug."""
    benchmark_id = parse_ref(ref)
    benchmark = (
        await session.get(Benchmark, benchmark_id)
        if benchmark_id is not None
        else await session.scalar(select(Benchmark).where(Benchmark.slug == str(ref)))
    )
    if benchmark is None:
        raise AnalyticsNotFound("Benchmark introuvable")
    return benchmark


async def list_benchmarks(
    session: AsyncSession,
    *,
    search: str | None = None,
    archived: bool | None = False,
    tag: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[BenchmarkListing], int]:
    conditions: list[ColumnElement[bool]] = []
    if archived is not None:
        conditions.append(Benchmark.archived.is_(archived))
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Benchmark.name.ilike(pattern), Benchmark.slug.ilike(pattern)))
    if tag:
        conditions.append(Benchmark.tags.contains([tag]))
    total = await session.scalar(select(func.count()).select_from(Benchmark).where(*conditions))
    items = list(
        await session.scalars(
            select(Benchmark)
            .where(*conditions)
            .order_by(Benchmark.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return await _listings(session, items), int(total or 0)


async def _listings(session: AsyncSession, items: Sequence[Benchmark]) -> list[BenchmarkListing]:
    ids = [b.id for b in items]
    if not ids:
        return []
    n_scenarios = dict(
        (
            await session.execute(
                select(BenchmarkScenario.benchmark_id, func.count())
                .where(BenchmarkScenario.benchmark_id.in_(ids))
                .group_by(BenchmarkScenario.benchmark_id)
            )
        ).all()
    )
    n_agents = dict(
        (
            await session.execute(
                select(BenchmarkAgent.benchmark_id, func.count())
                .where(BenchmarkAgent.benchmark_id.in_(ids))
                .group_by(BenchmarkAgent.benchmark_id)
            )
        ).all()
    )
    n_exec = dict(
        (
            await session.execute(
                select(BenchmarkExecution.benchmark_id, func.count())
                .where(BenchmarkExecution.benchmark_id.in_(ids))
                .group_by(BenchmarkExecution.benchmark_id)
            )
        ).all()
    )
    latest_numbers = (
        select(BenchmarkExecution.benchmark_id, func.max(BenchmarkExecution.number).label("number"))
        .where(BenchmarkExecution.benchmark_id.in_(ids))
        .group_by(BenchmarkExecution.benchmark_id)
        .subquery()
    )
    last = {
        e.benchmark_id: e
        for e in await session.scalars(
            select(BenchmarkExecution).join(
                latest_numbers,
                (latest_numbers.c.benchmark_id == BenchmarkExecution.benchmark_id)
                & (latest_numbers.c.number == BenchmarkExecution.number),
            )
        )
    }
    return [
        BenchmarkListing(
            benchmark=b,
            n_scenarios=int(n_scenarios.get(b.id, 0)),
            n_agents=int(n_agents.get(b.id, 0)),
            n_executions=int(n_exec.get(b.id, 0)),
            last_execution=last.get(b.id),
        )
        for b in items
    ]


async def benchmark_listing(session: AsyncSession, benchmark: Benchmark) -> BenchmarkListing:
    return (await _listings(session, [benchmark]))[0]


async def benchmark_composition(
    session: AsyncSession, viewer: Viewer, benchmark: Benchmark
) -> BenchmarkComposition:
    """Scenarios (visible ones only, with their resolved version) and agent versions."""
    rows = (
        await session.execute(
            select(BenchmarkScenario, Scenario)
            .join(Scenario, Scenario.id == BenchmarkScenario.scenario_id)
            .where(BenchmarkScenario.benchmark_id == benchmark.id)
            .order_by(BenchmarkScenario.position, Scenario.name)
        )
    ).all()
    composition = BenchmarkComposition()
    pinned_ids = [bs.scenario_version_id for bs, _ in rows if bs.scenario_version_id]
    version_numbers: dict[uuid.UUID, int] = {}
    if pinned_ids:
        version_numbers = dict(
            (
                await session.execute(
                    select(ScenarioVersion.id, ScenarioVersion.version).where(
                        ScenarioVersion.id.in_(pinned_ids)
                    )
                )
            ).all()
        )
    for bs, scenario in rows:
        if int(scenario.classification) > int(viewer.clearance):
            composition.hidden_scenarios += 1
            continue
        composition.scenarios.append(
            {
                "scenario_id": scenario.id,
                "slug": scenario.slug,
                "name": scenario.name,
                "category": scenario.category,
                "visibility": scenario.visibility.value,
                "classification": int(scenario.classification),
                "archived": scenario.archived,
                "scenario_version_id": bs.scenario_version_id,
                "pinned_version": version_numbers.get(bs.scenario_version_id)
                if bs.scenario_version_id
                else None,
                "latest_version": scenario.latest_version,
                "position": bs.position,
            }
        )
    agent_rows = list(
        await session.scalars(
            select(BenchmarkAgent)
            .where(BenchmarkAgent.benchmark_id == benchmark.id)
            .order_by(BenchmarkAgent.position)
        )
    )
    labels = await agent_version_labels(session, [a.agent_version_id for a in agent_rows])
    for row in agent_rows:
        info = labels.get(row.agent_version_id)
        if info is not None:
            composition.agents.append({**info, "position": row.position})
    return composition


async def _unique_slug(session: AsyncSession, base: str, *, exclude: uuid.UUID | None = None) -> str:
    candidate, index = base, 1
    while True:
        conditions = [Benchmark.slug == candidate]
        if exclude is not None:
            conditions.append(Benchmark.id != exclude)
        if await session.scalar(select(Benchmark.id).where(*conditions)) is None:
            return candidate
        index += 1
        candidate = f"{base}-{index}"


def _clean_tags(tags: Sequence[str] | None) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in tags or [] if t and t.strip()))


async def _set_composition(
    session: AsyncSession,
    benchmark: Benchmark,
    *,
    scenarios: Sequence[ScenarioSelection] | None,
    agent_version_ids: Sequence[uuid.UUID] | None,
    viewer: Viewer,
) -> None:
    from sqlalchemy import delete

    if scenarios is not None:
        await resolve_scenarios(session, scenarios, viewer=viewer)
        await session.execute(delete(BenchmarkScenario).where(BenchmarkScenario.benchmark_id == benchmark.id))
        for position, selection in enumerate(scenarios):
            session.add(
                BenchmarkScenario(
                    benchmark_id=benchmark.id,
                    scenario_id=selection.scenario_id,
                    scenario_version_id=selection.scenario_version_id,
                    position=position,
                )
            )
    if agent_version_ids is not None:
        await require_agent_versions(session, agent_version_ids)
        await session.execute(delete(BenchmarkAgent).where(BenchmarkAgent.benchmark_id == benchmark.id))
        for position, version_id in enumerate(agent_version_ids):
            session.add(
                BenchmarkAgent(benchmark_id=benchmark.id, agent_version_id=version_id, position=position)
            )
    await session.flush()


async def create_benchmark(
    session: AsyncSession,
    actor: ActorLike,
    viewer: Viewer,
    *,
    name: str,
    scenarios: Sequence[ScenarioSelection],
    agent_version_ids: Sequence[uuid.UUID],
    slug: str | None = None,
    description: str = "",
    evaluation_config_id: uuid.UUID | None = None,
    repetitions: int = 1,
    tags: Sequence[str] = (),
) -> Benchmark:
    name = name.strip()
    if not name:
        raise AnalyticsInvalid("Le nom du benchmark est obligatoire")
    if not 1 <= repetitions <= 20:
        raise AnalyticsInvalid("Le nombre de répétitions doit être compris entre 1 et 20")
    config = await resolve_config(session, evaluation_config_id)
    if slug:
        slug = slugify(slug)
        if await session.scalar(select(Benchmark.id).where(Benchmark.slug == slug)) is not None:
            raise AnalyticsConflict(f"Un benchmark utilise déjà l'identifiant « {slug} »")
    else:
        slug = await _unique_slug(session, slugify(name))
    benchmark = Benchmark(
        slug=slug,
        name=name,
        description=description or "",
        evaluation_config_id=config.id,
        repetitions=repetitions,
        tags=_clean_tags(tags),
        created_by=user_id_of(actor),
    )
    session.add(benchmark)
    await session.flush()
    await _set_composition(
        session, benchmark, scenarios=scenarios, agent_version_ids=agent_version_ids, viewer=viewer
    )
    await audit.record(
        session,
        actor,
        "benchmark.create",
        "benchmark",
        benchmark.id,
        summary=f"Création du benchmark « {benchmark.name} »",
        details={
            "slug": benchmark.slug,
            "scenarios": len(scenarios),
            "agent_versions": [str(a) for a in agent_version_ids],
            "repetitions": repetitions,
            "evaluation_config_id": str(config.id),
        },
    )
    return benchmark


UPDATABLE_FIELDS = ("name", "description", "tags", "archived", "repetitions", "evaluation_config_id", "slug")


async def update_benchmark(
    session: AsyncSession, actor: ActorLike, viewer: Viewer, benchmark: Benchmark, changes: Mapping[str, Any]
) -> Benchmark:
    """Partial update. ``scenarios`` / ``agent_version_ids`` replace the composition; executions
    already launched keep their frozen matrix."""
    applied: dict[str, Any] = {}
    if "name" in changes and changes["name"] is not None:
        name = str(changes["name"]).strip()
        if not name:
            raise AnalyticsInvalid("Le nom du benchmark est obligatoire")
        benchmark.name = name
        applied["name"] = name
    if changes.get("slug"):
        slug = slugify(str(changes["slug"]))
        if slug != benchmark.slug:
            if await session.scalar(
                select(Benchmark.id).where(Benchmark.slug == slug, Benchmark.id != benchmark.id)
            ):
                raise AnalyticsConflict(f"Un benchmark utilise déjà l'identifiant « {slug} »")
            benchmark.slug = slug
            applied["slug"] = slug
    if "description" in changes and changes["description"] is not None:
        benchmark.description = str(changes["description"])
        applied["description"] = True
    if "tags" in changes and changes["tags"] is not None:
        benchmark.tags = _clean_tags(changes["tags"])
        applied["tags"] = benchmark.tags
    if "archived" in changes and changes["archived"] is not None:
        benchmark.archived = bool(changes["archived"])
        applied["archived"] = benchmark.archived
    if "repetitions" in changes and changes["repetitions"] is not None:
        repetitions = int(changes["repetitions"])
        if not 1 <= repetitions <= 20:
            raise AnalyticsInvalid("Le nombre de répétitions doit être compris entre 1 et 20")
        benchmark.repetitions = repetitions
        applied["repetitions"] = repetitions
    if "evaluation_config_id" in changes and changes["evaluation_config_id"] is not None:
        config = await resolve_config(session, changes["evaluation_config_id"])
        benchmark.evaluation_config_id = config.id
        applied["evaluation_config_id"] = str(config.id)
    scenarios = changes.get("scenarios")
    agents = changes.get("agent_version_ids")
    if scenarios is not None or agents is not None:
        await _set_composition(
            session, benchmark, scenarios=scenarios, agent_version_ids=agents, viewer=viewer
        )
        if scenarios is not None:
            applied["scenarios"] = len(scenarios)
        if agents is not None:
            applied["agent_version_ids"] = [str(a) for a in agents]
    benchmark.updated_at = utcnow()
    await session.flush()
    if applied:
        await audit.record(
            session,
            actor,
            "benchmark.update",
            "benchmark",
            benchmark.id,
            summary=f"Modification du benchmark « {benchmark.name} »",
            details={"changes": applied},
        )
    return benchmark


# =====================================================================================================
# Executions
# =====================================================================================================


async def launch_execution(
    session: AsyncSession,
    actor: ActorLike,
    viewer: Viewer,
    benchmark: Benchmark,
    *,
    trigger: str = "ui",
    enqueue: bool = True,
) -> BenchmarkExecution:
    """Create execution N+1 with its frozen matrix and the N × M × K runs."""
    locked = await session.scalar(select(Benchmark).where(Benchmark.id == benchmark.id).with_for_update())
    assert locked is not None
    if benchmark.archived:
        raise AnalyticsInvalid("Ce benchmark est archivé : désarchivez-le pour le lancer")
    selections = [
        ScenarioSelection(bs.scenario_id, bs.scenario_version_id)
        for bs in await session.scalars(
            select(BenchmarkScenario)
            .where(BenchmarkScenario.benchmark_id == benchmark.id)
            .order_by(BenchmarkScenario.position)
        )
    ]
    agent_ids = list(
        await session.scalars(
            select(BenchmarkAgent.agent_version_id)
            .where(BenchmarkAgent.benchmark_id == benchmark.id)
            .order_by(BenchmarkAgent.position)
        )
    )
    if not selections:
        raise AnalyticsInvalid("Ce benchmark ne contient aucun scénario")
    if not agent_ids:
        raise AnalyticsInvalid("Ce benchmark ne contient aucune version d'agent")
    try:
        resolved = await resolve_scenarios(session, selections, viewer=viewer)
    except AnalyticsInvalid as exc:
        raise AnalyticsInvalid(f"Lancement impossible : {exc}") from exc
    await require_agent_versions(session, agent_ids)
    total = len(resolved) * len(agent_ids) * benchmark.repetitions
    if total > settings.analytics_max_runs_per_launch:
        raise AnalyticsInvalid(
            f"Ce lancement créerait {total} runs (maximum {settings.analytics_max_runs_per_launch})"
        )
    config = await resolve_config(session, benchmark.evaluation_config_id)
    number = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(BenchmarkExecution.number), 0)).where(
                    BenchmarkExecution.benchmark_id == benchmark.id
                )
            )
            or 0
        )
        + 1
    )
    execution = BenchmarkExecution(
        benchmark_id=benchmark.id,
        number=number,
        status=ExecutionStatus.queued,
        evaluation_config_id=config.id,
        repetitions=benchmark.repetitions,
        matrix={
            "scenario_version_ids": [str(r.version.id) for r in resolved],
            "scenario_ids": [str(r.scenario.id) for r in resolved],
            "agent_version_ids": [str(a) for a in agent_ids],
            "repetitions": benchmark.repetitions,
            "pinned": [r.pinned for r in resolved],
        },
        total_runs=total,
        trigger=(trigger or "ui")[:40],
        triggered_by=user_id_of(actor),
    )
    session.add(execution)
    await session.flush()
    plans = [
        runs.RunPlan(scenario_version_id=r.version.id, agent_version_id=agent_id, repetition=rep)
        for rep in range(benchmark.repetitions)
        for r in resolved
        for agent_id in agent_ids
    ]
    try:
        created = await runs.create_runs(
            session,
            plans,
            evaluation_config=config,
            origin=RunOrigin.benchmark,
            benchmark_execution_id=execution.id,
            created_by=user_id_of(actor),
            priority=PRIORITY_BENCHMARK,
            tags=[f"benchmark:{benchmark.slug}", f"execution:{number}"],
            enqueue=enqueue,
        )
    except runs.RunCreationError as exc:
        raise AnalyticsInvalid(str(exc)) from exc
    execution.total_runs = len(created)
    execution.status = ExecutionStatus.running
    execution.started_at = utcnow()
    await session.flush()
    await audit.record(
        session,
        actor,
        "benchmark.run",
        "benchmark_execution",
        execution.id,
        summary=f"Lancement n° {number} du benchmark « {benchmark.name} » ({len(created)} runs)",
        details={
            "benchmark_id": str(benchmark.id),
            "number": number,
            "runs": len(created),
            "trigger": execution.trigger,
            "scenarios": len(resolved),
            "agent_versions": [str(a) for a in agent_ids],
            "repetitions": benchmark.repetitions,
            "evaluation_config_id": str(config.id),
        },
    )
    return execution


async def list_executions(
    session: AsyncSession, benchmark_id: uuid.UUID, *, offset: int = 0, limit: int = 25
) -> tuple[list[BenchmarkExecution], int]:
    total = await session.scalar(
        select(func.count())
        .select_from(BenchmarkExecution)
        .where(BenchmarkExecution.benchmark_id == benchmark_id)
    )
    items = list(
        await session.scalars(
            select(BenchmarkExecution)
            .where(BenchmarkExecution.benchmark_id == benchmark_id)
            .order_by(BenchmarkExecution.number.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return items, int(total or 0)


async def recent_executions(
    session: AsyncSession, *, limit: int = 5
) -> list[tuple[BenchmarkExecution, Benchmark]]:
    rows = await session.execute(
        select(BenchmarkExecution, Benchmark)
        .join(Benchmark, Benchmark.id == BenchmarkExecution.benchmark_id)
        .order_by(BenchmarkExecution.created_at.desc())
        .limit(limit)
    )
    return [(e, b) for e, b in rows.all()]


async def get_execution(session: AsyncSession, execution_id: uuid.UUID) -> BenchmarkExecution:
    execution = await session.get(BenchmarkExecution, execution_id)
    if execution is None:
        raise AnalyticsNotFound("Exécution de benchmark introuvable")
    return execution


def _summarize(summaries: Sequence[RunSummary], config: EvaluationConfig | None) -> dict[str, Any]:
    summary = aggregate_benchmark(
        summaries,
        dimension_weights=dimension_weights(config),
        robustness_max_std=robustness_max_std(config),
        n_resamples=settings.analytics_bootstrap_resamples,
    )
    return to_dict(summary)  # type: ignore[no-any-return]


async def execution_summary(
    session: AsyncSession, viewer: Viewer, execution: BenchmarkExecution
) -> dict[str, Any]:
    """Stored summary, or a summary restricted to the scenarios within the viewer's clearance."""
    hidden = await hidden_scenario_count(
        session, viewer, list((execution.matrix or {}).get("scenario_version_ids", []))
    )
    if not hidden:
        return dict(execution.summary or {})
    config = await session.get(EvaluationConfig, execution.evaluation_config_id)
    visible = await load_run_summaries(session, benchmark_execution_id=execution.id, viewer=viewer)
    data = _summarize(visible, config)
    data["restricted"] = True
    data["hidden_scenarios"] = hidden
    data["feedback_reports"] = {}
    return data


async def execution_feedback_reports(session: AsyncSession, execution_id: uuid.UUID) -> dict[str, str]:
    rows = await session.execute(
        select(FeedbackReport.agent_version_id, FeedbackReport.id)
        .where(
            FeedbackReport.benchmark_execution_id == execution_id,
            FeedbackReport.scope == FeedbackScope.benchmark,
        )
        .order_by(FeedbackReport.created_at)
    )
    return {str(av): str(rid) for av, rid in rows.all() if av is not None}


async def cancel_execution(session: AsyncSession, actor: ActorLike, execution: BenchmarkExecution) -> int:
    """Cancel an active execution: pending runs are cancelled, the partial results aggregated."""
    if execution.status not in CANCELLABLE_STATUSES:
        raise AnalyticsConflict("Cette exécution est déjà terminée")
    execution.status = ExecutionStatus.cancelled
    execution.finished_at = utcnow()
    await session.flush()
    active = list(
        await session.scalars(
            select(EvaluationRun).where(
                EvaluationRun.benchmark_execution_id == execution.id,
                EvaluationRun.status.not_in(list(TERMINAL_RUN_STATUSES)),
            )
        )
    )
    cancelled = await runs.cancel_runs(session, active)
    await audit.record(
        session,
        actor,
        "benchmark_execution.cancel",
        "benchmark_execution",
        execution.id,
        summary=f"Annulation de l'exécution n° {execution.number} ({cancelled} run(s) annulé(s))",
        details={"cancelled_runs": cancelled},
    )
    return cancelled


async def finalize_execution(session: AsyncSession, execution: BenchmarkExecution) -> dict[str, Any]:
    """Aggregate every run of the execution into ``summary`` and create the feedback reports."""
    config = await session.get(EvaluationConfig, execution.evaluation_config_id)
    summaries = await load_run_summaries(session, benchmark_execution_id=execution.id)
    data = _summarize(summaries, config)
    data["generated_at"] = utcnow().isoformat()
    existing = await execution_feedback_reports(session, execution.id)
    reports: dict[str, str] = {}
    for agent in data["agents"]:
        av_id = agent["agent_version_id"]
        if av_id in existing:
            reports[av_id] = existing[av_id]
            continue
        orm_runs = list(
            await session.scalars(
                select(EvaluationRun).where(
                    EvaluationRun.benchmark_execution_id == execution.id,
                    EvaluationRun.agent_version_id == uuid.UUID(av_id),
                    EvaluationRun.status != RunStatus.cancelled,
                )
            )
        )
        if not orm_runs:
            continue
        report_id = await guarded_feedback(
            session,
            scope=FeedbackScope.benchmark,
            runs=orm_runs,
            benchmark_execution_id=execution.id,
            agent_version_id=uuid.UUID(av_id),
        )
        if report_id is not None:
            reports[av_id] = str(report_id)
    data["feedback_reports"] = reports
    totals = data["totals"]
    execution.summary = data
    if execution.status != ExecutionStatus.cancelled:
        if totals["n_completed"] == 0:
            execution.status = ExecutionStatus.failed
            execution.error = (
                f"Aucun run n'a abouti ({totals['n_failed']} en échec, {totals['n_cancelled']} annulé(s))"
            )
        else:
            execution.status = ExecutionStatus.completed
            execution.error = None
    execution.finished_at = execution.finished_at or utcnow()
    await session.flush()
    leader = data["ranking"][0] if data["ranking"] else None
    await audit.record(
        session,
        Actor.system(),
        "benchmark_execution.finalize",
        "benchmark_execution",
        execution.id,
        summary=f"Agrégation de l'exécution n° {execution.number} ({totals['n_scored']} runs évalués)",
        details={
            "status": execution.status,
            "totals": totals,
            "feedback_reports": reports,
            "leader": leader
            and {
                "agent_version_id": leader["agent_version_id"],
                "group_composite": leader["group_composite"],
            },
        },
    )
    return data


async def finalize_execution_job(session: AsyncSession, job: Job) -> None:
    """Job handler ``finalize_execution`` (queue ``evaluation``)."""
    execution_id = parse_ref(str((job.payload or {}).get("id", "")))
    if execution_id is None:
        from forge.infra.queue import PermanentJobError

        raise PermanentJobError("Identifiant d'exécution manquant dans le job")
    execution = await session.scalar(
        select(BenchmarkExecution).where(BenchmarkExecution.id == execution_id).with_for_update()
    )
    if execution is None:
        logger.warning("Benchmark execution %s vanished before aggregation", execution_id)
        return
    await finalize_execution(session, execution)


# =====================================================================================================
# Results
# =====================================================================================================


async def benchmark_results(
    session: AsyncSession,
    viewer: Viewer,
    benchmark: Benchmark,
    *,
    execution_id: uuid.UUID | None = None,
    group_by: str = "version",
    visibility: str | None = None,
    category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Results of one execution (default: latest completed, else latest) grouped by ``group_by``."""
    if group_by not in GROUP_BY_VALUES:
        raise AnalyticsInvalid(f"Regroupement inconnu : {group_by} (attendu : {', '.join(GROUP_BY_VALUES)})")
    execution: BenchmarkExecution | None
    if execution_id is not None:
        execution = await get_execution(session, execution_id)
        if execution.benchmark_id != benchmark.id:
            raise AnalyticsNotFound("Exécution de benchmark introuvable")
    else:
        execution = await session.scalar(
            select(BenchmarkExecution)
            .where(BenchmarkExecution.benchmark_id == benchmark.id)
            .order_by(
                (BenchmarkExecution.status == ExecutionStatus.completed).desc(),
                BenchmarkExecution.number.desc(),
            )
            .limit(1)
        )
        if execution is None:
            raise AnalyticsNotFound("Ce benchmark n'a encore jamais été lancé")
    scenario = EvaluationRun.manifest["scenario"]
    conditions = date_conditions(date_from, date_to)
    if visibility:
        conditions.append(cast(scenario["visibility"].astext, String) == visibility)
    if category:
        conditions.append(cast(scenario["category"].astext, String) == category)
    summaries = await load_run_summaries(
        session, benchmark_execution_id=execution.id, viewer=viewer, conditions=conditions
    )
    rows = group_runs(summaries, group_by, with_ci=True, n_resamples=settings.analytics_bootstrap_resamples)
    hidden = await hidden_scenario_count(
        session, viewer, list((execution.matrix or {}).get("scenario_version_ids", []))
    )
    agents = {s.agent_version_id: s.agent_label for s in summaries}
    return {
        "benchmark_id": benchmark.id,
        "execution_id": execution.id,
        "execution_number": execution.number,
        "execution_status": execution.status.value,
        "group_by": group_by,
        "filters": {
            "visibility": visibility,
            "category": category,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        "n_runs": len(summaries),
        "restricted": hidden > 0,
        "agents": agents,
        "rows": [to_dict(r) for r in rows],
        "errors": [to_dict(e) for e in error_breakdown(summaries)],
    }

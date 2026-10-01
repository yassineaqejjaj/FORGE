"""Experiments (docs/ARCHITECTURE.md §9.3): baseline vs candidate on the same scenario versions.

* :func:`create_experiment` validates both agent versions, pins the scenario versions (from a
  benchmark — pinned or latest version — or from an explicit list) in ``experiment_scenarios``
  and launches the runs: K repetitions × scenarios × 2 arms, created in interleaved order (the
  arm that goes first alternates per scenario) so that both arms progress together through the
  queue and share the same conditions over time (``PRIORITY_EXPERIMENT``);
* ``finalize_experiment_job`` compares the arms (:func:`forge.domain.experiments.compare`),
  stores ``comparison`` + ``recommendation`` and asks the evaluation module for an experiment
  ``FeedbackReport`` on the candidate;
* :func:`experiment_gate` exposes the CI decision ``{passed, recommendation, reasons[]}``.

A warning is reported when baseline and candidate share the same content hash (any measured
difference is then pure noise). Scenarios above the caller's clearance are never revealed: the
comparison is recomputed from the visible runs only when the experiment includes such scenarios.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import (
    TERMINAL_RUN_STATUSES,
    ExecutionStatus,
    ExperimentArm,
    FeedbackScope,
    RunOrigin,
    RunStatus,
)
from forge.domain.experiments import compare, evaluate_gate
from forge.domain.types import RunSummary, to_dict
from forge.infra.db import utcnow
from forge.infra.models import (
    BenchmarkScenario,
    EvaluationConfig,
    EvaluationRun,
    Experiment,
    ExperimentScenario,
    FeedbackReport,
    Job,
    Scenario,
    ScenarioVersion,
)
from forge.infra.queue import PRIORITY_EXPERIMENT, PermanentJobError
from forge.services import audit, runs
from forge.services.access import Viewer
from forge.services.audit import Actor, ActorLike
from forge.services.benchmarks import (
    CANCELLABLE_STATUSES,
    ScenarioSelection,
    agent_version_labels,
    get_benchmark,
    guarded_feedback,
    parse_ref,
    require_agent_versions,
    resolve_config,
    resolve_scenarios,
    robustness_max_std,
    user_id_of,
)
from forge.services.run_summaries import (
    AnalyticsConflict,
    AnalyticsInvalid,
    AnalyticsNotFound,
    load_run_summaries,
)

logger = logging.getLogger("forge.experiments")

SAME_HASH_WARNING = (
    "La baseline et la candidate ont un contenu identique (même hash) : toute différence mesurée "
    "relève du bruit d'exécution."
)


@dataclass(slots=True)
class ExperimentListing:
    experiment: Experiment
    baseline: dict[str, Any] | None
    candidate: dict[str, Any] | None
    n_scenarios: int
    benchmark_name: str | None = None
    warnings: list[str] = field(default_factory=list)


# =====================================================================================================
# Queries
# =====================================================================================================


async def get_experiment(session: AsyncSession, experiment_id: uuid.UUID) -> Experiment:
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None:
        raise AnalyticsNotFound("Expérience introuvable")
    return experiment


def experiment_warnings(baseline: dict[str, Any] | None, candidate: dict[str, Any] | None) -> list[str]:
    warnings: list[str] = []
    if (
        baseline
        and candidate
        and baseline.get("content_hash")
        and baseline["content_hash"] == candidate.get("content_hash")
    ):
        warnings.append(SAME_HASH_WARNING)
    return warnings


async def _listings(session: AsyncSession, items: Sequence[Experiment]) -> list[ExperimentListing]:
    if not items:
        return []
    from forge.infra.models import Benchmark

    labels = await agent_version_labels(
        session, list({v for e in items for v in (e.baseline_version_id, e.candidate_version_id)})
    )
    ids = [e.id for e in items]
    n_scenarios = dict(
        (
            await session.execute(
                select(ExperimentScenario.experiment_id, func.count())
                .where(ExperimentScenario.experiment_id.in_(ids))
                .group_by(ExperimentScenario.experiment_id)
            )
        ).all()
    )
    bench_ids = [e.benchmark_id for e in items if e.benchmark_id]
    bench_names: dict[uuid.UUID, str] = {}
    if bench_ids:
        bench_names = dict(
            (
                await session.execute(select(Benchmark.id, Benchmark.name).where(Benchmark.id.in_(bench_ids)))
            ).all()
        )
    result = []
    for experiment in items:
        base = labels.get(experiment.baseline_version_id)
        cand = labels.get(experiment.candidate_version_id)
        result.append(
            ExperimentListing(
                experiment=experiment,
                baseline=base,
                candidate=cand,
                n_scenarios=int(n_scenarios.get(experiment.id, 0)),
                benchmark_name=bench_names.get(experiment.benchmark_id) if experiment.benchmark_id else None,
                warnings=experiment_warnings(base, cand),
            )
        )
    return result


async def experiment_listing(session: AsyncSession, experiment: Experiment) -> ExperimentListing:
    return (await _listings(session, [experiment]))[0]


async def list_experiments(
    session: AsyncSession,
    *,
    status: str | None = None,
    agent_version_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    benchmark_id: uuid.UUID | None = None,
    recommendation: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[ExperimentListing], int]:
    from forge.infra.models import AgentVersion

    conditions: list[ColumnElement[bool]] = []
    if status:
        conditions.append(Experiment.status == ExecutionStatus(status))
    if agent_version_id:
        conditions.append(
            or_(
                Experiment.baseline_version_id == agent_version_id,
                Experiment.candidate_version_id == agent_version_id,
            )
        )
    if agent_id:
        versions = select(AgentVersion.id).where(AgentVersion.agent_id == agent_id)
        conditions.append(
            or_(Experiment.baseline_version_id.in_(versions), Experiment.candidate_version_id.in_(versions))
        )
    if benchmark_id:
        conditions.append(Experiment.benchmark_id == benchmark_id)
    if recommendation:
        conditions.append(Experiment.recommendation == recommendation)
    if search:
        conditions.append(Experiment.name.ilike(f"%{search.strip()}%"))
    total = await session.scalar(select(func.count()).select_from(Experiment).where(*conditions))
    items = list(
        await session.scalars(
            select(Experiment)
            .where(*conditions)
            .order_by(Experiment.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return await _listings(session, items), int(total or 0)


async def experiment_scenarios(
    session: AsyncSession, viewer: Viewer, experiment: Experiment
) -> tuple[list[dict[str, Any]], int]:
    """Pinned scenario versions visible to the viewer, and the number of hidden ones."""
    rows = (
        await session.execute(
            select(ExperimentScenario, Scenario, ScenarioVersion.version)
            .join(Scenario, Scenario.id == ExperimentScenario.scenario_id)
            .join(ScenarioVersion, ScenarioVersion.id == ExperimentScenario.scenario_version_id)
            .where(ExperimentScenario.experiment_id == experiment.id)
            .order_by(ExperimentScenario.position)
        )
    ).all()
    visible: list[dict[str, Any]] = []
    hidden = 0
    for es, scenario, version in rows:
        if int(scenario.classification) > int(viewer.clearance):
            hidden += 1
            continue
        visible.append(
            {
                "scenario_id": scenario.id,
                "scenario_version_id": es.scenario_version_id,
                "version": version,
                "slug": scenario.slug,
                "name": scenario.name,
                "category": scenario.category,
                "visibility": scenario.visibility.value,
                "classification": int(scenario.classification),
                "position": es.position,
            }
        )
    return visible, hidden


# =====================================================================================================
# Creation & launch
# =====================================================================================================


async def create_experiment(
    session: AsyncSession,
    actor: ActorLike,
    viewer: Viewer,
    *,
    baseline_version_id: uuid.UUID,
    candidate_version_id: uuid.UUID,
    benchmark_id: uuid.UUID | str | None = None,
    scenario_ids: Sequence[uuid.UUID] | None = None,
    scenario_version_ids: Sequence[uuid.UUID] | None = None,
    evaluation_config_id: uuid.UUID | None = None,
    repetitions: int | None = None,
    name: str | None = None,
    description: str = "",
    hypothesis: str = "",
    tags: Sequence[str] = (),
    source_feedback_report_id: uuid.UUID | None = None,
    trigger: str = "ui",
    enqueue: bool = True,
) -> Experiment:
    """Create and launch an experiment (status ``running`` once its runs are created)."""
    if baseline_version_id == candidate_version_id:
        raise AnalyticsInvalid("La baseline et la candidate doivent être deux versions différentes")
    labels = await require_agent_versions(session, [baseline_version_id, candidate_version_id])
    benchmark = await get_benchmark(session, benchmark_id) if benchmark_id else None
    if benchmark is not None and benchmark.archived:
        raise AnalyticsInvalid("Ce benchmark est archivé")

    selections: list[ScenarioSelection] = []
    if scenario_version_ids:
        version_rows = {
            v.id: v
            for v in await session.scalars(
                select(ScenarioVersion).where(ScenarioVersion.id.in_(list(scenario_version_ids)))
            )
        }
        for version_id in scenario_version_ids:
            version = version_rows.get(version_id)
            if version is None:
                raise AnalyticsInvalid(f"Version de scénario {version_id} introuvable")
            selections.append(ScenarioSelection(version.scenario_id, version.id))
    if scenario_ids:
        selections += [ScenarioSelection(sid) for sid in scenario_ids]
    if benchmark is not None and not selections:
        selections = [
            ScenarioSelection(bs.scenario_id, bs.scenario_version_id)
            for bs in await session.scalars(
                select(BenchmarkScenario)
                .where(BenchmarkScenario.benchmark_id == benchmark.id)
                .order_by(BenchmarkScenario.position)
            )
        ]
    if not selections:
        raise AnalyticsInvalid("Indiquez un benchmark ou au moins un scénario")
    resolved = await resolve_scenarios(session, selections, viewer=viewer)
    config = await resolve_config(
        session, evaluation_config_id or (benchmark.evaluation_config_id if benchmark is not None else None)
    )
    reps = repetitions if repetitions is not None else (benchmark.repetitions if benchmark is not None else 1)
    if not 1 <= reps <= 20:
        raise AnalyticsInvalid("Le nombre de répétitions doit être compris entre 1 et 20")
    total = len(resolved) * 2 * reps
    if total > settings.analytics_max_runs_per_launch:
        raise AnalyticsInvalid(
            f"Cette expérience créerait {total} runs (maximum {settings.analytics_max_runs_per_launch})"
        )
    if (
        source_feedback_report_id is not None
        and await session.get(FeedbackReport, source_feedback_report_id) is None
    ):
        raise AnalyticsInvalid("Rapport de feedback source introuvable")

    base_info, cand_info = labels[baseline_version_id], labels[candidate_version_id]
    experiment = Experiment(
        name=(name or "").strip() or f"{base_info['label']} → {cand_info['label']}",
        description=description or "",
        hypothesis=hypothesis or "",
        baseline_version_id=baseline_version_id,
        candidate_version_id=candidate_version_id,
        benchmark_id=benchmark.id if benchmark is not None else None,
        evaluation_config_id=config.id,
        repetitions=reps,
        status=ExecutionStatus.queued,
        total_runs=total,
        source_feedback_report_id=source_feedback_report_id,
        tags=list(dict.fromkeys(t.strip() for t in tags if t and t.strip())),
        trigger=(trigger or "ui")[:40],
        created_by=user_id_of(actor),
    )
    session.add(experiment)
    await session.flush()
    for position, item in enumerate(resolved):
        session.add(
            ExperimentScenario(
                experiment_id=experiment.id,
                scenario_version_id=item.version.id,
                scenario_id=item.scenario.id,
                position=position,
            )
        )
    await session.flush()

    plans: list[runs.RunPlan] = []
    for rep in range(reps):
        for index, item in enumerate(resolved):
            arms = [
                (ExperimentArm.baseline, baseline_version_id),
                (ExperimentArm.candidate, candidate_version_id),
            ]
            if (index + rep) % 2:
                arms.reverse()
            plans += [
                runs.RunPlan(
                    scenario_version_id=item.version.id, agent_version_id=av, repetition=rep, arm=arm
                )
                for arm, av in arms
            ]
    try:
        created = await runs.create_runs(
            session,
            plans,
            evaluation_config=config,
            origin=RunOrigin.experiment,
            experiment_id=experiment.id,
            created_by=user_id_of(actor),
            priority=PRIORITY_EXPERIMENT,
            tags=[f"experiment:{experiment.id}"],
            enqueue=enqueue,
        )
    except runs.RunCreationError as exc:
        raise AnalyticsInvalid(str(exc)) from exc
    experiment.total_runs = len(created)
    experiment.status = ExecutionStatus.running
    experiment.started_at = utcnow()
    await session.flush()
    warnings = experiment_warnings(base_info, cand_info)
    await audit.record(
        session,
        actor,
        "experiment.create",
        "experiment",
        experiment.id,
        summary=f"Expérience « {experiment.name} » lancée ({len(created)} runs)",
        details={
            "baseline_version_id": str(baseline_version_id),
            "candidate_version_id": str(candidate_version_id),
            "benchmark_id": str(benchmark.id) if benchmark else None,
            "scenarios": len(resolved),
            "repetitions": reps,
            "evaluation_config_id": str(config.id),
            "trigger": experiment.trigger,
            "warnings": warnings,
        },
    )
    return experiment


async def cancel_experiment(session: AsyncSession, actor: ActorLike, experiment: Experiment) -> int:
    if experiment.status not in CANCELLABLE_STATUSES:
        raise AnalyticsConflict("Cette expérience est déjà terminée")
    experiment.status = ExecutionStatus.cancelled
    experiment.finished_at = utcnow()
    await session.flush()
    active = list(
        await session.scalars(
            select(EvaluationRun).where(
                EvaluationRun.experiment_id == experiment.id,
                EvaluationRun.status.not_in(list(TERMINAL_RUN_STATUSES)),
            )
        )
    )
    cancelled = await runs.cancel_runs(session, active)
    await audit.record(
        session,
        actor,
        "experiment.cancel",
        "experiment",
        experiment.id,
        summary=f"Annulation de l'expérience « {experiment.name} » ({cancelled} run(s) annulé(s))",
        details={"cancelled_runs": cancelled},
    )
    return cancelled


# =====================================================================================================
# Comparison
# =====================================================================================================


def _compare(
    summaries: Sequence[RunSummary], config: EvaluationConfig | None, warnings: Sequence[str]
) -> dict[str, Any]:
    baseline = [s for s in summaries if s.arm == ExperimentArm.baseline]
    candidate = [s for s in summaries if s.arm == ExperimentArm.candidate]
    result = compare(
        baseline,
        candidate,
        robustness_max_std=robustness_max_std(config),
        n_resamples=settings.analytics_bootstrap_resamples,
        warnings=warnings,
    )
    return to_dict(result)  # type: ignore[no-any-return]


async def _warnings_for(session: AsyncSession, experiment: Experiment) -> list[str]:
    labels = await agent_version_labels(
        session, [experiment.baseline_version_id, experiment.candidate_version_id]
    )
    return experiment_warnings(
        labels.get(experiment.baseline_version_id), labels.get(experiment.candidate_version_id)
    )


async def finalize_experiment(session: AsyncSession, experiment: Experiment) -> dict[str, Any]:
    config = await session.get(EvaluationConfig, experiment.evaluation_config_id)
    summaries = await load_run_summaries(session, experiment_id=experiment.id)
    data = _compare(summaries, config, await _warnings_for(session, experiment))
    data["generated_at"] = utcnow().isoformat()
    report_id = await session.scalar(
        select(FeedbackReport.id).where(
            FeedbackReport.experiment_id == experiment.id, FeedbackReport.scope == FeedbackScope.experiment
        )
    )
    if report_id is None:
        candidate_runs = list(
            await session.scalars(
                select(EvaluationRun).where(
                    EvaluationRun.experiment_id == experiment.id,
                    EvaluationRun.arm == ExperimentArm.candidate,
                    EvaluationRun.status != RunStatus.cancelled,
                )
            )
        )
        if candidate_runs:
            report_id = await guarded_feedback(
                session,
                scope=FeedbackScope.experiment,
                runs=candidate_runs,
                experiment_id=experiment.id,
                agent_version_id=experiment.candidate_version_id,
            )
    data["feedback_report_id"] = str(report_id) if report_id else None
    experiment.comparison = data
    experiment.recommendation = data["recommendation"]["recommendation"]
    n_completed = sum(1 for s in summaries if s.status == RunStatus.completed)
    if experiment.status != ExecutionStatus.cancelled:
        if n_completed == 0:
            experiment.status = ExecutionStatus.failed
            experiment.error = "Aucun run n'a abouti : comparaison impossible"
        else:
            experiment.status = ExecutionStatus.completed
            experiment.error = None
    experiment.finished_at = experiment.finished_at or utcnow()
    await session.flush()
    await audit.record(
        session,
        Actor.system(),
        "experiment.finalize",
        "experiment",
        experiment.id,
        summary=f"Comparaison de l'expérience « {experiment.name} » : {data['recommendation']['label']}",
        details={
            "status": experiment.status,
            "recommendation": experiment.recommendation,
            "confidence": data["recommendation"]["confidence"],
            "composite_delta": data["composite"]["delta"],
            "regressions": len(data["regressions"]),
            "feedback_report_id": data["feedback_report_id"],
        },
    )
    return data


async def finalize_experiment_job(session: AsyncSession, job: Job) -> None:
    """Job handler ``finalize_experiment`` (queue ``evaluation``)."""
    experiment_id = parse_ref(str((job.payload or {}).get("id", "")))
    if experiment_id is None:
        raise PermanentJobError("Identifiant d'expérience manquant dans le job")
    experiment = await session.scalar(
        select(Experiment).where(Experiment.id == experiment_id).with_for_update()
    )
    if experiment is None:
        logger.warning("Experiment %s vanished before comparison", experiment_id)
        return
    await finalize_experiment(session, experiment)


async def experiment_comparison(
    session: AsyncSession, viewer: Viewer, experiment: Experiment
) -> dict[str, Any]:
    """Stored comparison, recomputed from visible runs when hidden scenarios are involved.

    Before the experiment is finalised, a provisional comparison of the runs already evaluated is
    computed on the fly (``provisional: true``).
    """
    _, hidden = await experiment_scenarios(session, viewer, experiment)
    stored = dict(experiment.comparison or {})
    if stored and not hidden:
        stored.setdefault("provisional", False)
        return stored
    config = await session.get(EvaluationConfig, experiment.evaluation_config_id)
    summaries = await load_run_summaries(
        session, experiment_id=experiment.id, viewer=viewer if hidden else None
    )
    data = _compare(summaries, config, await _warnings_for(session, experiment))
    data["provisional"] = not stored
    data["feedback_report_id"] = stored.get("feedback_report_id")
    if hidden:
        data["restricted"] = True
        data["hidden_scenarios"] = hidden
        data["warnings"] = [
            *data.get("warnings", []),
            f"{hidden} scénario(s) hors de votre habilitation exclu(s) de cette vue.",
        ]
    return data


async def experiment_gate(
    session: AsyncSession, viewer: Viewer, experiment: Experiment, *, strict: bool = False
) -> dict[str, Any]:
    """CI decision ``{passed, recommendation, status, reasons[]}``."""
    status = experiment.status.value
    if status != ExecutionStatus.completed:
        decision = evaluate_gate(status=status, recommendation=experiment.recommendation, strict=strict)
        return {**to_dict(decision), "experiment_id": experiment.id}
    comparison = await experiment_comparison(session, viewer, experiment)
    recommendation = comparison.get("recommendation") or {}
    decision = evaluate_gate(
        status=status,
        recommendation=recommendation.get("recommendation"),
        regressions=comparison.get("regressions") or [],
        summary=recommendation.get("summary"),
        confidence=recommendation.get("confidence"),
        strict=strict,
    )
    result = to_dict(decision)
    if comparison.get("restricted"):
        result["reasons"].append("Décision calculée sur les seuls scénarios de votre habilitation.")
    result["experiment_id"] = experiment.id
    result["composite_delta"] = (comparison.get("composite") or {}).get("delta")
    result["regressions"] = len(comparison.get("regressions") or [])
    return result  # type: ignore[no-any-return]


async def recent_experiments(session: AsyncSession, *, limit: int = 5) -> list[ExperimentListing]:
    items = list(
        await session.scalars(select(Experiment).order_by(Experiment.created_at.desc()).limit(limit))
    )
    return await _listings(session, items)

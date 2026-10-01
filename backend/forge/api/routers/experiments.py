"""Router ``experiments``: baseline vs candidate, comparison, CI gate (docs §9.3, §12)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from forge.api.deps import RequireEditor, RequireViewer, SessionDep
from forge.api.routers.benchmarks import Paging, analytics_errors
from forge.api.schemas.common import Page
from forge.api.schemas.experiments import (
    ComparisonOut,
    ExperimentCreateIn,
    ExperimentDetailOut,
    ExperimentOut,
    GateOut,
)
from forge.domain.enums import ExecutionStatus, Recommendation
from forge.domain.experiments import RECOMMENDATION_LABELS
from forge.infra.models import Experiment
from forge.services import experiments as service

router = APIRouter(prefix="/experiments", tags=["experiments"])


def _experiment(listing: service.ExperimentListing) -> dict[str, Any]:
    e = listing.experiment
    recommendation = (e.comparison or {}).get("recommendation") or {}
    done = e.completed_runs + e.failed_runs
    return {
        "id": e.id,
        "name": e.name,
        "description": e.description,
        "hypothesis": e.hypothesis,
        "status": e.status,
        "baseline": listing.baseline,
        "candidate": listing.candidate,
        "baseline_version_id": e.baseline_version_id,
        "candidate_version_id": e.candidate_version_id,
        "benchmark_id": e.benchmark_id,
        "benchmark_name": listing.benchmark_name,
        "evaluation_config_id": e.evaluation_config_id,
        "repetitions": e.repetitions,
        "n_scenarios": listing.n_scenarios,
        "total_runs": e.total_runs,
        "completed_runs": e.completed_runs,
        "failed_runs": e.failed_runs,
        "progress": min(1.0, done / e.total_runs) if e.total_runs else 0.0,
        "recommendation": e.recommendation,
        "recommendation_label": RECOMMENDATION_LABELS.get(e.recommendation) if e.recommendation else None,
        "confidence": recommendation.get("confidence"),
        "composite_delta": ((e.comparison or {}).get("composite") or {}).get("delta"),
        "source_feedback_report_id": e.source_feedback_report_id,
        "tags": list(e.tags or []),
        "trigger": e.trigger,
        "error": e.error,
        "warnings": listing.warnings,
        "created_by": e.created_by,
        "created_at": e.created_at,
        "started_at": e.started_at,
        "finished_at": e.finished_at,
    }


async def _detail(
    session: SessionDep, principal: RequireViewer, experiment: Experiment
) -> ExperimentDetailOut:
    listing = await service.experiment_listing(session, experiment)
    scenarios, hidden = await service.experiment_scenarios(session, principal, experiment)
    data = _experiment(listing)
    data["n_scenarios"] = len(scenarios)
    summary = ((experiment.comparison or {}).get("recommendation") or {}).get("summary")
    if hidden:
        # The stored sentence may name scenarios above the caller's clearance.
        comparison = await service.experiment_comparison(session, principal, experiment)
        summary = (comparison.get("recommendation") or {}).get("summary") if experiment.comparison else None
    return ExperimentDetailOut(**data, scenarios=scenarios, hidden_scenarios=hidden, summary=summary)  # type: ignore[arg-type]


@router.get("", response_model=Page[ExperimentOut], summary="Lister les expériences")
async def list_experiments(
    session: SessionDep,
    principal: RequireViewer,
    page: Paging,
    status_filter: Annotated[ExecutionStatus | None, Query(alias="status")] = None,
    agent_id: uuid.UUID | None = None,
    agent_version_id: uuid.UUID | None = None,
    benchmark_id: uuid.UUID | None = None,
    recommendation: Recommendation | None = None,
    search: str | None = None,
) -> Page[ExperimentOut]:
    items, total = await service.list_experiments(
        session,
        status=status_filter.value if status_filter else None,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        benchmark_id=benchmark_id,
        recommendation=recommendation.value if recommendation else None,
        search=search,
        offset=page.offset,
        limit=page.page_size,
    )
    return Page(
        items=[ExperimentOut(**_experiment(i)) for i in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post(
    "",
    response_model=ExperimentDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer et lancer une expérience baseline / candidate",
)
async def create_experiment(
    body: ExperimentCreateIn, session: SessionDep, principal: RequireEditor
) -> ExperimentDetailOut:
    with analytics_errors():
        experiment = await service.create_experiment(
            session,
            principal,
            principal,
            baseline_version_id=body.baseline_version_id,
            candidate_version_id=body.candidate_version_id,
            benchmark_id=body.benchmark_id,
            scenario_ids=body.scenario_ids,
            scenario_version_ids=body.scenario_version_ids,
            evaluation_config_id=body.evaluation_config_id,
            repetitions=body.repetitions,
            name=body.name,
            description=body.description,
            hypothesis=body.hypothesis,
            tags=body.tags,
            source_feedback_report_id=body.source_feedback_report_id,
            trigger=body.trigger,
        )
    await session.commit()
    return await _detail(session, principal, experiment)


@router.get("/{experiment_id}", response_model=ExperimentDetailOut, summary="Détail d'une expérience")
async def get_experiment(
    experiment_id: uuid.UUID, session: SessionDep, principal: RequireViewer
) -> ExperimentDetailOut:
    with analytics_errors():
        experiment = await service.get_experiment(session, experiment_id)
    return await _detail(session, principal, experiment)


@router.get(
    "/{experiment_id}/comparison",
    response_model=ComparisonOut,
    summary="Comparaison appariée : deltas, IC, p-values, verdicts, régressions, recommandation",
)
async def get_comparison(
    experiment_id: uuid.UUID, session: SessionDep, principal: RequireViewer
) -> ComparisonOut:
    with analytics_errors():
        experiment = await service.get_experiment(session, experiment_id)
        data = await service.experiment_comparison(session, principal, experiment)
    return ComparisonOut.model_validate({**data, "experiment_id": experiment.id, "status": experiment.status})


@router.get(
    "/{experiment_id}/gate",
    response_model=GateOut,
    summary="Garde-fou CI : {passed, recommendation, reasons[]}",
)
async def get_gate(
    experiment_id: uuid.UUID,
    session: SessionDep,
    principal: RequireViewer,
    strict: Annotated[bool, Query(description="Seule la recommandation « ship » passe")] = False,
) -> GateOut:
    with analytics_errors():
        experiment = await service.get_experiment(session, experiment_id)
        data = await service.experiment_gate(session, principal, experiment, strict=strict)
    return GateOut.model_validate(data)


@router.post("/{experiment_id}/cancel", response_model=ExperimentDetailOut, summary="Annuler une expérience")
async def cancel_experiment(
    experiment_id: uuid.UUID, session: SessionDep, principal: RequireEditor
) -> ExperimentDetailOut:
    with analytics_errors():
        experiment = await service.get_experiment(session, experiment_id)
        await service.cancel_experiment(session, principal, experiment)
    await session.commit()
    return await _detail(session, principal, experiment)

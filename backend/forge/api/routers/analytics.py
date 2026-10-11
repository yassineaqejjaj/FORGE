"""Router ``analytics``: dashboard and errors explorer (docs §12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from forge.api.deps import RequireViewer, SessionDep
from forge.api.routers.benchmarks import Paging
from forge.api.routers.meta import platform_errors
from forge.api.schemas.analytics import (
    AgentHealthOut,
    DashboardOut,
    ErrorsPageOut,
    ReleasesOverviewOut,
    ResultsOverviewOut,
    WorkerActivityOut,
)
from forge.domain.enums import ErrorSeverity
from forge.services import analytics as service
from forge.services import monitoring

router = APIRouter(tags=["analytics"])


@router.get(
    "/dashboard", response_model=DashboardOut, summary="Tableau de bord (indicateurs, tendances, activité)"
)
async def get_dashboard(
    session: SessionDep,
    principal: RequireViewer,
    days: Annotated[int, Query(ge=1, le=365, description="Fenêtre en jours")] = 30,
    agent_id: Annotated[uuid.UUID | None, Query(description="Restreindre à un système (agent)")] = None,
) -> DashboardOut:
    return DashboardOut.model_validate(
        await service.dashboard(session, principal, days=days, agent_id=agent_id)
    )


@router.get(
    "/results/overview",
    response_model=ResultsOverviewOut,
    summary="Résultats : runs évalués de la période agrégés par version d'agent",
)
async def get_results_overview(
    session: SessionDep,
    principal: RequireViewer,
    days: Annotated[int, Query(ge=1, le=365, description="Fenêtre en jours")] = 30,
    agent_id: uuid.UUID | None = None,
) -> ResultsOverviewOut:
    return ResultsOverviewOut.model_validate(
        await service.results_overview(session, principal, days=days, agent_id=agent_id)
    )


@router.get(
    "/workers/activity",
    response_model=WorkerActivityOut,
    summary="Activité des workers : jobs en file et en cours par file (exécution, évaluation)",
)
async def get_worker_activity(session: SessionDep, principal: RequireViewer) -> WorkerActivityOut:
    from forge.infra.queue import queue_activity

    return WorkerActivityOut.model_validate({"queues": await queue_activity(session)})


@router.get("/errors", response_model=ErrorsPageOut, summary="Explorateur d'erreurs (filtres et agrégations)")
async def explore_errors(
    session: SessionDep,
    principal: RequireViewer,
    page: Paging,
    error_type: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[ErrorSeverity] | None, Query()] = None,
    agent_id: uuid.UUID | None = None,
    agent_version_id: uuid.UUID | None = None,
    scenario_id: uuid.UUID | None = None,
    category: str | None = None,
    benchmark_execution_id: uuid.UUID | None = None,
    experiment_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> ErrorsPageOut:
    filters = service.ErrorFilters(
        error_type=error_type,
        severity=[s.value for s in severity] if severity else None,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        scenario_id=scenario_id,
        category=category,
        benchmark_execution_id=benchmark_execution_id,
        experiment_id=experiment_id,
        run_id=run_id,
        date_from=date_from,
        date_to=date_to,
    )
    data = await service.explore_errors(session, principal, filters, offset=page.offset, limit=page.page_size)
    return ErrorsPageOut.model_validate({**data, "page": page.page, "page_size": page.page_size})


@router.get(
    "/analytics/releases",
    response_model=ReleasesOverviewOut,
    summary="Résultats par release : réussite, coût par réussite, latence, écart avec les runs sans release",
)
async def get_releases_overview(
    session: SessionDep,
    principal: RequireViewer,
    days: Annotated[int, Query(ge=1, le=365, description="Fenêtre en jours")] = 30,
    agent_id: uuid.UUID | None = None,
) -> ReleasesOverviewOut:
    return ReleasesOverviewOut.model_validate(
        await monitoring.releases_overview(session, principal, days=days, agent_id=agent_id)
    )


@router.get(
    "/agents/{agent_id}/health",
    response_model=AgentHealthOut,
    summary="Santé d'un agent en production : fenêtre récente contre la période précédente",
    description=(
        "Compare les runs de production (observés et captures) de la fenêtre récente à ceux de la période "
        "d'avant : baisse significative du taux de réussite, hausse des échecs, du coût par réussite "
        "ou de la latence p95. Trop peu de runs → `insufficient_data` (jamais de fausse alerte)."
    ),
)
async def get_agent_health(
    agent_id: uuid.UUID,
    session: SessionDep,
    principal: RequireViewer,
    window_hours: Annotated[int, Query(ge=1, le=720)] = 24,
    baseline_hours: Annotated[int, Query(ge=1, le=2160)] = 168,
) -> AgentHealthOut:
    with platform_errors():
        data = await monitoring.agent_health(
            session, principal, agent_id, window_hours=window_hours, baseline_hours=baseline_hours
        )
    return AgentHealthOut.model_validate(data)

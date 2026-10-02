"""Router ``analytics``: dashboard and errors explorer (docs §12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from forge.api.deps import RequireViewer, SessionDep
from forge.api.routers.benchmarks import Paging
from forge.api.schemas.analytics import DashboardOut, ErrorsPageOut, ResultsOverviewOut
from forge.domain.enums import ErrorSeverity
from forge.services import analytics as service

router = APIRouter(tags=["analytics"])


@router.get(
    "/dashboard", response_model=DashboardOut, summary="Tableau de bord (indicateurs, tendances, activité)"
)
async def get_dashboard(
    session: SessionDep,
    principal: RequireViewer,
    days: Annotated[int, Query(ge=1, le=365, description="Fenêtre en jours")] = 30,
) -> DashboardOut:
    return DashboardOut.model_validate(await service.dashboard(session, principal, days=days))


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

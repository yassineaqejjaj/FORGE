"""Router ``benchmarks``: definitions, launches (executions), aggregated results (docs §9.1, §12)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from forge.api.deps import RequireEditor, RequireViewer, SessionDep
from forge.api.errors import ApiError, conflict, not_found, validation_error
from forge.api.schemas.benchmarks import (
    BenchmarkCreateIn,
    BenchmarkDetailOut,
    BenchmarkOut,
    BenchmarkRunIn,
    BenchmarkSummaryOut,
    BenchmarkUpdateIn,
    CancelOut,
    ExecutionBriefOut,
    ExecutionDetailOut,
    ExecutionOut,
    GroupBy,
    ResultsOut,
)
from forge.api.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from forge.infra.models import Benchmark, BenchmarkExecution, EvaluationConfig
from forge.services import benchmarks as service
from forge.services.run_summaries import (
    AnalyticsConflict,
    AnalyticsError,
    AnalyticsInvalid,
    AnalyticsNotFound,
)

router = APIRouter(tags=["benchmarks"])


def page_params(
    page: Annotated[int, Query(ge=1, description="Page (1 = première)")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Taille de page")
    ] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    """Pagination as two plain query parameters (combinable with other filters)."""
    return PageParams(page=page, page_size=page_size)


Paging = Annotated[PageParams, Depends(page_params)]


@contextmanager
def analytics_errors() -> Iterator[None]:
    """Translate analytics service errors into API errors (shared by the analytics routers)."""
    try:
        yield
    except AnalyticsNotFound as exc:
        raise not_found(str(exc)) from exc
    except AnalyticsConflict as exc:
        raise conflict(str(exc)) from exc
    except AnalyticsInvalid as exc:
        raise validation_error(str(exc)) from exc
    except AnalyticsError as exc:  # pragma: no cover - defensive
        raise ApiError(400, str(exc)) from exc


def _brief(execution: BenchmarkExecution | None) -> ExecutionBriefOut | None:
    if execution is None:
        return None
    return ExecutionBriefOut.model_validate(execution)


def _benchmark(listing: service.BenchmarkListing) -> dict[str, Any]:
    b = listing.benchmark
    return {
        "id": b.id,
        "slug": b.slug,
        "name": b.name,
        "description": b.description,
        "evaluation_config_id": b.evaluation_config_id,
        "repetitions": b.repetitions,
        "tags": list(b.tags or []),
        "archived": b.archived,
        "n_scenarios": listing.n_scenarios,
        "n_agents": listing.n_agents,
        "n_executions": listing.n_executions,
        "last_execution": _brief(listing.last_execution),
        "created_by": b.created_by,
        "created_at": b.created_at,
        "updated_at": b.updated_at,
    }


async def _detail(session: SessionDep, principal: RequireViewer, benchmark: Benchmark) -> BenchmarkDetailOut:
    listing = await service.benchmark_listing(session, benchmark)
    composition = await service.benchmark_composition(session, principal, benchmark)
    config = await session.get(EvaluationConfig, benchmark.evaluation_config_id)
    data = _benchmark(listing)
    data["n_scenarios"] = len(composition.scenarios)
    return BenchmarkDetailOut(
        **data,
        scenarios=composition.scenarios,  # type: ignore[arg-type]
        agents=composition.agents,  # type: ignore[arg-type]
        hidden_scenarios=composition.hidden_scenarios,
        evaluation_config_name=f"{config.name} (v{config.version})" if config else None,
    )


def _execution(execution: BenchmarkExecution, benchmark: Benchmark | None) -> dict[str, Any]:
    matrix = execution.matrix or {}
    done = execution.completed_runs + execution.failed_runs
    return {
        "id": execution.id,
        "number": execution.number,
        "status": execution.status,
        "total_runs": execution.total_runs,
        "completed_runs": execution.completed_runs,
        "failed_runs": execution.failed_runs,
        "created_at": execution.created_at,
        "finished_at": execution.finished_at,
        "benchmark_id": execution.benchmark_id,
        "benchmark_name": benchmark.name if benchmark else None,
        "benchmark_slug": benchmark.slug if benchmark else None,
        "evaluation_config_id": execution.evaluation_config_id,
        "repetitions": execution.repetitions,
        "trigger": execution.trigger,
        "error": execution.error,
        "triggered_by": execution.triggered_by,
        "started_at": execution.started_at,
        "progress": min(1.0, done / execution.total_runs) if execution.total_runs else 0.0,
        "n_scenarios": len(matrix.get("scenario_version_ids") or []),
        "n_agents": len(matrix.get("agent_version_ids") or []),
    }


async def _execution_detail(
    session: SessionDep, principal: RequireViewer, execution: BenchmarkExecution
) -> ExecutionDetailOut:
    benchmark = await session.get(Benchmark, execution.benchmark_id)
    summary = await service.execution_summary(session, principal, execution)
    matrix = dict(execution.matrix or {})
    if summary.get("restricted"):
        visible = {s["scenario_version_id"] for s in summary.get("matrix", {}).get("scenarios", [])}
        ids = list(matrix.get("scenario_version_ids") or [])
        keep = [i for i, sv in enumerate(ids) if sv in visible]
        for key in ("scenario_version_ids", "scenario_ids", "pinned"):
            values = list(matrix.get(key) or [])
            matrix[key] = [values[i] for i in keep if i < len(values)]
    data = _execution(execution, benchmark)
    data["n_scenarios"] = len(matrix.get("scenario_version_ids") or [])
    return ExecutionDetailOut(
        **data,
        matrix=matrix,
        summary=BenchmarkSummaryOut.model_validate(summary) if summary.get("schema") else None,
    )


# --- Benchmarks --------------------------------------------------------------------------------------


@router.get("/benchmarks", response_model=Page[BenchmarkOut], summary="Lister les benchmarks")
async def list_benchmarks(
    session: SessionDep,
    principal: RequireViewer,
    page: Paging,
    search: str | None = None,
    archived: bool | None = False,
    tag: str | None = None,
) -> Page[BenchmarkOut]:
    items, total = await service.list_benchmarks(
        session, search=search, archived=archived, tag=tag, offset=page.offset, limit=page.page_size
    )
    return Page(
        items=[BenchmarkOut(**_benchmark(i)) for i in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post(
    "/benchmarks",
    response_model=BenchmarkDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un benchmark",
)
async def create_benchmark(
    body: BenchmarkCreateIn, session: SessionDep, principal: RequireEditor
) -> BenchmarkDetailOut:
    with analytics_errors():
        benchmark = await service.create_benchmark(
            session,
            principal,
            principal,
            name=body.name,
            slug=body.slug,
            description=body.description,
            evaluation_config_id=body.evaluation_config_id,
            repetitions=body.repetitions,
            scenarios=[
                service.ScenarioSelection(s.scenario_id, s.scenario_version_id) for s in body.scenarios
            ],
            agent_version_ids=body.agent_version_ids,
            tags=body.tags,
        )
    await session.commit()
    return await _detail(session, principal, benchmark)


@router.get("/benchmarks/{benchmark_ref}", response_model=BenchmarkDetailOut, summary="Détail d'un benchmark")
async def get_benchmark(
    benchmark_ref: str, session: SessionDep, principal: RequireViewer
) -> BenchmarkDetailOut:
    with analytics_errors():
        benchmark = await service.get_benchmark(session, benchmark_ref)
    return await _detail(session, principal, benchmark)


@router.patch(
    "/benchmarks/{benchmark_ref}", response_model=BenchmarkDetailOut, summary="Modifier un benchmark"
)
async def update_benchmark(
    benchmark_ref: str, body: BenchmarkUpdateIn, session: SessionDep, principal: RequireEditor
) -> BenchmarkDetailOut:
    changes: dict[str, Any] = body.model_dump(exclude_unset=True)
    if body.scenarios is not None:
        changes["scenarios"] = [
            service.ScenarioSelection(s.scenario_id, s.scenario_version_id) for s in body.scenarios
        ]
    with analytics_errors():
        benchmark = await service.get_benchmark(session, benchmark_ref)
        await service.update_benchmark(session, principal, principal, benchmark, changes)
    await session.commit()
    return await _detail(session, principal, benchmark)


@router.post(
    "/benchmarks/{benchmark_ref}/run",
    response_model=ExecutionDetailOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lancer une exécution du benchmark (N scénarios × M versions × K répétitions)",
)
async def run_benchmark(
    benchmark_ref: str, session: SessionDep, principal: RequireEditor, body: BenchmarkRunIn | None = None
) -> ExecutionDetailOut:
    with analytics_errors():
        benchmark = await service.get_benchmark(session, benchmark_ref)
        execution = await service.launch_execution(
            session, principal, principal, benchmark, trigger=(body.trigger if body else "ui")
        )
    await session.commit()
    return await _execution_detail(session, principal, execution)


@router.get(
    "/benchmarks/{benchmark_ref}/executions",
    response_model=Page[ExecutionOut],
    summary="Exécutions d'un benchmark (plus récentes d'abord)",
)
async def list_executions(
    benchmark_ref: str, session: SessionDep, principal: RequireViewer, page: Paging
) -> Page[ExecutionOut]:
    with analytics_errors():
        benchmark = await service.get_benchmark(session, benchmark_ref)
    items, total = await service.list_executions(
        session, benchmark.id, offset=page.offset, limit=page.page_size
    )
    return Page(
        items=[ExecutionOut(**_execution(e, benchmark)) for e in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get(
    "/benchmarks/{benchmark_ref}/results",
    response_model=ResultsOut,
    summary="Résultats agrégés d'une exécution, regroupés et filtrés",
)
async def benchmark_results(
    benchmark_ref: str,
    session: SessionDep,
    principal: RequireViewer,
    execution_id: uuid.UUID | None = None,
    group_by: GroupBy = "version",
    visibility: str | None = None,
    category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> ResultsOut:
    with analytics_errors():
        benchmark = await service.get_benchmark(session, benchmark_ref)
        data = await service.benchmark_results(
            session,
            principal,
            benchmark,
            execution_id=execution_id,
            group_by=group_by,
            visibility=visibility,
            category=category,
            date_from=date_from,
            date_to=date_to,
        )
    return ResultsOut.model_validate(data)


# --- Executions --------------------------------------------------------------------------------------


@router.get(
    "/benchmark-executions/{execution_id}",
    response_model=ExecutionDetailOut,
    summary="Détail d'une exécution de benchmark (matrice figée, résumé agrégé)",
)
async def get_execution(
    execution_id: uuid.UUID, session: SessionDep, principal: RequireViewer
) -> ExecutionDetailOut:
    with analytics_errors():
        execution = await service.get_execution(session, execution_id)
    return await _execution_detail(session, principal, execution)


@router.post(
    "/benchmark-executions/{execution_id}/cancel",
    response_model=CancelOut,
    summary="Annuler une exécution en cours (les résultats partiels sont agrégés)",
)
async def cancel_execution(
    execution_id: uuid.UUID, session: SessionDep, principal: RequireEditor
) -> CancelOut:
    with analytics_errors():
        execution = await service.get_execution(session, execution_id)
        cancelled = await service.cancel_execution(session, principal, execution)
    await session.commit()
    return CancelOut(detail=f"Exécution n° {execution.number} annulée", cancelled_runs=cancelled)

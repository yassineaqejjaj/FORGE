"""Router ``runs``: ad-hoc run creation, lists, Run Detail, trace, timeline, manifest, cancel, retry.

Runs of scenarios above the caller's clearance are never revealed (404); private content is redacted
for non-maintainers (docs §3.3, §3.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from forge.api.deps import RequireEditor, RequireViewer, SessionDep
from forge.api.routers.meta import PageQuery, platform_errors
from forge.api.schemas.common import Page
from forge.api.schemas.runs import (
    ObservedRunIn,
    RunCreateIn,
    RunDetailOut,
    RunManifestOut,
    RunOut,
    RunTraceOut,
)
from forge.domain.enums import ExperimentArm, RunOrigin, RunStatus
from forge.infra.models import EvaluationRun
from forge.services import observed_runs
from forge.services import run_queries as service

router = APIRouter(prefix="/runs", tags=["runs"])


async def _summaries(
    session: SessionDep, principal: RequireViewer, runs: list[EvaluationRun]
) -> list[RunOut]:
    if not runs:
        return []
    rows, _ = await service.list_runs(
        session, principal, service.RunFilters(), offset=0, limit=len(runs) + 1, run_ids=[r.id for r in runs]
    )
    by_id = {r.run.id: r for r in rows}
    return [RunOut(**service.run_summary(by_id[r.id])) for r in runs if r.id in by_id]


@router.post(
    "", response_model=list[RunOut], status_code=status.HTTP_201_CREATED, summary="Lancer des runs ad hoc"
)
async def create_runs(body: RunCreateIn, principal: RequireEditor, session: SessionDep) -> list[RunOut]:
    with platform_errors():
        runs = await service.create_adhoc_runs(
            session,
            principal,
            principal,
            service.RunRequest(
                agent_version_id=body.agent_version_id,
                scenario_ids=body.scenario_ids,
                scenario_version_ids=body.scenario_version_ids,
                repetitions=body.repetitions,
                evaluation_config_id=body.evaluation_config_id,
                tags=body.tags,
            ),
            created_by=principal.user_id,
        )
    await session.commit()
    return await _summaries(session, principal, runs)


@router.post(
    "/observed",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
    summary="Ingérer un run déjà exécuté (évaluation seule)",
    description=(
        "Enregistre un run exécuté par un système externe puis le fait évaluer par le pipeline normal "
        "(règles du scénario, métriques, juges de la configuration). `external_id` est une clé "
        "d'idempotence par agent : un second appel renvoie le run existant avec le code 200."
    ),
    responses={200: {"model": RunOut, "description": "Run déjà ingéré avec cette clé d'idempotence"}},
)
async def create_observed_run(
    body: ObservedRunIn, response: Response, principal: RequireEditor, session: SessionDep
) -> RunOut:
    with platform_errors():
        run, created = await observed_runs.ingest_observed_run(
            session,
            principal,
            principal,
            observed_runs.ObservedRunData(
                agent_version_id=body.agent_version_id,
                scenario_id=body.scenario_id,
                evaluation_config_id=body.evaluation_config_id,
                input=body.input,
                output_text=body.output_text,
                output_json=body.output_json,
                execution_status=body.execution_status,
                error=body.error,
                started_at=body.started_at,
                completed_at=body.completed_at,
                input_tokens=body.usage.input_tokens,
                output_tokens=body.usage.output_tokens,
                model_calls=body.usage.model_calls,
                tags=body.tags,
                external_id=body.external_id,
            ),
            created_by=principal.user_id,
        )
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return (await _summaries(session, principal, [run]))[0]


@router.get("", response_model=Page[RunOut], summary="Lister les runs")
async def list_runs(
    principal: RequireViewer,
    session: SessionDep,
    paging: PageQuery,
    status_: Annotated[list[RunStatus] | None, Query(alias="status")] = None,
    origin: RunOrigin | None = None,
    agent_id: uuid.UUID | None = None,
    agent_version_id: uuid.UUID | None = None,
    scenario_id: uuid.UUID | None = None,
    scenario_version_id: uuid.UUID | None = None,
    benchmark_execution_id: uuid.UUID | None = None,
    experiment_id: uuid.UUID | None = None,
    arm: ExperimentArm | None = None,
    passed: bool | None = None,
    gate_failed: bool | None = None,
    min_composite: float | None = Query(default=None, ge=0, le=100),
    max_composite: float | None = Query(default=None, ge=0, le=100),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    tag: str | None = Query(default=None, max_length=200),
    external_id: str | None = Query(
        default=None, max_length=200, description="Clé d'idempotence (runs observés)"
    ),
    q: str | None = Query(default=None, max_length=200, description="Nom de scénario ou d'agent"),
    sort: str = Query(default="-created_at", description="-created_at, created_at, ±composite, ±latency"),
) -> Page[RunOut]:
    filters = service.RunFilters(
        status=status_ or (),
        origin=origin,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        scenario_id=scenario_id,
        scenario_version_id=scenario_version_id,
        benchmark_execution_id=benchmark_execution_id,
        experiment_id=experiment_id,
        arm=arm,
        passed=passed,
        gate_failed=gate_failed,
        min_composite=min_composite,
        max_composite=max_composite,
        created_from=created_from,
        created_to=created_to,
        tag=tag,
        external_id=external_id,
        q=q,
    )
    with platform_errors():
        rows, total = await service.list_runs(
            session, principal, filters, sort=sort, offset=paging.offset, limit=paging.page_size
        )
    return Page[RunOut](
        items=[RunOut(**service.run_summary(r)) for r in rows],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/{run_id}", response_model=RunDetailOut, summary="Détail d'un run")
async def get_run(run_id: uuid.UUID, principal: RequireViewer, session: SessionDep) -> RunDetailOut:
    with platform_errors():
        detail = await service.run_detail(session, principal, run_id)
    return RunDetailOut(**detail)


@router.get(
    "/{run_id}/trace", response_model=RunTraceOut, summary="Trace d'exécution (messages, outils, modèles)"
)
async def get_trace(run_id: uuid.UUID, principal: RequireViewer, session: SessionDep) -> RunTraceOut:
    with platform_errors():
        trace = await service.run_trace(session, principal, run_id)
    return RunTraceOut(**trace)


@router.get("/{run_id}/timeline", response_model=dict[str, Any], summary="Timeline du run")
async def get_timeline(run_id: uuid.UUID, principal: RequireViewer, session: SessionDep) -> dict[str, Any]:
    with platform_errors():
        return await service.run_timeline(session, principal, run_id)


@router.get("/{run_id}/manifest", response_model=RunManifestOut, summary="Manifeste figé du run")
async def get_manifest(run_id: uuid.UUID, principal: RequireViewer, session: SessionDep) -> RunManifestOut:
    with platform_errors():
        manifest = await service.run_manifest(session, principal, run_id)
    return RunManifestOut(**manifest)


@router.post("/{run_id}/cancel", response_model=RunOut, summary="Annuler un run")
async def cancel_run(run_id: uuid.UUID, principal: RequireEditor, session: SessionDep) -> RunOut:
    with platform_errors():
        run = await service.cancel_run(session, principal, principal, run_id)
    await session.commit()
    return (await _summaries(session, principal, [run]))[0]


@router.post(
    "/{run_id}/retry", response_model=RunOut, status_code=status.HTTP_201_CREATED, summary="Relancer un run"
)
async def retry_run(run_id: uuid.UUID, principal: RequireEditor, session: SessionDep) -> RunOut:
    with platform_errors():
        run = await service.retry_run(session, principal, principal, run_id, created_by=principal.user_id)
    await session.commit()
    return (await _summaries(session, principal, [run]))[0]

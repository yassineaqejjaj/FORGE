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
    ContextGapIn,
    ContextGapOut,
    ObservedRunIn,
    PromoteRunIn,
    PromoteRunOut,
    RunCreateIn,
    RunDetailOut,
    RunManifestOut,
    RunOut,
    RunRiskOut,
    RunTraceOut,
)
from forge.domain.enums import ExperimentArm, RunOrigin, RunStatus
from forge.infra.models import EvaluationRun
from forge.services import context_gaps, monitoring, observed_runs, regression
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
                context_snapshot_id=body.context_snapshot_id,
                release_id=body.release_id,
                manifest=body.manifest,
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
                context_snapshot_id=body.context_snapshot_id,
                release_id=body.release_id,
                manifest=body.manifest,
                events=[e.model_dump(mode="json", exclude_none=True) for e in body.events],
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
    context_snapshot_id: str | None = Query(
        default=None, max_length=300, description="Snapshot ORBIT (« nom@vN »)"
    ),
    release_id: str | None = Query(default=None, max_length=200),
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
        context_snapshot_id=context_snapshot_id,
        release_id=release_id,
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


@router.post(
    "/{run_id}/context-gap",
    response_model=ContextGapOut,
    summary="Combler le manque de contexte d'un run via ORBIT",
    description=(
        "Demande à ORBIT de recomposer le contexte servi à ce run autour des informations manquantes "
        "(`MISSING_INFORMATION` ou `missing`), enregistré comme nouvelle version du snapshot. Avec `retest`, "
        "une version d'agent épinglée sur ce snapshot est créée et le même scénario est relancé."
    ),
)
async def fill_context_gap(
    run_id: uuid.UUID, body: ContextGapIn, principal: RequireEditor, session: SessionDep
) -> ContextGapOut:
    with platform_errors():
        result = await context_gaps.fill_context_gap(
            session,
            principal,
            principal,
            run_id,
            context_gaps.GapRequest(
                missing=body.missing,
                orbit_project=body.orbit_project,
                credential_id=body.credential_id,
                snapshot=body.snapshot,
                retest=body.retest,
            ),
            created_by=principal.user_id,
        )
    await session.commit()
    return ContextGapOut(
        run_id=result.run_id,
        missing=result.missing,
        orbit_request_id=result.orbit_request_id,
        orbit_project=result.orbit_project,
        completion=result.completion,
        candidate_version_id=result.candidate_version_id,
        retest_run_id=result.retest_run_id,
    )


@router.post(
    "/{run_id}/promote-to-scenario",
    response_model=PromoteRunOut,
    summary="Faire d'un run en échec un scénario de régression",
    description=(
        "Crée une variante du scénario du run avec l'entrée et le contexte réellement reçus, et les erreurs "
        "constatées en contraintes. Idempotent : `201` à la création, `200` si le run était déjà promu."
    ),
    responses={200: {"model": PromoteRunOut, "description": "Run déjà promu"}},
)
async def promote_run(
    run_id: uuid.UUID,
    response: Response,
    principal: RequireEditor,
    session: SessionDep,
    body: PromoteRunIn | None = None,
) -> PromoteRunOut:
    with platform_errors():
        promotion = await regression.promote_run(
            session, principal, principal, run_id, label=body.label if body else None
        )
    await session.commit()
    response.status_code = status.HTTP_201_CREATED if promotion.created else status.HTTP_200_OK
    return PromoteRunOut(
        scenario_id=promotion.scenario_id,
        scenario_version_id=promotion.scenario_version_id,
        slug=promotion.slug,
        created=promotion.created,
    )


@router.get(
    "/{run_id}/risk",
    response_model=RunRiskOut,
    summary="Risque d'échec d'un run en cours, avant sa fin",
    description=(
        "Signes d'échec lus dans les étapes déjà rapportées : appel d'outil répété (boucle), outils en "
        "échec, durée ou tokens très au-delà des runs réussis de la même version, budget presque consommé. "
        "`level` : low, medium ou high."
    ),
)
async def get_run_risk(run_id: uuid.UUID, principal: RequireViewer, session: SessionDep) -> RunRiskOut:
    with platform_errors():
        data = await monitoring.run_risk(session, principal, run_id)
    return RunRiskOut.model_validate(data)

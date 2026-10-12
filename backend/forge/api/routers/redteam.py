"""Router ``redteam``: install the attack catalogue, launch it against an agent, read the resistance."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from forge.api.deps import RequireEditor, RequireViewer, SessionDep
from forge.api.routers.meta import platform_errors
from forge.api.schemas.redteam import RedTeamAttackOut, RedTeamLaunchIn, RedTeamLaunchOut, RedTeamReportOut
from forge.domain import redteam as domain
from forge.services import redteam as service
from forge.services import scenarios

router = APIRouter(prefix="/redteam", tags=["redteam"])


@router.get("/catalog", response_model=list[RedTeamAttackOut], summary="Catalogue des attaques")
async def catalog(session: SessionDep, principal: RequireViewer) -> list[RedTeamAttackOut]:
    out = []
    for attack in domain.CATALOG:
        scenario = await scenarios.get_by_slug(session, attack.slug)
        out.append(
            RedTeamAttackOut(
                key=attack.key,
                label=attack.label,
                summary=attack.summary,
                prompt=attack.prompt,
                expected_behavior=attack.expected_behavior,
                scenario_id=scenario.id if scenario else None,
            )
        )
    return out


@router.post(
    "/runs",
    response_model=RedTeamLaunchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Lancer le catalogue d'attaques contre une version d'agent",
    description="Installe les scénarios d'attaque manquants puis lance un run par attaque et par répétition.",
)
async def launch(body: RedTeamLaunchIn, session: SessionDep, principal: RequireEditor) -> RedTeamLaunchOut:
    with platform_errors():
        runs = await service.launch(
            session,
            principal,
            principal,
            body.agent_version_id,
            repetitions=body.repetitions,
            created_by=principal.user_id,
        )
    await session.commit()
    return RedTeamLaunchOut(run_ids=[r.id for r in runs], attacks=len(domain.CATALOG))


@router.get(
    "/report",
    response_model=RedTeamReportOut,
    summary="Résistance d'une version d'agent aux attaques",
    description=(
        "Pour chaque famille d'attaque : part des runs évalués où aucun détecteur n'a déclenché. "
        "Les détecteurs sont des règles déterministes (aucun juge LLM)."
    ),
)
async def report(
    agent_version_id: uuid.UUID,
    session: SessionDep,
    principal: RequireViewer,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> RedTeamReportOut:
    with platform_errors():
        data = await service.report(session, principal, agent_version_id, days=days)
    return RedTeamReportOut.model_validate(data)

"""Router ``reviews``: human review queue and human evaluations (evaluator+, docs §7.1, §9.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from forge.api.deps import RequireEvaluator, RequireViewer, SessionDep
from forge.api.errors import forbidden
from forge.api.routers.meta import PageQuery, platform_errors
from forge.api.schemas.common import Page
from forge.api.schemas.reviews import (
    HumanEvaluationIn,
    HumanEvaluationOut,
    HumanEvaluationSubmitOut,
    ReviewCriterion,
    ReviewQueueItem,
)
from forge.services import reviews as service

router = APIRouter(tags=["reviews"])


@router.get("/reviews/queue", response_model=Page[ReviewQueueItem], summary="File de revue humaine")
async def review_queue(
    principal: RequireEvaluator,
    session: SessionDep,
    paging: PageQuery,
    dataset_id: uuid.UUID | None = Query(default=None, description="Jeu de données gold"),
    blind: bool = Query(default=False, description="Mode aveugle : masque les scores IA"),
    priority: bool = Query(
        default=False,
        description="Exécutions qui demandent un humain (désaccord des juges, confiance faible, jeu gold)",
    ),
) -> Page[ReviewQueueItem]:
    if principal.user_id is None:
        raise forbidden("La file de revue est réservée aux utilisateurs (pas aux clés d'API)")
    with platform_errors():
        items, total = await service.review_queue(
            session,
            principal,
            principal.user_id,
            dataset_id=dataset_id,
            priority_only=priority,
            offset=paging.offset,
            limit=paging.page_size,
        )
    result = []
    for item in items:
        agent = (item.run.manifest or {}).get("agent") or {}
        scenario = (item.run.manifest or {}).get("scenario") or {}
        result.append(
            ReviewQueueItem(
                run_id=item.run.id,
                status=item.run.status,
                origin=item.run.origin,
                scenario_id=item.scenario.id,
                scenario_slug=scenario.get("slug") or item.scenario.slug,
                scenario_name=scenario.get("name") or item.scenario.name,
                visibility=scenario.get("visibility") or item.scenario.visibility.value,
                classification=int(item.scenario.classification),
                agent_version_id=item.run.agent_version_id,
                agent_label=f"{agent.get('agent_name')} v{agent.get('version')}" if agent else None,
                created_at=item.run.created_at,
                blind=blind,
                composite_score=None if blind else item.run.composite_score,
                ai_scores=None if blind else item.ai_scores,
                max_spread=item.max_spread,
                min_confidence=None if blind else item.min_confidence,
                criteria=[ReviewCriterion(**c) for c in item.criteria],
            )
        )
    return Page[ReviewQueueItem](items=result, total=total, page=paging.page, page_size=paging.page_size)


@router.post(
    "/runs/{run_id}/human-evaluations",
    response_model=HumanEvaluationSubmitOut,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer (ou remplacer) son évaluation humaine d'un run",
)
async def submit_human_evaluation(
    run_id: uuid.UUID, body: HumanEvaluationIn, principal: RequireEvaluator, session: SessionDep
) -> HumanEvaluationSubmitOut:
    with platform_errors():
        run, rows, rescored = await service.submit_human_evaluation(
            session,
            principal,
            principal,
            run_id,
            user_id=principal.user_id,
            scores=[service.HumanScore(s.criterion_key, s.score, s.comment) for s in body.scores],
            comment=body.comment,
        )
    await session.commit()
    evaluations = [
        e
        for e in await service.list_human_evaluations(session, principal, run_id)
        if e["user_id"] == principal.user_id
    ]
    return HumanEvaluationSubmitOut(
        run_id=run.id,
        evaluations=[HumanEvaluationOut(**e) for e in evaluations],
        composite_score=run.composite_score,
        rescored=rescored,
        detail={"criteria": len(rows)},
    )


@router.get(
    "/runs/{run_id}/human-evaluations",
    response_model=list[HumanEvaluationOut],
    summary="Évaluations humaines d'un run",
)
async def list_human_evaluations(
    run_id: uuid.UUID, principal: RequireViewer, session: SessionDep
) -> list[HumanEvaluationOut]:
    with platform_errors():
        rows = await service.list_human_evaluations(session, principal, run_id)
    return [HumanEvaluationOut(**r) for r in rows]

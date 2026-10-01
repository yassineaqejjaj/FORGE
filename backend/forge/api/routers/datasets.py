"""Router ``datasets``: context datasets (documents) and gold datasets (runs for calibration)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from forge.api.deps import RequireEditor, RequireViewer, SessionDep
from forge.api.routers.meta import PageQuery, platform_errors
from forge.api.schemas.common import Page
from forge.api.schemas.datasets import (
    DatasetCreateIn,
    DatasetDetailOut,
    DatasetItemOut,
    DatasetItemsIn,
    DatasetOut,
    DatasetUpdateIn,
)
from forge.domain.enums import DatasetKind
from forge.infra.models import Dataset, EvaluationRun, Scenario
from forge.services import access
from forge.services import datasets as service

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _dataset(dataset: Dataset, items_count: int) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "slug": dataset.slug,
        "name": dataset.name,
        "kind": dataset.kind,
        "description": dataset.description,
        "version": dataset.version,
        "tags": list(dataset.tags or []),
        "items_count": items_count,
        "created_by": dataset.created_by,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
    }


async def _detail(session: SessionDep, principal: RequireViewer, dataset: Dataset) -> DatasetDetailOut:
    items = await service.list_items(session, dataset)
    runs: dict[uuid.UUID, dict[str, Any]] = {}
    run_ids = [i.run_id for i in items if i.run_id]
    if run_ids:
        rows = await session.execute(
            select(EvaluationRun, Scenario)
            .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
            .where(EvaluationRun.id.in_(run_ids), access.classification_condition(principal))
        )
        for run, scenario in rows.all():
            agent = (run.manifest or {}).get("agent") or {}
            runs[run.id] = {
                "status": run.status.value,
                "scenario_slug": scenario.slug,
                "scenario_name": scenario.name,
                "agent_label": f"{agent.get('agent_name')} v{agent.get('version')}",
                "composite_score": run.composite_score,
                "created_at": run.created_at.isoformat(),
            }
    visible = [i for i in items if i.run_id is None or i.run_id in runs]
    return DatasetDetailOut(
        **_dataset(dataset, len(visible)),
        items=[
            DatasetItemOut(
                id=i.id,
                dataset_id=i.dataset_id,
                key=i.key,
                content=dict(i.content or {}),
                run_id=i.run_id,
                run=runs.get(i.run_id) if i.run_id else None,
                created_at=i.created_at,
            )
            for i in visible
        ],
    )


@router.get("", response_model=Page[DatasetOut], summary="Lister les jeux de données")
async def list_datasets(
    principal: RequireViewer,
    session: SessionDep,
    paging: PageQuery,
    kind: DatasetKind | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> Page[DatasetOut]:
    rows, total = await service.list_datasets(
        session, kind=kind, q=q, offset=paging.offset, limit=paging.page_size
    )
    return Page[DatasetOut](
        items=[DatasetOut(**_dataset(r.dataset, r.items_count)) for r in rows],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post(
    "",
    response_model=DatasetDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un jeu de données",
)
async def create_dataset(
    body: DatasetCreateIn, principal: RequireEditor, session: SessionDep
) -> DatasetDetailOut:
    with platform_errors():
        dataset = await service.create_dataset(
            session,
            principal,
            principal,
            name=body.name,
            kind=body.kind,
            slug=body.slug,
            description=body.description,
            tags=body.tags,
            items=[i.model_dump(exclude_none=True, mode="json") for i in body.items],
            created_by=principal.user_id,
        )
    await session.commit()
    return await _detail(session, principal, dataset)


@router.get("/{dataset_id}", response_model=DatasetDetailOut, summary="Détail d'un jeu de données")
async def get_dataset(
    dataset_id: uuid.UUID, principal: RequireViewer, session: SessionDep
) -> DatasetDetailOut:
    with platform_errors():
        dataset = await service.get_dataset(session, dataset_id)
    return await _detail(session, principal, dataset)


@router.patch("/{dataset_id}", response_model=DatasetDetailOut, summary="Modifier un jeu de données")
async def update_dataset(
    dataset_id: uuid.UUID, body: DatasetUpdateIn, principal: RequireEditor, session: SessionDep
) -> DatasetDetailOut:
    with platform_errors():
        dataset = await service.get_dataset(session, dataset_id)
        await service.update_dataset(session, principal, dataset, body.model_dump(exclude_unset=True))
    await session.commit()
    return await _detail(session, principal, dataset)


@router.post(
    "/{dataset_id}/items",
    response_model=list[DatasetItemOut],
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter des éléments",
)
async def add_items(
    dataset_id: uuid.UUID, body: DatasetItemsIn, principal: RequireEditor, session: SessionDep
) -> list[DatasetItemOut]:
    with platform_errors():
        dataset = await service.get_dataset(session, dataset_id)
        items = await service.add_items(
            session,
            principal,
            principal,
            dataset,
            [i.model_dump(exclude_none=True, mode="json") for i in body.items],
        )
    await session.commit()
    return [
        DatasetItemOut(
            id=i.id,
            dataset_id=i.dataset_id,
            key=i.key,
            content=dict(i.content or {}),
            run_id=i.run_id,
            created_at=i.created_at,
        )
        for i in items
    ]


@router.delete(
    "/{dataset_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Retirer un élément"
)
async def remove_item(
    dataset_id: uuid.UUID, item_id: uuid.UUID, principal: RequireEditor, session: SessionDep
) -> Response:
    with platform_errors():
        dataset = await service.get_dataset(session, dataset_id)
        await service.remove_item(session, principal, dataset, item_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

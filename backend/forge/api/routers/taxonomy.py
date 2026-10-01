"""Router ``taxonomy``: criteria catalog and error taxonomy (custom entries: maintainer)."""

from __future__ import annotations

from fastapi import APIRouter, status

from forge.api.deps import RequireMaintainer, RequireViewer, SessionDep
from forge.api.routers.meta import platform_errors
from forge.api.schemas.taxonomy import CriterionCreateIn, CriterionOut, ErrorTypeCreateIn, ErrorTypeOut
from forge.domain.enums import DIMENSION_LABELS, Dimension
from forge.infra.models import Criterion
from forge.services import taxonomy as service

router = APIRouter(tags=["taxonomy"])

_NON_JUDGED = {Dimension.cost, Dimension.latency, Dimension.robustness}


def _criterion(c: Criterion) -> CriterionOut:
    return CriterionOut(
        key=c.key,
        dimension=c.dimension,
        dimension_label=DIMENSION_LABELS.get(c.dimension, c.dimension.value),
        name=c.name,
        question=c.question,
        rubric=c.rubric,
        scale_min=c.scale_min,
        scale_max=c.scale_max,
        builtin=c.builtin,
        judged=c.dimension not in _NON_JUDGED,
        created_at=c.created_at,
    )


@router.get("/criteria", response_model=list[CriterionOut], summary="Catalogue des critères")
async def list_criteria(
    principal: RequireViewer, session: SessionDep, dimension: Dimension | None = None
) -> list[CriterionOut]:
    return [_criterion(c) for c in await service.list_criteria(session, dimension=dimension)]


@router.post(
    "/criteria", response_model=CriterionOut, status_code=status.HTTP_201_CREATED, summary="Créer un critère"
)
async def create_criterion(
    body: CriterionCreateIn, principal: RequireMaintainer, session: SessionDep
) -> CriterionOut:
    with platform_errors():
        criterion = await service.create_criterion(
            session,
            principal,
            key=body.key,
            name=body.name,
            question=body.question,
            rubric=body.rubric,
            scale_min=body.scale_min,
            scale_max=body.scale_max,
        )
    await session.commit()
    return _criterion(criterion)


@router.get("/error-types", response_model=list[ErrorTypeOut], summary="Taxonomie des erreurs")
async def list_error_types(principal: RequireViewer, session: SessionDep) -> list[ErrorTypeOut]:
    return [ErrorTypeOut.model_validate(e) for e in await service.list_error_types(session)]


@router.post(
    "/error-types",
    response_model=ErrorTypeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un type d'erreur",
)
async def create_error_type(
    body: ErrorTypeCreateIn, principal: RequireMaintainer, session: SessionDep
) -> ErrorTypeOut:
    with platform_errors():
        error_type = await service.create_error_type(
            session,
            principal,
            code=body.code,
            label=body.label,
            description=body.description,
            default_severity=body.default_severity,
            dimension=body.dimension,
        )
    await session.commit()
    return ErrorTypeOut.model_validate(error_type)

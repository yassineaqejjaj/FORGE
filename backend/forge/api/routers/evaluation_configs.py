"""Router ``evaluation_configs`` (docs §12): ScoreConfiguration versions and previews.

Reads and previews: viewer (previews persist nothing). Writes: maintainer. Hidden global rules are
masked for non-maintainers.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from forge.api.deps import Principal, RequireMaintainer, RequireViewer, SessionDep
from forge.api.errors import conflict, not_found, validation_error
from forge.api.schemas.common import Page, PageParams
from forge.api.schemas.evaluation_configs import (
    ConfigCreateIn,
    ConfigDetailOut,
    ConfigJudgeOut,
    ConfigOut,
    ConfigVersionIn,
    ConfigVersionSummary,
    PreviewIn,
    PreviewItemOut,
    PreviewOut,
)
from forge.domain.redaction import redact_rules
from forge.infra.models import EvaluationConfig
from forge.services import evaluation_configs as config_service

router = APIRouter(prefix="/evaluation-configs", tags=["evaluation-configs"])


async def _get(session: SessionDep, config_id: uuid.UUID) -> EvaluationConfig:
    config = await session.get(EvaluationConfig, config_id)
    if config is None:
        raise not_found("Configuration d'évaluation introuvable")
    return config


def _out(config: EvaluationConfig, principal: Principal) -> ConfigOut:
    out = ConfigOut.model_validate(config, from_attributes=True)
    if not principal.can_see_private:
        out.rules = redact_rules(list(out.rules), private=False)
    return out


async def _detail(session: SessionDep, config: EvaluationConfig, principal: Principal) -> ConfigDetailOut:
    judges = await config_service.config_judges(session, config)
    versions = await config_service.config_versions(session, config.key)
    return ConfigDetailOut(
        **_out(config, principal).model_dump(),
        judges=[ConfigJudgeOut.model_validate(j, from_attributes=True) for j in judges],
        versions=[ConfigVersionSummary.model_validate(v, from_attributes=True) for v in versions],
    )


@router.post(
    "", response_model=ConfigDetailOut, status_code=status.HTTP_201_CREATED, summary="Créer une configuration"
)
async def create_config(
    body: ConfigCreateIn, principal: RequireMaintainer, session: SessionDep
) -> ConfigDetailOut:
    try:
        config = await config_service.create_config(
            session,
            key=body.key,
            name=body.name,
            description=body.description,
            is_default=body.is_default,
            actor=principal,
            created_by=principal.user_id,
            **body.behaviour(),
        )
    except config_service.ConfigConflict as exc:
        raise conflict(str(exc)) from exc
    except config_service.ConfigValidationError as exc:
        raise validation_error(str(exc)) from exc
    await session.commit()
    return await _detail(session, config, principal)


@router.get("", response_model=Page[ConfigOut], summary="Lister les configurations d'évaluation")
async def list_configs(
    principal: RequireViewer,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    latest_only: bool = True,
    key: str | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> Page[ConfigOut]:
    params = PageParams(page=page, page_size=page_size)
    rows, total = await config_service.list_configs(
        session, latest_only=latest_only, key=key, search=q, offset=params.offset, limit=params.page_size
    )
    return Page[ConfigOut](
        items=[_out(c, principal) for c in rows], total=total, page=page, page_size=page_size
    )


@router.get("/{config_id}", response_model=ConfigDetailOut, summary="Détail d'une configuration")
async def get_config(config_id: uuid.UUID, principal: RequireViewer, session: SessionDep) -> ConfigDetailOut:
    return await _detail(session, await _get(session, config_id), principal)


@router.post(
    "/{config_id}/versions",
    response_model=ConfigDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une nouvelle version d'une configuration",
)
async def create_version(
    config_id: uuid.UUID, body: ConfigVersionIn, principal: RequireMaintainer, session: SessionDep
) -> ConfigDetailOut:
    config = await _get(session, config_id)
    changes: dict[str, object] = dict(body.behaviour())
    for name in ("name", "description", "is_default"):
        value = getattr(body, name)
        if value is not None:
            changes[name] = value
    try:
        version = await config_service.create_config_version(
            session, config, changes, actor=principal, created_by=principal.user_id
        )
    except config_service.ConfigConflict as exc:
        raise conflict(str(exc)) from exc
    except config_service.ConfigValidationError as exc:
        raise validation_error(str(exc)) from exc
    await session.commit()
    return await _detail(session, version, principal)


@router.post(
    "/{config_id}/preview",
    response_model=PreviewOut,
    summary="Aperçu des composites recalculés avec cette configuration (sans enregistrement)",
)
async def preview_config(
    config_id: uuid.UUID, body: PreviewIn, principal: RequireViewer, session: SessionDep
) -> PreviewOut:
    config = await _get(session, config_id)
    try:
        result = await config_service.preview(
            session,
            config,
            viewer=principal,
            run_ids=body.run_ids,
            benchmark_execution_id=body.benchmark_execution_id,
            overrides=body.overrides.behaviour() if body.overrides is not None else None,
        )
    except config_service.ConfigValidationError as exc:
        raise validation_error(str(exc)) from exc
    finally:
        await session.rollback()  # a preview never persists anything
    return PreviewOut(
        config_id=result.config_id,
        items=[PreviewItemOut.model_validate(i, from_attributes=True) for i in result.items],
        skipped=result.skipped,
        mean_before=result.mean_before,
        mean_after=result.mean_after,
        pass_rate_before=result.pass_rate_before,
        pass_rate_after=result.pass_rate_after,
        notes=result.notes,
    )

"""Router ``judges`` (docs §12): immutable judge versions, enabling, dry-run test.

Reads: viewer. Writes and tests: maintainer.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from forge.api.deps import RequireMaintainer, RequireViewer, SessionDep
from forge.api.errors import ApiError, conflict, not_found, validation_error
from forge.api.schemas.common import Page, PageParams
from forge.api.schemas.judges import (
    JudgeCreateIn,
    JudgeDetailOut,
    JudgeOut,
    JudgeTestIn,
    JudgeTestOut,
    JudgeUpdateIn,
    JudgeVersionIn,
    JudgeVersionSummary,
)
from forge.domain.enums import JudgeProvider
from forge.domain.judges import PLACEHOLDERS
from forge.infra.llm import LLMError
from forge.infra.models import Judge
from forge.services import evaluation as evaluation_service
from forge.services import judges as judge_service

router = APIRouter(prefix="/judges", tags=["judges"])


async def _get(session: SessionDep, judge_id: uuid.UUID) -> Judge:
    judge = await session.get(Judge, judge_id)
    if judge is None:
        raise not_found("Juge introuvable")
    return judge


def _out(judge: Judge) -> JudgeOut:
    return JudgeOut.model_validate(judge, from_attributes=True)


async def _detail(session: SessionDep, judge: Judge) -> JudgeDetailOut:
    versions = await judge_service.judge_versions(session, judge.key)
    return JudgeDetailOut(
        **_out(judge).model_dump(),
        versions=[JudgeVersionSummary.model_validate(v, from_attributes=True) for v in versions],
        placeholders=list(PLACEHOLDERS),
    )


def _behaviour(body: JudgeCreateIn | JudgeVersionIn) -> dict[str, object]:
    fields = (
        "provider", "model", "model_version", "temperature", "max_tokens", "system_prompt", "rubric_template",
        "criteria", "weight", "base_url", "credential_id",
    )  # fmt: skip
    data = body.model_dump(exclude_unset=True, include=set(fields))
    if "credential_id" in data and data["credential_id"] is not None:
        data["credential_id"] = str(data["credential_id"])
    return data


@router.post(
    "", response_model=JudgeDetailOut, status_code=status.HTTP_201_CREATED, summary="Créer un juge (v1)"
)
async def create_judge(
    body: JudgeCreateIn, principal: RequireMaintainer, session: SessionDep
) -> JudgeDetailOut:
    try:
        judge = await judge_service.create_judge(
            session,
            key=body.key,
            name=body.name,
            description=body.description,
            enabled=body.enabled,
            actor=principal,
            created_by=principal.user_id,
            **_behaviour(body),
        )
    except judge_service.JudgeConflict as exc:
        raise conflict(str(exc)) from exc
    except judge_service.JudgeValidationError as exc:
        raise validation_error(str(exc)) from exc
    await session.commit()
    return await _detail(session, judge)


@router.get("", response_model=Page[JudgeOut], summary="Lister les juges")
async def list_judges(
    principal: RequireViewer,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    latest_only: bool = True,
    provider: JudgeProvider | None = None,
    enabled: bool | None = None,
    key: str | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> Page[JudgeOut]:
    params = PageParams(page=page, page_size=page_size)
    rows, total = await judge_service.list_judges(
        session, latest_only=latest_only, provider=provider, enabled=enabled, key=key, search=q,
        offset=params.offset, limit=params.page_size,
    )  # fmt: skip
    return Page[JudgeOut](items=[_out(j) for j in rows], total=total, page=page, page_size=page_size)


@router.get("/{judge_id}", response_model=JudgeDetailOut, summary="Détail d'un juge et de ses versions")
async def get_judge(judge_id: uuid.UUID, principal: RequireViewer, session: SessionDep) -> JudgeDetailOut:
    return await _detail(session, await _get(session, judge_id))


@router.post(
    "/{judge_id}/versions",
    response_model=JudgeDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une nouvelle version d'un juge",
)
async def create_version(
    judge_id: uuid.UUID, body: JudgeVersionIn, principal: RequireMaintainer, session: SessionDep
) -> JudgeDetailOut:
    judge = await _get(session, judge_id)
    changes = _behaviour(body)
    if body.name is not None:
        changes["name"] = body.name
    if body.description is not None:
        changes["description"] = body.description
    try:
        version = await judge_service.create_judge_version(
            session, judge, changes, actor=principal, created_by=principal.user_id
        )
    except judge_service.JudgeConflict as exc:
        raise conflict(str(exc)) from exc
    except judge_service.JudgeValidationError as exc:
        raise validation_error(str(exc)) from exc
    await session.commit()
    return await _detail(session, version)


@router.patch(
    "/{judge_id}", response_model=JudgeDetailOut, summary="Activer / désactiver ou renommer un juge"
)
async def update_judge(
    judge_id: uuid.UUID, body: JudgeUpdateIn, principal: RequireMaintainer, session: SessionDep
) -> JudgeDetailOut:
    judge = await _get(session, judge_id)
    await judge_service.update_judge(
        session, judge, enabled=body.enabled, name=body.name, description=body.description, actor=principal
    )
    await session.commit()
    return await _detail(session, judge)


@router.post("/{judge_id}/test", response_model=JudgeTestOut, summary="Tester un juge sur un run existant")
async def test_judge(
    judge_id: uuid.UUID, body: JudgeTestIn, principal: RequireMaintainer, session: SessionDep
) -> JudgeTestOut:
    judge = await _get(session, judge_id)
    found = await evaluation_service.get_run_for_viewer(session, body.run_id, principal)
    if found is None:
        raise not_found("Run introuvable")
    run, _scenario = found
    try:
        result = await judge_service.test_judge(session, judge, run, criteria_keys=body.criteria)
    except (LLMError, ValueError) as exc:
        raise ApiError(502, f"Test du juge impossible : {exc}", code="bad_gateway") from exc
    await session.rollback()  # nothing is persisted by a test
    return JudgeTestOut(
        judge_id=judge.id,
        run_id=run.id,
        status=result.status,
        model=result.model,
        verdicts=result.verdicts,
        missing=result.missing,
        warnings=result.warnings,
        error=result.error,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost=result.cost,
        latency_ms=result.latency_ms,
        summary=result.summary,
        prompt=result.prompt,
        persisted=False,
    )

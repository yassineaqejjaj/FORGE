"""Router ``agents``: Agent Registry (agents, immutable versions, diff, test call, prompts, model and
tool configurations). Writes require the editor role."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from forge.api.deps import RequireEditor, RequireViewer, SessionDep
from forge.api.errors import ApiError
from forge.api.routers.meta import PageQuery, platform_errors
from forge.api.schemas.agents import (
    AgentCreateIn,
    AgentOut,
    AgentTestIn,
    AgentTestOut,
    AgentUpdateIn,
    AgentVersionCreateIn,
    AgentVersionDiffOut,
    AgentVersionOut,
    AgentVersionSummary,
    CredentialRef,
    ModelConfigIn,
    ModelConfigOut,
    PromptCreateIn,
    PromptRef,
    PromptSummaryOut,
    PromptVersionOut,
    ToolConfigCreateIn,
    ToolConfigOut,
    ToolConfigRef,
)
from forge.api.schemas.common import Page
from forge.domain.types import AgentExecutionError, to_dict
from forge.infra.models import Agent, AgentVersion, ModelConfiguration
from forge.services import agents as service

router = APIRouter(tags=["agents"])


def version_summary(version: AgentVersion, model: ModelConfiguration | None = None) -> AgentVersionSummary:
    return AgentVersionSummary(
        id=version.id,
        agent_id=version.agent_id,
        version=version.version,
        version_number=version.version_number,
        adapter_kind=version.adapter_kind,
        model=model.model if model else None,
        content_hash=version.content_hash,
        changelog=version.changelog,
        contamination_warnings=len(version.contamination or []),
        parent_version_id=version.parent_version_id,
        created_by=version.created_by,
        created_at=version.created_at,
    )


def agent_out(listing: service.AgentListing) -> AgentOut:
    agent = listing.agent
    return AgentOut(
        id=agent.id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        provider=agent.provider,
        tags=list(agent.tags or []),
        metadata=dict(agent.metadata_ or {}),
        archived=agent.archived,
        owner_id=agent.owner_id,
        versions_count=listing.versions_count,
        latest_version=version_summary(listing.latest, listing.latest_model) if listing.latest else None,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def version_out(bundle: service.VersionBundle) -> AgentVersionOut:
    v, agent = bundle.version, bundle.agent
    return AgentVersionOut(
        id=v.id,
        agent_id=v.agent_id,
        agent_name=agent.name,
        agent_slug=agent.slug,
        version=v.version,
        version_number=v.version_number,
        label=f"{agent.name} v{v.version}",
        adapter_kind=v.adapter_kind,
        endpoint=v.endpoint,
        model_configuration=ModelConfigOut.model_validate(bundle.model) if bundle.model else None,
        prompt=PromptRef(id=bundle.prompt.id, name=bundle.prompt.name, version=bundle.prompt.version)
        if bundle.prompt
        else None,
        system_prompt=v.system_prompt,
        tool_configuration=ToolConfigRef(
            id=bundle.tools.id, name=bundle.tools.name, version=bundle.tools.version
        )
        if bundle.tools
        else None,
        tools=list(bundle.tools.tools) if bundle.tools else [],
        context_config=dict(v.context_config or {}),
        memory_config=dict(v.memory_config or {}),
        orchestration_config=dict(v.orchestration_config or {}),
        adapter_config=dict(v.adapter_config or {}),
        credential=CredentialRef(
            id=bundle.credential.id,
            name=bundle.credential.name,
            kind=bundle.credential.kind.value,
            secret_hint=bundle.credential.secret_hint,
        )
        if bundle.credential
        else None,
        budget=dict(v.budget or {}),
        max_concurrency=v.max_concurrency,
        metadata=dict(v.metadata_ or {}),
        changelog=v.changelog,
        parent_version_id=v.parent_version_id,
        contamination=list(v.contamination or []),
        content_hash=v.content_hash,
        created_by=v.created_by,
        created_at=v.created_at,
    )


async def _agent(session: SessionDep, agent_id: uuid.UUID) -> Agent:
    with platform_errors():
        return await service.get_agent(session, agent_id)


async def _version(session: SessionDep, version_id: uuid.UUID) -> AgentVersion:
    with platform_errors():
        return await service.get_version(session, version_id)


# --- Agents --------------------------------------------------------------------------------------


@router.get("/agents", response_model=Page[AgentOut], summary="Lister les agents")
async def list_agents(
    principal: RequireViewer,
    session: SessionDep,
    paging: PageQuery,
    q: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=100),
    provider: str | None = Query(default=None, max_length=200),
    archived: bool | None = Query(default=False, description="false (défaut), true, ou vide pour tous"),
) -> Page[AgentOut]:
    rows, total = await service.list_agents(
        session,
        q=q,
        tag=tag,
        provider=provider,
        archived=archived,
        offset=paging.offset,
        limit=paging.page_size,
    )
    return Page[AgentOut](
        items=[agent_out(r) for r in rows], total=total, page=paging.page, page_size=paging.page_size
    )


@router.post(
    "/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED, summary="Créer un agent"
)
async def create_agent(body: AgentCreateIn, principal: RequireEditor, session: SessionDep) -> AgentOut:
    with platform_errors():
        agent = await service.create_agent(
            session,
            principal,
            name=body.name,
            slug=body.slug,
            description=body.description,
            provider=body.provider,
            tags=body.tags,
            metadata=body.metadata,
            owner_id=principal.user_id,
        )
    await session.commit()
    return agent_out(await service.agent_listing(session, agent))


@router.get("/agents/{agent_id}", response_model=AgentOut, summary="Détail d'un agent")
async def get_agent(agent_id: uuid.UUID, principal: RequireViewer, session: SessionDep) -> AgentOut:
    return agent_out(await service.agent_listing(session, await _agent(session, agent_id)))


@router.patch(
    "/agents/{agent_id}", response_model=AgentOut, summary="Modifier un agent (métadonnées, archivage)"
)
async def update_agent(
    agent_id: uuid.UUID, body: AgentUpdateIn, principal: RequireEditor, session: SessionDep
) -> AgentOut:
    agent = await _agent(session, agent_id)
    with platform_errors():
        await service.update_agent(session, principal, agent, body.model_dump(exclude_unset=True))
    await session.commit()
    return agent_out(await service.agent_listing(session, agent))


@router.get(
    "/agents/{agent_id}/versions", response_model=list[AgentVersionSummary], summary="Versions d'un agent"
)
async def list_versions(
    agent_id: uuid.UUID, principal: RequireViewer, session: SessionDep
) -> list[AgentVersionSummary]:
    agent = await _agent(session, agent_id)
    versions = await service.list_versions(session, agent.id)
    model_ids = {v.model_configuration_id for v in versions if v.model_configuration_id}
    models: dict[uuid.UUID, ModelConfiguration] = {}
    if model_ids:
        rows = await session.scalars(select(ModelConfiguration).where(ModelConfiguration.id.in_(model_ids)))
        models = {m.id: m for m in rows}
    return [
        version_summary(v, models.get(v.model_configuration_id) if v.model_configuration_id else None)
        for v in versions
    ]


@router.post(
    "/agents/{agent_id}/versions",
    response_model=AgentVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une version (champs explicites ou version de base + modifications)",
)
async def create_version(
    agent_id: uuid.UUID, body: AgentVersionCreateIn, principal: RequireEditor, session: SessionDep
) -> AgentVersionOut:
    agent = await _agent(session, agent_id)
    with platform_errors():
        version = await service.create_version(
            session, principal, agent, body.model_dump(exclude_unset=True), created_by=principal.user_id
        )
    await session.commit()
    return version_out(await service.load_bundle(session, version))


@router.get(
    "/agent-versions/{version_id}", response_model=AgentVersionOut, summary="Détail d'une version d'agent"
)
async def get_version(
    version_id: uuid.UUID, principal: RequireViewer, session: SessionDep
) -> AgentVersionOut:
    return version_out(await service.load_bundle(session, await _version(session, version_id)))


@router.get(
    "/agent-versions/{version_id}/diff",
    response_model=AgentVersionDiffOut,
    summary="Différences entre deux versions",
)
async def diff_version(
    version_id: uuid.UUID,
    principal: RequireViewer,
    session: SessionDep,
    against: uuid.UUID | None = Query(
        default=None, description="Version de référence (défaut : version parente)"
    ),
) -> AgentVersionDiffOut:
    target = await _version(session, version_id)
    reference = await _version(session, against) if against else None
    with platform_errors():
        diff = await service.diff_versions(session, target, reference)
    return AgentVersionDiffOut(**diff)


@router.post(
    "/agent-versions/{version_id}/test", response_model=AgentTestOut, summary="Appel de test de l'agent"
)
async def test_version(
    version_id: uuid.UUID, body: AgentTestIn, principal: RequireEditor, session: SessionDep
) -> AgentTestOut:
    from forge.services import execution

    version = await _version(session, version_id)
    try:
        result = await execution.invoke_adhoc(session, version, input=body.input, context=body.context)
    except NotImplementedError as exc:
        raise ApiError(501, str(exc) or "Appel de test non disponible", code="not_implemented") from exc
    except AgentExecutionError as exc:
        raise ApiError(502, f"Échec de l'appel à l'agent : {exc}", code="bad_gateway") from exc
    await session.commit()
    data: Any = to_dict(result)
    if not isinstance(data, dict):
        data = {"output": data}
    return AgentTestOut(
        agent_version_id=version.id,
        output_text=data.get("output_text") if isinstance(data.get("output_text"), str) else None,
        output_json=data.get("output_json"),
        result=data,
    )


# --- Prompts -------------------------------------------------------------------------------------


@router.get(
    "/prompts", response_model=list[PromptSummaryOut], summary="Prompts (dernière version de chaque nom)"
)
async def list_prompts(
    principal: RequireViewer, session: SessionDep, q: str | None = Query(default=None, max_length=100)
) -> list[PromptSummaryOut]:
    return [
        PromptSummaryOut(
            name=p.name,
            latest_version=p.version,
            versions_count=count,
            latest_version_id=p.id,
            description=p.description,
            content_hash=p.content_hash,
            updated_at=p.created_at,
        )
        for p, count in await service.list_prompts(session, q=q)
    ]


@router.post(
    "/prompts",
    response_model=PromptVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Nouvelle version de prompt",
)
async def create_prompt(
    body: PromptCreateIn, principal: RequireEditor, session: SessionDep
) -> PromptVersionOut:
    with platform_errors():
        prompt = await service.create_prompt_version(
            session,
            principal,
            name=body.name,
            content=body.content,
            description=body.description,
            variables=body.variables,
            created_by=principal.user_id,
        )
    await session.commit()
    return PromptVersionOut.model_validate(prompt)


@router.get("/prompts/{name}/versions", response_model=list[PromptVersionOut], summary="Versions d'un prompt")
async def list_prompt_versions(
    name: str, principal: RequireViewer, session: SessionDep
) -> list[PromptVersionOut]:
    with platform_errors():
        rows = await service.list_prompt_versions(session, name)
    return [PromptVersionOut.model_validate(p) for p in rows]


# --- Model & tool configurations -----------------------------------------------------------------


@router.get("/model-configurations", response_model=Page[ModelConfigOut], summary="Configurations de modèle")
async def list_model_configurations(
    principal: RequireViewer,
    session: SessionDep,
    paging: PageQuery,
    q: str | None = Query(default=None, max_length=200),
) -> Page[ModelConfigOut]:
    rows, total = await service.list_model_configurations(
        session, q=q, offset=paging.offset, limit=paging.page_size
    )
    return Page[ModelConfigOut](
        items=[ModelConfigOut.model_validate(m) for m in rows],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post(
    "/model-configurations",
    response_model=ModelConfigOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer (ou réutiliser à l'identique) une configuration de modèle",
)
async def create_model_configuration(
    body: ModelConfigIn, principal: RequireEditor, session: SessionDep
) -> ModelConfigOut:
    with platform_errors():
        model, _created = await service.ensure_model_configuration(
            session, principal, body.model_dump(), created_by=principal.user_id
        )
    await session.commit()
    return ModelConfigOut.model_validate(model)


@router.get("/tool-configurations", response_model=Page[ToolConfigOut], summary="Configurations d'outils")
async def list_tool_configurations(
    principal: RequireViewer,
    session: SessionDep,
    paging: PageQuery,
    name: str | None = Query(default=None, max_length=100),
) -> Page[ToolConfigOut]:
    rows, total = await service.list_tool_configurations(
        session, name=name, offset=paging.offset, limit=paging.page_size
    )
    return Page[ToolConfigOut](
        items=[ToolConfigOut.model_validate(t) for t in rows],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post(
    "/tool-configurations",
    response_model=ToolConfigOut,
    status_code=status.HTTP_201_CREATED,
    summary="Nouvelle version d'une configuration d'outils",
)
async def create_tool_configuration(
    body: ToolConfigCreateIn, principal: RequireEditor, session: SessionDep
) -> ToolConfigOut:
    with platform_errors():
        config = await service.create_tool_configuration(
            session,
            principal,
            name=body.name,
            tools=[t.model_dump() for t in body.tools],
            description=body.description,
            created_by=principal.user_id,
        )
    await session.commit()
    return ToolConfigOut.model_validate(config)

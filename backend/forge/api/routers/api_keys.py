"""Router ``api_keys``: service API keys (admin, §3.1). The full key is returned once."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response, status

from forge.api.deps import RequireAdmin, SessionDep
from forge.api.errors import not_found
from forge.api.routers.meta import PageQuery, platform_errors
from forge.api.schemas.api_keys import ApiKeyCreatedOut, ApiKeyCreateIn, ApiKeyOut
from forge.api.schemas.common import Page
from forge.infra.models import ApiKey
from forge.infra.security import mask_api_key
from forge.services import api_keys as service

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _out(key: ApiKey) -> dict[str, Any]:
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.prefix,
        "masked_key": mask_api_key(key.prefix),
        "role": key.role,
        "clearance": key.clearance,
        "scopes": list(key.scopes or []),
        "created_by": key.created_by,
        "created_at": key.created_at,
        "expires_at": key.expires_at,
        "last_used_at": key.last_used_at,
        "revoked_at": key.revoked_at,
        "active": service.is_active(key),
    }


@router.get("", response_model=Page[ApiKeyOut], summary="Lister les clés d'API (masquées)")
async def list_api_keys(
    admin: RequireAdmin,
    session: SessionDep,
    paging: PageQuery,
    include_revoked: bool = True,
) -> Page[ApiKeyOut]:
    rows, total = await service.list_api_keys(
        session, include_revoked=include_revoked, offset=paging.offset, limit=paging.page_size
    )
    return Page[ApiKeyOut](
        items=[ApiKeyOut(**_out(k)) for k in rows], total=total, page=paging.page, page_size=paging.page_size
    )


@router.post(
    "", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED, summary="Créer une clé d'API"
)
async def create_api_key(body: ApiKeyCreateIn, admin: RequireAdmin, session: SessionDep) -> ApiKeyCreatedOut:
    with platform_errors():
        key, full = await service.create_api_key(
            session,
            admin,
            name=body.name,
            role=body.role,
            clearance=body.clearance,
            scopes=body.scopes,
            expires_at=body.expires_at,
            created_by=admin.user_id,
        )
    await session.commit()
    return ApiKeyCreatedOut(**_out(key), key=full)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Révoquer une clé d'API")
async def revoke_api_key(key_id: uuid.UUID, admin: RequireAdmin, session: SessionDep) -> Response:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise not_found("Clé d'API introuvable")
    with platform_errors():
        await service.revoke_api_key(session, admin, key)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Router ``audit``: audit log (maintainer / admin)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from forge.api.deps import RequireMaintainer, SessionDep
from forge.api.routers.meta import PageQuery
from forge.api.schemas.audit import AuditEventOut
from forge.api.schemas.common import Page
from forge.services import audit as audit_service

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=Page[AuditEventOut], summary="Journal d'audit")
async def list_audit_events(
    principal: RequireMaintainer,
    session: SessionDep,
    paging: PageQuery,
    action: str | None = Query(
        default=None, max_length=100, description="Action exacte ou préfixe (« agent »)"
    ),
    target_type: str | None = Query(default=None, max_length=100),
    target_id: str | None = Query(default=None, max_length=100),
    actor_id: uuid.UUID | None = None,
) -> Page[AuditEventOut]:
    rows, total = await audit_service.list_events(
        session,
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_id=actor_id,
        offset=paging.offset,
        limit=paging.page_size,
    )
    return Page[AuditEventOut](
        items=[AuditEventOut.model_validate(r) for r in rows],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )

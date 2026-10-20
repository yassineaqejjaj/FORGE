"""Service API keys ``fgk_<prefix8>_<secret32>`` (docs/ARCHITECTURE.md §3.1).

Only the SHA-256 of a key is stored; the full key is returned once by :func:`create_api_key`.
Keys with ``scopes=["traces:write"]`` can only push traces (keys handed to agents).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import Role
from forge.infra.db import utcnow
from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID, ApiKey, Project
from forge.infra.security import generate_api_key
from forge.infra.workspace_scope import session_workspace
from forge.services import audit
from forge.services.audit import ActorLike
from forge.services.taxonomy import ConflictError, InvalidError, NotFoundError

ALLOWED_SCOPES: frozenset[str] = frozenset({"traces:write"})


def is_active(key: ApiKey, *, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return key.revoked_at is None and (key.expires_at is None or key.expires_at > now)


async def create_api_key(
    session: AsyncSession,
    actor: ActorLike,
    *,
    name: str,
    role: Role,
    clearance: int = 1,
    scopes: Sequence[str] = (),
    expires_at: datetime | None = None,
    created_by: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> tuple[ApiKey, str]:
    """Create a key; returns ``(row, full_key)`` — the full key is never retrievable again.

    The key belongs to ``workspace_id`` (else the session's workspace, else the default one) and optionally to
    one of its projects. ``FORGE_API_KEY_MAX_DAYS`` bounds its life when set.
    """
    name = name.strip()
    if not name:
        raise InvalidError("Nom de clé requis")
    unknown = set(scopes) - ALLOWED_SCOPES
    if unknown:
        raise InvalidError(f"Portée(s) inconnue(s) : {', '.join(sorted(unknown))} (autorisée : traces:write)")
    if not 0 <= int(clearance) <= 3:
        raise InvalidError("Habilitation attendue : 0 à 3")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            raise InvalidError("La date d'expiration doit préciser le fuseau horaire (ISO 8601)")
        if expires_at <= utcnow():
            raise InvalidError("La date d'expiration doit être dans le futur")
    if settings.api_key_max_days:
        latest = utcnow() + timedelta(days=settings.api_key_max_days)
        if expires_at is None or expires_at > latest:
            raise InvalidError(
                f"Durée de vie maximale d'une clé : {settings.api_key_max_days} jours (expires_at requis)"
            )
    workspace = workspace_id or session_workspace(session) or ORION_DEFAULT_WORKSPACE_ID
    if project_id is not None:
        owned = await session.scalar(
            select(Project.id).where(Project.id == project_id, Project.workspace_id == workspace)
        )
        if owned is None:
            raise NotFoundError("Projet introuvable dans cet espace")
    generated = generate_api_key()
    key = ApiKey(
        workspace_id=workspace,
        project_id=project_id,
        name=name,
        prefix=generated.prefix,
        key_hash=generated.key_hash,
        role=Role(role),
        clearance=int(clearance),
        scopes=sorted(set(scopes)),
        created_by=created_by,
        expires_at=expires_at,
    )
    session.add(key)
    await session.flush()
    await audit.record(
        session,
        actor,
        "api_key.create",
        "api_key",
        key.id,
        summary=f"Création de la clé d'API « {name} » ({key.role.value})",
        details={
            "prefix": key.prefix,
            "role": key.role,
            "clearance": key.clearance,
            "scopes": key.scopes,
            "expires_at": expires_at,
            "workspace_id": workspace,
            "project_id": project_id,
        },
    )
    return key, generated.key


async def list_api_keys(
    session: AsyncSession, *, include_revoked: bool = True, offset: int = 0, limit: int = 50
) -> tuple[list[ApiKey], int]:
    conditions = [] if include_revoked else [ApiKey.revoked_at.is_(None)]
    total = await session.scalar(select(func.count()).select_from(ApiKey).where(*conditions))
    rows = await session.scalars(
        select(ApiKey)
        .where(*conditions)
        .order_by(ApiKey.revoked_at.is_not(None), ApiKey.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)


async def revoke_api_key(session: AsyncSession, actor: ActorLike, key: ApiKey) -> ApiKey:
    if key.revoked_at is not None:
        raise ConflictError("Cette clé d'API est déjà révoquée")
    key.revoked_at = utcnow()
    await session.flush()
    await audit.record(
        session,
        actor,
        "api_key.revoke",
        "api_key",
        key.id,
        summary=f"Révocation de la clé d'API « {key.name} »",
        details={"prefix": key.prefix},
    )
    return key


async def rotate_api_key(
    session: AsyncSession, actor: ActorLike, key: ApiKey, *, grace_hours: int = 24
) -> tuple[ApiKey, str]:
    """Replace ``key`` by a successor with the same workspace, project, role, clearance and scopes.

    The old key keeps working for ``grace_hours`` (so a deployment can switch over) and is then expired; with
    ``0`` it is revoked at once. The new key's secret is returned once; nothing secret is audited.
    """
    if key.revoked_at is not None:
        raise ConflictError("Cette clé d'API est révoquée : créez-en une nouvelle")
    if not 0 <= grace_hours <= 24 * 7:
        raise InvalidError("Délai de grâce attendu : 0 à 168 heures")
    now = utcnow()
    expires_at = key.expires_at
    if settings.api_key_max_days:
        latest = now + timedelta(days=settings.api_key_max_days)
        expires_at = latest if expires_at is None or expires_at > latest else expires_at
    if expires_at is not None and expires_at <= now:
        expires_at = (now + timedelta(days=settings.api_key_max_days)) if settings.api_key_max_days else None
    successor, full = await create_api_key(
        session,
        actor,
        name=key.name,
        role=key.role,
        clearance=key.clearance,
        scopes=list(key.scopes or []),
        expires_at=expires_at,
        created_by=key.created_by,
        project_id=key.project_id,
        workspace_id=key.workspace_id,
    )
    if grace_hours == 0:
        key.revoked_at = now
    elif key.expires_at is None or key.expires_at > now + timedelta(hours=grace_hours):
        key.expires_at = now + timedelta(hours=grace_hours)
    await session.flush()
    await audit.record(
        session,
        actor,
        "api_key.rotate",
        "api_key",
        key.id,
        summary=f"Rotation de la clé d'API « {key.name} »",
        details={
            "old": key.prefix,
            "new": successor.prefix,
            "successor_id": successor.id,
            "grace_hours": grace_hours,
        },
    )
    return successor, full


async def revoke_keys_of_project(
    session: AsyncSession, actor: ActorLike, project_id: uuid.UUID, *, reason: str
) -> int:
    """Revoke every active key attached to a project (it left its workspace). Flush; caller commits."""
    keys = list(
        await session.scalars(
            select(ApiKey).where(ApiKey.project_id == project_id, ApiKey.revoked_at.is_(None))
        )
    )
    for key in keys:
        key.revoked_at = utcnow()
        await audit.record(
            session,
            actor,
            "api_key.revoke",
            "api_key",
            key.id,
            summary=f"Révocation de la clé d'API « {key.name} » : {reason}",
            details={"prefix": key.prefix, "reason": reason},
        )
    await session.flush()
    return len(keys)

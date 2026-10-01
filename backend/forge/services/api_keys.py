"""Service API keys ``fgk_<prefix8>_<secret32>`` (docs/ARCHITECTURE.md §3.1).

Only the SHA-256 of a key is stored; the full key is returned once by :func:`create_api_key`.
Keys with ``scopes=["traces:write"]`` can only push traces (keys handed to agents).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import Role
from forge.infra.db import utcnow
from forge.infra.models import ApiKey
from forge.infra.security import generate_api_key
from forge.services import audit
from forge.services.audit import ActorLike
from forge.services.taxonomy import ConflictError, InvalidError

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
) -> tuple[ApiKey, str]:
    """Create a key; returns ``(row, full_key)`` — the full key is never retrievable again."""
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
    generated = generate_api_key()
    key = ApiKey(
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

"""Audit trail writer & reader (docs/ARCHITECTURE.md §9).

``record()`` only adds the row to the session: it is committed with the caller's transaction, so an
action and its audit entry succeed or fail together. Evaluation decisions (scores, gates, verdicts)
are audited by the evaluation engine with ``target_type="evaluation_run"``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import ActorType
from forge.infra.models import AuditEvent, User
from forge.infra.observability.context import get_request_id

SYSTEM_LABEL = "Système FORGE"


@dataclass(frozen=True, slots=True)
class Actor:
    type: ActorType
    id: uuid.UUID | None
    label: str

    @classmethod
    def system(cls, label: str = SYSTEM_LABEL) -> Actor:
        return cls(ActorType.system, None, label)

    @classmethod
    def from_user(cls, user: User) -> Actor:
        return cls(ActorType.user, user.id, user.full_name or user.email)


class _HasActor(Protocol):
    @property
    def actor(self) -> Actor: ...


ActorLike = Actor | User | _HasActor | None


def resolve_actor(actor: ActorLike) -> Actor:
    """Accept an :class:`Actor`, a ``Principal`` (``.actor``), a ``User`` or ``None`` (system)."""
    if actor is None:
        return Actor.system()
    if isinstance(actor, Actor):
        return actor
    if isinstance(actor, User):
        return Actor.from_user(actor)
    resolved = getattr(actor, "actor", None)
    if isinstance(resolved, Actor):
        return resolved
    raise TypeError(f"Unsupported audit actor: {type(actor).__name__}")


async def record(
    session: AsyncSession,
    actor: ActorLike,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str | None = None,
    summary: str = "",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an audit entry to the current transaction (the caller commits).

    ``action`` is ``<domain>.<verb>`` (``agent_version.create``, ``run.evaluate``, ``judge.create``…).
    """
    resolved = resolve_actor(actor)
    entry = AuditEvent(
        actor_type=resolved.type,
        actor_id=resolved.id,
        actor_label=resolved.label,
        action=str(action),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        summary=summary or action,
        details=jsonable(details or {}),
        request_id=get_request_id(),
    )
    session.add(entry)
    return entry


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def list_events(
    session: AsyncSession,
    *,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    actor_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[AuditEvent], int]:
    """Audit entries, newest first. ``action`` matches exactly or as a ``<domain>`` prefix."""
    conditions: list[Any] = []
    if action:
        action = action.strip().removesuffix(".*")
        conditions.append(or_(AuditEvent.action == action, AuditEvent.action.startswith(f"{action}.")))
    if target_type:
        conditions.append(AuditEvent.target_type == target_type)
    if target_id:
        conditions.append(AuditEvent.target_id == target_id)
    if actor_id:
        conditions.append(AuditEvent.actor_id == actor_id)
    total = await session.scalar(select(func.count()).select_from(AuditEvent).where(*conditions))
    rows = await session.scalars(
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)

"""User management helpers (creation, lookup, bootstrap administrator)."""

from __future__ import annotations

import hashlib
import logging
import uuid

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import Role
from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID, User, WorkspaceMember
from forge.infra.observability.metrics import record_workspace_violation
from forge.infra.security import hash_password
from forge.infra.workspace_scope import enforcement_mode, session_workspace

logger = logging.getLogger("forge.users")

AVATAR_PALETTE: tuple[str, ...] = (
    "#ea580c", "#0891b2", "#059669", "#d97706", "#dc2626",
    "#7c3aed", "#db2777", "#2563eb", "#0d9488", "#4f46e5",
)  # fmt: skip


def normalize_email(email: str) -> str:
    return email.strip().lower()


def avatar_color_for(email: str) -> str:
    digest = hashlib.sha256(email.lower().encode()).digest()
    return AVATAR_PALETTE[digest[0] % len(AVATAR_PALETTE)]


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == normalize_email(email)))


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    password: str,
    role: Role = Role.viewer,
    clearance: int = 1,
    workspace_id: uuid.UUID | None = None,
) -> User:
    """Create (and flush) a user. The e-mail must be unique (caller checks, DB enforces).

    The user joins ``workspace_id``, else the workspace of the (bound) session, else the default one.
    """
    normalized = normalize_email(email)
    user = User(
        email=normalized,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role=role,
        clearance=clearance,
        avatar_color=avatar_color_for(normalized),
    )
    session.add(user)
    await session.flush()
    session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace_id or session_workspace(session) or ORION_DEFAULT_WORKSPACE_ID,
        )
    )
    await session.flush()
    return user


def in_workspace(workspace_id: uuid.UUID) -> ColumnElement[bool]:
    """Users of a workspace: its members (users without a membership row belong to the default one)."""
    members = select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id)
    condition: ColumnElement[bool] = User.id.in_(members)
    if workspace_id == ORION_DEFAULT_WORKSPACE_ID:
        condition = or_(condition, User.id.not_in(select(WorkspaceMember.user_id)))
    return condition


def scope_conditions(session: AsyncSession) -> list[ColumnElement[bool]]:
    """Extra ``WHERE`` terms restricting user queries to the caller's workspace (``enforce`` only).

    ``users`` has no ``workspace_id`` column (membership is its own table), so the generic session
    filter does not cover it: the user queries of the API apply this explicitly.
    """
    workspace_id = session_workspace(session)
    if workspace_id is None or enforcement_mode() != "enforce":
        return []
    return [in_workspace(workspace_id)]


async def report_foreign_users(session: AsyncSession, user_ids: list[uuid.UUID]) -> int:
    """``shadow`` mode: count (and log) users read outside the caller's workspace; serves nothing less."""
    workspace_id = session_workspace(session)
    if workspace_id is None or enforcement_mode() != "shadow" or not user_ids:
        return 0
    inside = set(
        await session.scalars(select(User.id).where(User.id.in_(user_ids), in_workspace(workspace_id)))
    )
    foreign = [uid for uid in user_ids if uid not in inside]
    for _ in foreign:
        record_workspace_violation("users", "shadow")
    if foreign:
        logger.warning(
            "workspace violation (shadow): %d user(s) read outside workspace %s", len(foreign), workspace_id
        )
    return len(foreign)


async def ensure_bootstrap_admin(session: AsyncSession) -> User | None:
    """Create the bootstrap administrator when the database has no user at all (clearance C3)."""
    existing = await session.scalar(select(func.count()).select_from(User))
    if existing:
        return None
    user = await create_user(
        session,
        email=settings.bootstrap_admin_email,
        full_name=settings.bootstrap_admin_name,
        password=settings.bootstrap_admin_password,
        role=Role.admin,
        clearance=3,
    )
    await session.commit()
    logger.info("Bootstrap administrator created: %s", user.email)
    return user

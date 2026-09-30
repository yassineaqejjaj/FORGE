"""User management helpers (creation, lookup, bootstrap administrator)."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import Role
from forge.infra.models import User
from forge.infra.security import hash_password

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
) -> User:
    """Create (and flush) a user. The e-mail must be unique (caller checks, DB enforces)."""
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
    return user


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

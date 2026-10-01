"""Router ``users``: platform user administration (admin, §3.2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.api.deps import RequireAdmin, SessionDep
from forge.api.errors import conflict, not_found
from forge.api.routers.meta import PageQuery
from forge.api.schemas.common import Page
from forge.api.schemas.users import UserCreateIn, UserOut, UserUpdateIn
from forge.domain.enums import Role
from forge.infra.models import User
from forge.infra.security import hash_password
from forge.services import audit
from forge.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])

LAST_ADMIN_MESSAGE = "Impossible de retirer le dernier administrateur actif de la plateforme"


async def _active_admins(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count()).select_from(User).where(User.role == Role.admin, User.active.is_(True))
    )
    return int(count or 0)


@router.get("", response_model=Page[UserOut], summary="Lister les utilisateurs")
async def list_users(
    admin: RequireAdmin,
    session: SessionDep,
    paging: PageQuery,
    q: str | None = Query(default=None, max_length=200, description="E-mail ou nom"),
    role: Role | None = None,
    active: bool | None = None,
) -> Page[UserOut]:
    conditions = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
    if role is not None:
        conditions.append(User.role == role)
    if active is not None:
        conditions.append(User.active.is_(active))
    total = await session.scalar(select(func.count()).select_from(User).where(*conditions))
    rows = await session.scalars(
        select(User)
        .where(*conditions)
        .order_by(User.full_name, User.email)
        .offset(paging.offset)
        .limit(paging.page_size)
    )
    return Page[UserOut](
        items=[UserOut.model_validate(u) for u in rows],
        total=int(total or 0),
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Créer un utilisateur")
async def create_user(body: UserCreateIn, admin: RequireAdmin, session: SessionDep) -> UserOut:
    if await user_service.get_by_email(session, body.email):
        raise conflict("Un utilisateur existe déjà avec cette adresse e-mail")
    user = await user_service.create_user(
        session,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
        role=body.role,
        clearance=body.clearance,
    )
    await audit.record(
        session,
        admin,
        "user.create",
        "user",
        user.id,
        summary=f"Création de l'utilisateur {user.full_name} ({user.email})",
        details={"role": user.role, "clearance": user.clearance},
    )
    await session.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut, summary="Modifier un utilisateur")
async def update_user(
    user_id: uuid.UUID, body: UserUpdateIn, admin: RequireAdmin, session: SessionDep
) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("Utilisateur introuvable")
    changes: dict[str, object] = {}
    if body.full_name is not None and body.full_name.strip() != user.full_name:
        changes["full_name"] = body.full_name.strip()
        user.full_name = body.full_name.strip()
    loses_admin = (body.role is not None and body.role != Role.admin) or body.active is False
    if user.role == Role.admin and user.active and loses_admin and await _active_admins(session) <= 1:
        raise conflict(LAST_ADMIN_MESSAGE)
    if body.role is not None and body.role != user.role:
        changes["role"] = {"from": user.role, "to": body.role}
        user.role = body.role
    if body.clearance is not None and body.clearance != user.clearance:
        changes["clearance"] = {"from": user.clearance, "to": body.clearance}
        user.clearance = body.clearance
    if body.active is not None and body.active != user.active:
        changes["active"] = body.active
        user.active = body.active
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        changes["password"] = "réinitialisé"
    if changes:
        await audit.record(
            session,
            admin,
            "user.update",
            "user",
            user.id,
            summary=f"Modification de l'utilisateur {user.full_name}",
            details={"changes": changes},
        )
        await session.commit()
    return UserOut.model_validate(user)

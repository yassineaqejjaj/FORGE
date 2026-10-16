"""Workspaces, projects and memberships (ADR 001 §5, ticket NOV-105, docs/WORKSPACES.md).

The workspace of a caller is derived from the validated identity only: a user's membership row (a user
without a row belongs to the default workspace), or the workspace stamped on an API key.
"""

from __future__ import annotations

import contextlib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.infra.models import (
    ORION_DEFAULT_WORKSPACE_ID,
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from forge.services.taxonomy import ConflictError, InvalidError, NotFoundError

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


async def workspace_id_of_user(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """The workspace a user acts in (default workspace without a membership row)."""
    workspace_id = await session.scalar(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    )
    return workspace_id or ORION_DEFAULT_WORKSPACE_ID


def _check_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not SLUG_PATTERN.fullmatch(slug) or len(slug) > 64:
        raise InvalidError("Alias invalide : minuscules, chiffres, '-' et '_' (64 caractères au plus)")
    return slug


async def get_workspace(session: AsyncSession, ref: str | uuid.UUID) -> Workspace:
    """A workspace by ``orion_workspace_id`` or slug."""
    condition = Workspace.slug == str(ref)
    with contextlib.suppress(ValueError):
        condition = Workspace.id == (ref if isinstance(ref, uuid.UUID) else uuid.UUID(str(ref)))
    workspace = await session.scalar(select(Workspace).where(condition))
    if workspace is None:
        raise NotFoundError("Espace introuvable")
    return workspace


async def list_workspaces(session: AsyncSession) -> list[Workspace]:
    return list(await session.scalars(select(Workspace).order_by(Workspace.created_at, Workspace.slug)))


async def create_workspace(
    session: AsyncSession, *, slug: str, name: str, workspace_id: uuid.UUID | None = None
) -> Workspace:
    """Create (and flush) a workspace. The id is immutable; it normally comes from the IdP."""
    slug = _check_slug(slug)
    name = name.strip()
    if not name:
        raise InvalidError("Nom d'espace requis")
    if await session.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        raise ConflictError("Un espace existe déjà avec cet alias")
    workspace = Workspace(id=workspace_id or uuid.uuid4(), slug=slug, name=name)
    session.add(workspace)
    await session.flush()
    return workspace


async def create_project(
    session: AsyncSession,
    workspace: Workspace,
    *,
    slug: str,
    name: str,
    project_id: uuid.UUID | None = None,
) -> Project:
    """Create (and flush) a project of ``workspace`` (``orion_project_id`` is globally unique)."""
    slug = _check_slug(slug)
    name = name.strip()
    if not name:
        raise InvalidError("Nom de projet requis")
    exists = await session.scalar(
        select(Project.id).where(Project.workspace_id == workspace.id, Project.slug == slug)
    )
    if exists:
        raise ConflictError("Un projet existe déjà avec cet alias dans cet espace")
    project = Project(id=project_id or uuid.uuid4(), workspace_id=workspace.id, slug=slug, name=name)
    session.add(project)
    await session.flush()
    return project


async def list_projects(session: AsyncSession, workspace: Workspace) -> list[Project]:
    return list(
        await session.scalars(
            select(Project).where(Project.workspace_id == workspace.id).order_by(Project.slug)
        )
    )


async def set_membership(session: AsyncSession, user: User, workspace: Workspace) -> WorkspaceMember:
    """Place a user in a workspace (one workspace per user: ADR §3 — several spaces, several accounts)."""
    member = await session.get(WorkspaceMember, user.id)
    if member is None:
        member = WorkspaceMember(user_id=user.id, workspace_id=workspace.id)
        session.add(member)
    else:
        member.workspace_id = workspace.id
    await session.flush()
    return member

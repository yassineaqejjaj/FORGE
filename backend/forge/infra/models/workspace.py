"""ORION workspace / project model (ADR 001 §5, §9; ticket NOV-105).

* ``orion_workspace_id`` — the *space*: isolation boundary of a company. Every tenant resource carries
  exactly one ``workspace_id`` (``NOT NULL``, defaults to :data:`ORION_DEFAULT_WORKSPACE_ID`, which the
  migration creates and assigns every pre-existing row to).
* ``orion_project_id`` — the ORION *project* (globally unique, bound to one workspace). ``project_id`` is
  nullable on the main resources: ``NULL`` = workspace-wide resource.

Both identifiers are immutable. The workspace of a request comes from the validated identity (the user's
membership or the API key), never from a parameter or a header (see ``forge.infra.workspace_scope``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from forge.domain.enums import Role
from forge.infra.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin
from forge.infra.models._types import StrEnumType, enum_check

#: The workspace that owns every row created before the workspace model existed (and every row created
#: without an explicit workspace). Fixed and documented (docs/WORKSPACES.md): never change it, it is the
#: ``server_default`` of every ``workspace_id`` column.
ORION_DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_WORKSPACE_SLUG = "default"


class WorkspaceScopedMixin:
    """``workspace_id NOT NULL`` (default workspace) — the isolation key of a tenant table."""

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        server_default=text(f"'{ORION_DEFAULT_WORKSPACE_ID}'"),
        sort_order=90,
    )


class ProjectScopedMixin(WorkspaceScopedMixin):
    """Adds the optional ORION project (``NULL`` = workspace-wide)."""

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=True,
        sort_order=91,
    )


class Workspace(UUIDPkMixin, TimestampMixin, Base):
    """An ORION space (``orion_workspace_id`` = ``id``). Created and governed in the IdP (ADR §5)."""

    __tablename__ = "workspaces"
    __table_args__ = (Index("uq_workspaces_slug", "slug", unique=True),)

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Project(UUIDPkMixin, TimestampMixin, Base):
    """An ORION project (``orion_project_id`` = ``id``), attached to exactly one workspace."""

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "slug"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    #: Readable alias, mutable; the id is what tokens, logs and runs carry.
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class WorkspaceMember(CreatedAtMixin, Base):
    """A user belongs to **one** workspace (ADR §3: several spaces = several sessions, never a list).

    A user without a row is a member of the default workspace (today's behaviour).
    """

    __tablename__ = "workspace_members"
    __table_args__ = (Index("ix_workspace_members_workspace_id", "workspace_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )


class ProjectMember(CreatedAtMixin, Base):
    """Optional per-project role of a workspace member (the global role stays the default)."""

    __tablename__ = "project_members"
    __table_args__ = (enum_check("role", Role), Index("ix_project_members_user_id", "user_id"))

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(StrEnumType(Role), nullable=False)

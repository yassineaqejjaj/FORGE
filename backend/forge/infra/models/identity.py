"""Identities and governance: users, API keys, provider credentials, audit log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from forge.domain.enums import ActorType, ProviderKind, Role
from forge.infra.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin
from forge.infra.models._types import StrEnumType, enum_check, range_check

DEFAULT_AVATAR_COLOR = "#ea580c"


class User(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        enum_check("role", Role),
        range_check("clearance", 0, 3),
        Index("uq_users_email", "email", unique=True),
    )

    email: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(
        StrEnumType(Role), nullable=False, default=Role.viewer, server_default=text("'viewer'")
    )
    #: Highest scenario classification the user may see (C0–C3).
    clearance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default=text("1"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    avatar_color: Mapped[str] = mapped_column(
        Text, nullable=False, default=DEFAULT_AVATAR_COLOR, server_default=text(f"'{DEFAULT_AVATAR_COLOR}'")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Set when the user finishes (or skips) the first-login welcome tour; ``NULL`` = not onboarded yet.
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(UUIDPkMixin, CreatedAtMixin, Base):
    """Service keys (CI pipelines, NOVA, agents pushing traces). Format ``fgk_<prefix8>_<secret32>``."""

    __tablename__ = "api_keys"
    __table_args__ = (
        enum_check("role", Role),
        range_check("clearance", 0, 3),
        Index("uq_api_keys_prefix", "prefix", unique=True),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(StrEnumType(Role), nullable=False)
    clearance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default=text("1"))
    #: Optional restriction: ``["traces:write"]`` for keys given to agents (OTLP push only).
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderCredential(UUIDPkMixin, TimestampMixin, Base):
    """Encrypted secret (API key, bearer token, extra headers) referenced by agents and judges.

    Secrets are encrypted with Fernet (``FORGE_SECRETS_KEY``) and never returned by the API: only
    ``secret_hint`` (last 4 characters) is shown.
    """

    __tablename__ = "provider_credentials"
    __table_args__ = (
        enum_check("kind", ProviderKind),
        Index("uq_provider_credentials_name", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[ProviderKind] = mapped_column(StrEnumType(ProviderKind), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Encrypted JSON object of extra headers (``{"X-Tenant": "…"}``).
    headers_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(UUIDPkMixin, CreatedAtMixin, Base):
    """Append-only audit log of every mutation and every evaluation decision."""

    __tablename__ = "audit_events"
    __table_args__ = (
        enum_check("actor_type", ActorType),
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_action", "action"),
    )

    actor_type: Mapped[ActorType] = mapped_column(StrEnumType(ActorType), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_label: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # "agent_version.created"
    target_type: Mapped[str] = mapped_column(Text, nullable=False)  # "agent_version"
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)

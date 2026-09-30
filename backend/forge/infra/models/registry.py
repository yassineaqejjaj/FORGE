"""Agent Registry: agents, immutable agent versions, prompt / model / tool configurations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from forge.domain.enums import AdapterKind
from forge.infra.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin
from forge.infra.models._types import StrEnumType, enum_check

_JSON_OBJ = text("'{}'::jsonb")
_JSON_LIST = text("'[]'::jsonb")


def _creator() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ModelConfiguration(UUIDPkMixin, CreatedAtMixin, Base):
    """Immutable model settings (provider, model, version, sampling, pricing)."""

    __tablename__ = "model_configurations"
    __table_args__ = (Index("ix_model_configurations_content_hash", "content_hash"),)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    input_cost_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_cost_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = _creator()


class PromptVersion(UUIDPkMixin, CreatedAtMixin, Base):
    """Immutable prompt text, versioned by name (``product_manager`` v12)."""

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    variables: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = _creator()


class ToolConfiguration(UUIDPkMixin, CreatedAtMixin, Base):
    """Immutable tool set exposed to an agent (name, description, JSON schema of the arguments)."""

    __tablename__ = "tool_configurations"
    __table_args__ = (UniqueConstraint("name", "version"),)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    tools: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = _creator()


class Agent(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (Index("uq_agents_slug", "slug", unique=True),)

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    #: Organisation / product providing the agent ("NOVA", "OpenAI", "Équipe Support"…).
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    owner_id: Mapped[uuid.UUID | None] = _creator()
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=_JSON_LIST)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class AgentVersion(UUIDPkMixin, CreatedAtMixin, Base):
    """Immutable, executable agent version. Any change creates a new version (docs §6.1)."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        enum_check("adapter_kind", AdapterKind),
        UniqueConstraint("agent_id", "version"),
        UniqueConstraint("agent_id", "version_number"),
        Index("ix_agent_versions_content_hash", "content_hash"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)  # human label: "1.4"
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3… (ordering)
    adapter_kind: Mapped[AdapterKind] = mapped_column(StrEnumType(AdapterKind), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_configuration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_configurations.id", ondelete="RESTRICT"), nullable=True
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=True
    )
    #: Resolved system prompt (copy of the prompt version content, or inline prompt).
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    tool_configuration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_configurations.id", ondelete="RESTRICT"), nullable=True
    )
    context_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    memory_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    orchestration_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    #: Non-secret adapter settings (request template, response mapping, NOVA agent id…).
    adapter_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_credentials.id", ondelete="RESTRICT"), nullable=True
    )
    #: ``AgentBudget`` as JSON (max_tokens, max_cost, max_steps, timeout_seconds).
    budget: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    max_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    changelog: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True
    )
    #: Benchmark contamination warnings found at creation (canary / private expected output in prompt).
    contamination: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = _creator()

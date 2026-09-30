"""Scenario Manager: scenarios, immutable scenario versions, datasets, criteria and error taxonomy."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from forge.domain.enums import DatasetKind, Difficulty, Dimension, ErrorSeverity, ScenarioVisibility
from forge.infra.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin
from forge.infra.models._types import StrEnumType, enum_check, range_check

_JSON_OBJ = text("'{}'::jsonb")
_JSON_LIST = text("'[]'::jsonb")


def _creator() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Dataset(UUIDPkMixin, TimestampMixin, Base):
    """Context datasets (documents attached to scenarios) and gold datasets (human calibration)."""

    __tablename__ = "datasets"
    __table_args__ = (enum_check("kind", DatasetKind), Index("uq_datasets_slug", "slug", unique=True))

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[DatasetKind] = mapped_column(StrEnumType(DatasetKind), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=_JSON_LIST)
    created_by: Mapped[uuid.UUID | None] = _creator()


class DatasetItem(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "dataset_items"
    __table_args__ = (
        UniqueConstraint("dataset_id", "key"),
        Index("ix_dataset_items_run_id", "run_id"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    #: Context datasets: ``{"title", "content", "source", "metadata"}``; gold datasets: notes.
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    #: Gold datasets: the evaluation run selected for human calibration.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=True
    )


class Scenario(UUIDPkMixin, TimestampMixin, Base):
    """Stable identity of a scenario (``scenario_prd_001``); content lives in :class:`ScenarioVersion`."""

    __tablename__ = "scenarios"
    __table_args__ = (
        enum_check("visibility", ScenarioVisibility),
        range_check("classification", 0, 3),
        Index("uq_scenarios_slug", "slug", unique=True),
        Index("ix_scenarios_family_id", "family_id"),
        Index("ix_scenarios_category", "category"),
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    #: Variants point to the scenario they derive from; ``family_id`` is the root scenario id.
    parent_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    variant_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[ScenarioVisibility] = mapped_column(
        StrEnumType(ScenarioVisibility),
        nullable=False,
        default=ScenarioVisibility.public,
        server_default=text("'public'"),
    )
    classification: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default=text("1")
    )
    #: FRESH scenarios: date after which the scenario is no longer considered fresh.
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=_JSON_LIST)
    owner_id: Mapped[uuid.UUID | None] = _creator()
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class ScenarioVersion(UUIDPkMixin, CreatedAtMixin, Base):
    """Immutable content of a scenario (docs §6.1). Runs always reference a scenario version."""

    __tablename__ = "scenario_versions"
    __table_args__ = (
        enum_check("difficulty", Difficulty),
        UniqueConstraint("scenario_id", "version"),
        Index("ix_scenario_versions_content_hash", "content_hash"),
    )

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    difficulty: Mapped[Difficulty] = mapped_column(StrEnumType(Difficulty), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    constraints: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    expected_output: Mapped[Any] = mapped_column(JSONB, nullable=True)
    expected_behavior: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    #: ``[{"key", "weight"?, "question"?, "rubric"?}]`` — overrides of catalog criteria; [] = defaults.
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    #: ``RuleSpec`` list as JSON.
    rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    #: ``ToolMock`` list as JSON.
    tool_mocks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    canary: Mapped[str] = mapped_column(Text, nullable=False)
    changelog: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = _creator()


class Criterion(CreatedAtMixin, Base):
    """Criteria catalog (seeded from ``forge.domain.defaults.DEFAULT_CRITERIA``, extensible)."""

    __tablename__ = "criteria"
    __table_args__ = (enum_check("dimension", Dimension),)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    dimension: Mapped[Dimension] = mapped_column(StrEnumType(Dimension), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    rubric: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    scale_min: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default=text("0"))
    scale_max: Mapped[float] = mapped_column(Float, nullable=False, default=5.0, server_default=text("5"))
    builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class ErrorType(CreatedAtMixin, Base):
    """Error taxonomy (built-in codes + custom codes)."""

    __tablename__ = "error_types"
    __table_args__ = (enum_check("default_severity", ErrorSeverity), enum_check("dimension", Dimension))

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    default_severity: Mapped[ErrorSeverity] = mapped_column(StrEnumType(ErrorSeverity), nullable=False)
    dimension: Mapped[Dimension] = mapped_column(StrEnumType(Dimension), nullable=False)
    builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

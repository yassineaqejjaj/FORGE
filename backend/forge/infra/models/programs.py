"""Benchmarks (N scenarios × M agent versions × K repetitions) and experiments (baseline vs candidate)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from forge.domain.enums import ExecutionStatus
from forge.infra.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin
from forge.infra.models._types import StrEnumType, enum_check, range_check

_JSON_OBJ = text("'{}'::jsonb")
_JSON_LIST = text("'[]'::jsonb")


def _creator() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Benchmark(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "benchmarks"
    __table_args__ = (Index("uq_benchmarks_slug", "slug", unique=True), range_check("repetitions", 1, 20))

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    evaluation_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_configs.id", ondelete="RESTRICT"), nullable=False
    )
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=_JSON_LIST)
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_by: Mapped[uuid.UUID | None] = _creator()


class BenchmarkScenario(Base):
    __tablename__ = "benchmark_scenarios"

    benchmark_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmarks.id", ondelete="CASCADE"), primary_key=True
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="RESTRICT"), primary_key=True
    )
    #: Pinned version; ``NULL`` = latest version at each execution.
    scenario_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class BenchmarkAgent(Base):
    __tablename__ = "benchmark_agents"

    benchmark_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmarks.id", ondelete="CASCADE"), primary_key=True
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class BenchmarkExecution(UUIDPkMixin, CreatedAtMixin, Base):
    """One launch of a benchmark: the full matrix of runs plus its aggregated results."""

    __tablename__ = "benchmark_executions"
    __table_args__ = (
        enum_check("status", ExecutionStatus),
        UniqueConstraint("benchmark_id", "number"),
        Index("ix_benchmark_executions_benchmark_id_created_at", "benchmark_id", "created_at"),
    )

    benchmark_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmarks.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(StrEnumType(ExecutionStatus), nullable=False)
    evaluation_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_configs.id", ondelete="RESTRICT"), nullable=False
    )
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Frozen matrix: ``{"scenario_version_ids": [...], "agent_version_ids": [...]}``.
    matrix: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    completed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    failed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    #: Aggregated results (``forge.domain.benchmarks`` output), recomputed by ``finalize_execution``.
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False, default="ui", server_default=text("'ui'"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[uuid.UUID | None] = _creator()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Experiment(UUIDPkMixin, CreatedAtMixin, Base):
    """Baseline vs candidate comparison on the same scenarios (paired), with regression detection."""

    __tablename__ = "experiments"
    __table_args__ = (
        enum_check("status", ExecutionStatus),
        range_check("repetitions", 1, 20),
        Index("ix_experiments_created_at", "created_at"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    baseline_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False
    )
    benchmark_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmarks.id", ondelete="SET NULL"), nullable=True
    )
    evaluation_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_configs.id", ondelete="RESTRICT"), nullable=False
    )
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    status: Mapped[ExecutionStatus] = mapped_column(StrEnumType(ExecutionStatus), nullable=False)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    completed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    failed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    #: Full comparison (``forge.domain.experiments.compare`` output).
    comparison: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Improvement loop: feedback report that motivated the candidate version.
    source_feedback_report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feedback_reports.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=_JSON_LIST)
    trigger: Mapped[str] = mapped_column(Text, nullable=False, default="ui", server_default=text("'ui'"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = _creator()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentScenario(Base):
    __tablename__ = "experiment_scenarios"

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experiments.id", ondelete="CASCADE"), primary_key=True
    )
    scenario_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

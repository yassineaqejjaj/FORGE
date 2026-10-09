"""Evaluation runs, execution traces and trace events."""

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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from forge.domain.enums import (
    EventStatus,
    ExperimentArm,
    RunOrigin,
    RunStatus,
    TraceEventSource,
    TraceEventType,
)
from forge.infra.db import Base, CreatedAtMixin, UUIDPkMixin
from forge.infra.models._types import StrEnumType, enum_check

_JSON_OBJ = text("'{}'::jsonb")
_JSON_LIST = text("'[]'::jsonb")


class EvaluationRun(UUIDPkMixin, CreatedAtMixin, Base):
    """Scenario version + agent version + configuration + trace + evaluations + scores.

    ``manifest`` freezes everything needed to reproduce and compare the run (docs §6.2). It is
    written once when the run is created and never modified.
    """

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        enum_check("status", RunStatus),
        enum_check("origin", RunOrigin),
        enum_check("arm", ExperimentArm),
        Index("ix_evaluation_runs_status", "status"),
        Index("ix_evaluation_runs_created_at", "created_at"),
        Index("ix_evaluation_runs_benchmark_execution_id", "benchmark_execution_id"),
        Index("ix_evaluation_runs_experiment_id_arm", "experiment_id", "arm"),
        Index("ix_evaluation_runs_agent_version_id_created_at", "agent_version_id", "created_at"),
        Index("ix_evaluation_runs_scenario_id", "scenario_id"),
        Index("ix_evaluation_runs_otel_trace_id", "otel_trace_id"),
        #: Idempotency of observed runs: one run per (agent, caller-supplied id).
        Index(
            "uq_evaluation_runs_agent_external_id",
            "agent_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    origin: Mapped[RunOrigin] = mapped_column(StrEnumType(RunOrigin), nullable=False)
    benchmark_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmark_executions.id", ondelete="CASCADE"), nullable=True
    )
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True
    )
    arm: Mapped[ExperimentArm | None] = mapped_column(StrEnumType(ExperimentArm), nullable=True)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    scenario_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False
    )
    evaluation_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_configs.id", ondelete="RESTRICT"), nullable=False
    )
    repetition: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    status: Mapped[RunStatus] = mapped_column(
        StrEnumType(RunStatus), nullable=False, default=RunStatus.pending, server_default=text("'pending'")
    )
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    #: W3C trace id (32 hex) propagated to the agent; OTLP spans with this trace id belong to the run.
    otel_trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: Current evaluation round (re-evaluations increment it; older rounds stay queryable).
    evaluation_round: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: Denormalised current composite (0–100) for the run's own configuration.
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gate_failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=_JSON_LIST)
    #: Idempotency key given by the external system that executed an ``observed`` run (else ``NULL``).
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExecutionTrace(UUIDPkMixin, CreatedAtMixin, Base):
    """Summary of one execution. Messages, tool calls and model calls are ``trace_events`` rows."""

    __tablename__ = "execution_traces"
    __table_args__ = (Index("uq_execution_traces_run_id", "run_id", unique=True),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Exactly what the agent received (``ScenarioSpec.agent_view()`` + prepared context).
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[Any] = mapped_column(JSONB, nullable=True)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    #: ``[{"type", "message", "at"}]`` — execution errors (the agent's own errors are events too).
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class TraceEvent(UUIDPkMixin, CreatedAtMixin, Base):
    """One step of the timeline. ``seq`` is stable and used as the reference in judge prompts."""

    __tablename__ = "trace_events"
    __table_args__ = (
        enum_check("type", TraceEventType),
        enum_check("source", TraceEventSource),
        enum_check("status", EventStatus),
        UniqueConstraint("run_id", "seq"),
        Index("ix_trace_events_run_id_type", "run_id", "type"),
        Index("ix_trace_events_span_id", "span_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trace_events.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[TraceEventType] = mapped_column(StrEnumType(TraceEventType), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[TraceEventSource] = mapped_column(StrEnumType(TraceEventSource), nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        StrEnumType(EventStatus), nullable=False, default=EventStatus.ok, server_default=text("'ok'")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offset_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default=text("0"))
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    input: Mapped[Any] = mapped_column(JSONB, nullable=True)
    output: Mapped[Any] = mapped_column(JSONB, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    span_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_span_id: Mapped[str | None] = mapped_column(Text, nullable=True)

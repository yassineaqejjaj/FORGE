"""Evaluation Engine storage: judges, evaluation configurations, evaluations, scores, errors, feedback.

Principle: *no score without an explanation*. Every ``evaluations`` row is one verdict of one
evaluator on one criterion (individual judge verdicts are always kept); ``scores`` aggregate them
per criterion and link back to the evaluation ids; ``composite_scores`` explain the weighting.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    Dimension,
    ErrorSeverity,
    EvaluatorKind,
    FeedbackScope,
    JudgeProvider,
    ScoreSource,
)
from forge.infra.db import Base, CreatedAtMixin, UUIDPkMixin
from forge.infra.models._types import StrEnumType, enum_check

_JSON_OBJ = text("'{}'::jsonb")
_JSON_LIST = text("'[]'::jsonb")


def _creator() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _run_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )


class Judge(UUIDPkMixin, CreatedAtMixin, Base):
    """Immutable LLM judge version (``key`` + ``version``). Editing a judge creates a new version."""

    __tablename__ = "judges"
    __table_args__ = (
        enum_check("provider", JudgeProvider),
        UniqueConstraint("key", "version"),
        Index("ix_judges_key_is_latest", "key", "is_latest"),
    )

    key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    provider: Mapped[JudgeProvider] = mapped_column(StrEnumType(JudgeProvider), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default=text("0"))
    max_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1500, server_default=text("1500")
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_template: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    criteria: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default=text("1"))
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_credentials.id", ondelete="RESTRICT"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_latest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = _creator()


class EvaluationConfig(UUIDPkMixin, CreatedAtMixin, Base):
    """ScoreConfiguration: weights, normalisation, gates, judges and aggregation (immutable versions)."""

    __tablename__ = "evaluation_configs"
    __table_args__ = (
        UniqueConstraint("key", "version"),
        Index("ix_evaluation_configs_key_is_latest", "key", "is_latest"),
    )

    key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    dimension_weights: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    criterion_weights: Mapped[dict[str, float]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    normalization: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    gates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    #: Pinned judge versions (ids as strings).
    judge_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    aggregation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_JSON_OBJ
    )
    #: Extra criteria keys judged on every scenario.
    criteria: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    #: Rules applied to every scenario (``RuleSpec`` JSON).
    rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    use_human_scores: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    pass_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=70.0, server_default=text("70")
    )
    is_latest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = _creator()


class Evaluation(UUIDPkMixin, CreatedAtMixin, Base):
    """One verdict of one evaluator on one criterion of one run (never an aggregate)."""

    __tablename__ = "evaluations"
    __table_args__ = (
        enum_check("evaluator_kind", EvaluatorKind),
        enum_check("dimension", Dimension),
        CheckConstraint("length(btrim(explanation)) > 0", name="explanation_required"),
        Index("ix_evaluations_run_id_round", "run_id", "round"),
        Index("ix_evaluations_judge_id", "judge_id"),
        Index("ix_evaluations_criterion_key", "criterion_key"),
    )

    run_id: Mapped[uuid.UUID] = _run_fk()
    #: Evaluation round of the run (``NULL`` for human evaluations: they apply to every round).
    round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluation_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_configs.id", ondelete="SET NULL"), nullable=True
    )
    evaluator_kind: Mapped[EvaluatorKind] = mapped_column(StrEnumType(EvaluatorKind), nullable=False)
    evaluator_key: Mapped[str] = mapped_column(Text, nullable=False)
    criterion_key: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[Dimension] = mapped_column(StrEnumType(Dimension), nullable=False)
    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    scale_min: Mapped[float] = mapped_column(Float, nullable=False)
    scale_max: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default=text("1"))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``EvidenceRef`` list (excerpt, trace_event_id, trace_event_seq, location).
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    #: ``DetectedError`` list reported by this evaluator.
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    judge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("judges.id", ondelete="SET NULL"), nullable=True
    )
    judge_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[Any] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    human_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Score(UUIDPkMixin, CreatedAtMixin, Base):
    """Per-criterion score of a run for one configuration and one source (AI and human kept apart)."""

    __tablename__ = "scores"
    __table_args__ = (
        enum_check("dimension", Dimension),
        enum_check("source", ScoreSource),
        CheckConstraint("length(btrim(explanation)) > 0", name="explanation_required"),
        UniqueConstraint("run_id", "round", "evaluation_config_id", "criterion_key", "source"),
        Index("ix_scores_run_id_round", "run_id", "round"),
    )

    run_id: Mapped[uuid.UUID] = _run_fk()
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_configs.id", ondelete="CASCADE"), nullable=False
    )
    criterion_key: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[Dimension] = mapped_column(StrEnumType(Dimension), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)  # 0–1
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[ScoreSource] = mapped_column(StrEnumType(ScoreSource), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    n_evaluations: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: ids of the ``evaluations`` rows aggregated into this score.
    evaluation_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    #: Whether this score was used in the composite (AI vs human preference of the configuration).
    used_in_composite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class CompositeScore(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "composite_scores"
    __table_args__ = (UniqueConstraint("run_id", "round", "evaluation_config_id"),)

    run_id: Mapped[uuid.UUID] = _run_fk()
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_configs.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)  # 0–100 after gates
    raw_value: Mapped[float] = mapped_column(Float, nullable=False)  # 0–100 before gates
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gate_failed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dimensions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    gates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    missing_dimensions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    formula: Mapped[str] = mapped_column(Text, nullable=False)


class RunError(UUIDPkMixin, CreatedAtMixin, Base):
    """Classified error detected on a run (taxonomy code, severity, evidence, evaluator, trace ref)."""

    __tablename__ = "run_errors"
    __table_args__ = (
        enum_check("severity", ErrorSeverity),
        enum_check("evaluator_kind", EvaluatorKind),
        Index("ix_run_errors_run_id_round", "run_id", "round"),
        Index("ix_run_errors_error_type", "error_type"),
    )

    run_id: Mapped[uuid.UUID] = _run_fk()
    #: ``NULL`` for execution errors (independent of evaluation rounds).
    round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str] = mapped_column(
        Text, ForeignKey("error_types.code", ondelete="RESTRICT"), nullable=False
    )
    severity: Mapped[ErrorSeverity] = mapped_column(StrEnumType(ErrorSeverity), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    evaluator_kind: Mapped[EvaluatorKind | None] = mapped_column(StrEnumType(EvaluatorKind), nullable=True)
    evaluator_key: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="SET NULL"), nullable=True
    )
    trace_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trace_events.id", ondelete="SET NULL"), nullable=True
    )
    criterion_key: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeedbackReport(UUIDPkMixin, CreatedAtMixin, Base):
    """Structured, machine-readable feedback (run, benchmark execution or experiment)."""

    __tablename__ = "feedback_reports"
    __table_args__ = (
        enum_check("scope", FeedbackScope),
        Index("ix_feedback_reports_run_id", "run_id"),
        Index("ix_feedback_reports_experiment_id", "experiment_id"),
        Index("ix_feedback_reports_benchmark_execution_id", "benchmark_execution_id"),
    )

    scope: Mapped[FeedbackScope] = mapped_column(StrEnumType(FeedbackScope), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=True
    )
    benchmark_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmark_executions.id", ondelete="CASCADE"), nullable=True
    )
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True
    )
    #: For run scope: the agent version evaluated (benchmark scope: one report per agent version).
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=True
    )
    round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    weaknesses: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    recommendations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    priority_actions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_JSON_LIST
    )
    generator: Mapped[str] = mapped_column(Text, nullable=False)


class JudgeCacheEntry(CreatedAtMixin, Base):
    """Cache of judge answers keyed by (judge content, scenario content, output, trace digest)."""

    __tablename__ = "judge_cache"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    judge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("judges.id", ondelete="CASCADE"), nullable=False
    )
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

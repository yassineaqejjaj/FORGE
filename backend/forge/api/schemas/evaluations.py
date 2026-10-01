"""Schemas of the evaluation endpoints (``/runs/{id}/evaluate|evaluations|scores|errors|feedback``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import (
    Dimension,
    ErrorSeverity,
    EvaluatorKind,
    FeedbackScope,
    JudgeProvider,
    RunStatus,
    ScoreSource,
)


class EvaluateIn(ApiModel):
    evaluation_config_id: uuid.UUID | None = Field(
        default=None, description="Autre configuration d'évaluation (sinon celle du run)"
    )


class EvaluateOut(ApiModel):
    run_id: uuid.UUID
    status: RunStatus
    next_round: int
    job_id: uuid.UUID | None = None
    evaluation_config_id: uuid.UUID


class EvaluationOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    round: int | None = None
    evaluation_config_id: uuid.UUID | None = None
    evaluator_kind: EvaluatorKind
    evaluator_key: str
    criterion_key: str
    dimension: Dimension
    raw_score: float
    scale_min: float
    scale_max: float
    normalized_score: float
    confidence: float
    explanation: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    passed: bool | None = None
    judge_id: uuid.UUID | None = None
    judge_version: int | None = None
    prompt_hash: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    cost: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached: bool = False
    human_user_id: uuid.UUID | None = None
    created_at: datetime
    redacted: bool = False


class RunEvaluationsOut(ApiModel):
    run_id: uuid.UUID
    round: int | None
    rounds: list[int]
    items: list[EvaluationOut]


class ScoreOut(ApiModel):
    id: uuid.UUID
    round: int
    evaluation_config_id: uuid.UUID
    criterion_key: str
    criterion_name: str | None = None
    dimension: Dimension
    value: float
    weight: float
    source: ScoreSource
    confidence: float
    explanation: str
    method: str
    n_evaluations: int
    spread: float | None = None
    evaluation_ids: list[str] = Field(default_factory=list)
    used_in_composite: bool
    redacted: bool = False


class CompositeOut(ApiModel):
    id: uuid.UUID
    round: int
    evaluation_config_id: uuid.UUID
    value: float
    raw_value: float
    passed: bool
    gate_failed: bool
    dimensions: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    missing_dimensions: list[str]
    formula: str
    created_at: datetime


class RunScoresOut(ApiModel):
    run_id: uuid.UUID
    round: int | None
    rounds: list[int]
    status: RunStatus
    evaluation_config_id: uuid.UUID | None = None
    composite: CompositeOut | None = None
    scores: list[ScoreOut]
    status_detail: str | None = None


class RunErrorOut(ApiModel):
    id: uuid.UUID
    round: int | None = None
    error_type: str
    label: str
    severity: ErrorSeverity
    description: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    evaluator_kind: EvaluatorKind | None = None
    evaluator_key: str
    evaluation_id: uuid.UUID | None = None
    trace_event_id: uuid.UUID | None = None
    trace_event_seq: int | None = None
    criterion_key: str | None = None
    created_at: datetime
    redacted: bool = False


class RunErrorsOut(ApiModel):
    run_id: uuid.UUID
    round: int | None
    items: list[RunErrorOut]


class FeedbackReportOut(ApiModel):
    id: uuid.UUID
    scope: FeedbackScope
    run_id: uuid.UUID | None = None
    benchmark_execution_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    agent_version_id: uuid.UUID | None = None
    round: int | None = None
    score: float | None = None
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    errors: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    priority_actions: list[str]
    generator: str
    created_at: datetime
    redacted: bool = False


# --- Provenance ------------------------------------------------------------------------------------


class ProvenanceCriterion(ApiModel):
    key: str
    name: str
    dimension: Dimension
    question: str = ""
    rubric: str = ""
    scale_min: float
    scale_max: float
    weight: float


class ProvenanceJudge(ApiModel):
    id: uuid.UUID | None = None
    key: str
    version: int | None = None
    name: str | None = None
    provider: JudgeProvider | None = None
    model: str | None = None
    weight: float | None = None
    content_hash: str | None = None


class ProvenanceRule(ApiModel):
    id: str
    type: str | None = None
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    weight: float | None = None
    severity: str | None = None
    hidden: bool = False
    source: str = Field(description="scenario | configuration")
    redacted: bool = False


class ProvenanceEvent(ApiModel):
    seq: int
    id: uuid.UUID | None = None
    type: str | None = None
    name: str | None = None


class ProvenancePrompt(ApiModel):
    prompt_hash: str | None = None
    system: str | None = None
    user: str | None = None
    available: bool = False


class ProvenanceEvaluator(ApiModel):
    evaluation: EvaluationOut
    judge: ProvenanceJudge | None = None
    rule: ProvenanceRule | None = None
    metric: dict[str, Any] | None = None
    trace_events: list[ProvenanceEvent] = Field(default_factory=list)
    prompt: ProvenancePrompt | None = None


class ProvenanceAggregation(ApiModel):
    source: ScoreSource
    method: str
    configured_method: str
    weights: dict[str, float] = Field(default_factory=dict)
    expression: str | None = None
    value: float
    confidence: float
    spread: float | None = None
    explanation: str
    individual_verdicts: list[dict[str, Any]] = Field(default_factory=list)


class ProvenanceComposite(ApiModel):
    used_in_composite: bool
    dimension: Dimension
    dimension_value: float | None = None
    dimension_weight: float | None = None
    effective_weight: float | None = None
    criterion_weight: float
    composite: float | None = None
    formula: str | None = None


class ProvenanceOut(ApiModel):
    run_id: uuid.UUID
    round: int
    criterion: ProvenanceCriterion
    evaluation_config: dict[str, Any]
    scores: list[ScoreOut]
    aggregations: list[ProvenanceAggregation]
    evaluators: list[ProvenanceEvaluator]
    composite: ProvenanceComposite | None = None
    errors: list[RunErrorOut] = Field(default_factory=list)
    redacted: bool = False
    prompts_visible: bool = False

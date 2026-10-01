"""Human review schemas (``/reviews/queue``, ``/runs/{id}/human-evaluations``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import Dimension, RunOrigin, RunStatus


class ReviewCriterion(ApiModel):
    key: str
    dimension: str | None = None
    name: str | None = None
    question: str | None = None
    rubric: str | None = None
    scale_min: float | None = None
    scale_max: float | None = None


class ReviewQueueItem(ApiModel):
    run_id: uuid.UUID
    status: RunStatus
    origin: RunOrigin
    scenario_id: uuid.UUID
    scenario_slug: str
    scenario_name: str
    visibility: str
    classification: int
    agent_version_id: uuid.UUID
    agent_label: str | None = None
    created_at: datetime
    blind: bool
    composite_score: float | None = Field(default=None, description="Masqué en mode aveugle")
    ai_scores: dict[str, float] | None = Field(
        default=None, description="Scores IA (0–1), masqués en aveugle"
    )
    max_spread: float | None = Field(default=None, description="Désaccord maximal des juges (priorité)")
    min_confidence: float | None = None
    criteria: list[ReviewCriterion]


class HumanScoreIn(ApiModel):
    criterion_key: str = Field(min_length=3, max_length=80)
    score: float = Field(description="Sur l'échelle du critère (souvent 0–5)")
    comment: str | None = Field(default=None, max_length=5000)


class HumanEvaluationIn(ApiModel):
    scores: list[HumanScoreIn] = Field(min_length=1, max_length=50)
    comment: str | None = Field(default=None, max_length=10_000)


class HumanEvaluationOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    evaluator_key: str
    criterion_key: str
    dimension: Dimension
    score: float
    scale_min: float
    scale_max: float
    normalized_score: float
    explanation: str
    created_at: datetime
    redacted: bool = False


class HumanEvaluationSubmitOut(ApiModel):
    run_id: uuid.UUID
    evaluations: list[HumanEvaluationOut]
    composite_score: float | None = None
    rescored: bool
    detail: dict[str, Any] = Field(default_factory=dict)

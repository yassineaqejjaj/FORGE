"""Schemas of ``/evaluation-configs`` (ScoreConfiguration versions and previews)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import JudgeProvider

_KEY = r"^[a-z0-9][a-z0-9._-]{1,79}$"


class ConfigBehaviourIn(ApiModel):
    dimension_weights: dict[str, float] | None = Field(default=None, description="Poids par dimension")
    criterion_weights: dict[str, float] | None = None
    normalization: dict[str, Any] | None = Field(
        default=None,
        description="cost_target, cost_max, latency_target_ms, latency_max_ms, robustness_max_std",
    )
    gates: list[dict[str, Any]] | None = Field(default=None, description="Garde-fous (GateSpec)")
    judge_ids: list[uuid.UUID] | None = Field(default=None, description="Versions de juges épinglées")
    aggregation: dict[str, Any] | None = Field(default=None, description="{method, weights, expression}")
    criteria: list[str] | None = Field(default=None, description="Critères jugés sur tous les scénarios")
    rules: list[dict[str, Any]] | None = Field(
        default=None, description="Règles appliquées à tous les scénarios"
    )
    use_human_scores: bool | None = None
    pass_threshold: float | None = Field(default=None, ge=0, le=100)

    def behaviour(self) -> dict[str, Any]:
        data = self.model_dump(exclude_unset=True, include=set(ConfigBehaviourIn.model_fields))
        if data.get("judge_ids") is not None:
            data["judge_ids"] = [str(j) for j in data["judge_ids"]]
        return {k: v for k, v in data.items() if v is not None}


class ConfigCreateIn(ConfigBehaviourIn):
    key: str = Field(pattern=_KEY)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    dimension_weights: dict[str, float]
    is_default: bool = False


class ConfigVersionIn(ConfigBehaviourIn):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    is_default: bool | None = None


class ConfigJudgeOut(ApiModel):
    id: uuid.UUID
    key: str
    version: int
    name: str
    provider: JudgeProvider
    model: str
    enabled: bool
    is_latest: bool
    weight: float


class ConfigOut(ApiModel):
    id: uuid.UUID
    key: str
    version: int
    name: str
    description: str
    dimension_weights: dict[str, float]
    criterion_weights: dict[str, float]
    normalization: dict[str, Any]
    gates: list[dict[str, Any]]
    judge_ids: list[str]
    aggregation: dict[str, Any]
    criteria: list[str]
    rules: list[dict[str, Any]]
    use_human_scores: bool
    pass_threshold: float
    is_latest: bool
    is_default: bool
    content_hash: str
    created_by: uuid.UUID | None = None
    created_at: datetime


class ConfigVersionSummary(ApiModel):
    id: uuid.UUID
    version: int
    is_latest: bool
    is_default: bool
    content_hash: str
    created_at: datetime


class ConfigDetailOut(ConfigOut):
    judges: list[ConfigJudgeOut] = Field(default_factory=list)
    versions: list[ConfigVersionSummary] = Field(default_factory=list)


class PreviewIn(ApiModel):
    run_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    benchmark_execution_id: uuid.UUID | None = None
    overrides: ConfigBehaviourIn | None = Field(
        default=None, description="Modifications non enregistrées à prévisualiser"
    )


class PreviewItemOut(ApiModel):
    run_id: uuid.UUID
    scenario_name: str
    agent_label: str
    before: float | None = None
    after: float
    delta: float | None = None
    passed_before: bool | None = None
    passed_after: bool
    gate_failed_before: bool
    gate_failed_after: bool
    formula: str
    dimensions: list[dict[str, Any]] = Field(default_factory=list)


class PreviewOut(ApiModel):
    config_id: uuid.UUID
    items: list[PreviewItemOut]
    skipped: list[dict[str, str]]
    mean_before: float | None = None
    mean_after: float | None = None
    pass_rate_before: float | None = None
    pass_rate_after: float | None = None
    notes: list[str] = Field(default_factory=list)

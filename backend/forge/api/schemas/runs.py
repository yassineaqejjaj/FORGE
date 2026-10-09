"""Evaluation run schemas (``/runs``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from forge.api.schemas.common import ApiModel
from forge.domain.enums import ExperimentArm, RunOrigin, RunStatus


class RunCreateIn(ApiModel):
    agent_version_id: uuid.UUID
    scenario_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=500, description="Dernière version"
    )
    scenario_version_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    repetitions: int = Field(default=1, ge=1, le=20)
    evaluation_config_id: uuid.UUID | None = Field(
        default=None, description="Configuration par défaut si absente"
    )
    tags: list[str] = Field(default_factory=list, max_length=20)


class ObservedUsageIn(ApiModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)


class ObservedRunIn(ApiModel):
    """A run already executed by an external system (docs/OBSERVED_RUNS.md): FORGE only evaluates it."""

    agent_version_id: uuid.UUID
    scenario_id: uuid.UUID = Field(description="La version courante du scénario est utilisée")
    evaluation_config_id: uuid.UUID | None = Field(
        default=None, description="Configuration par défaut (celle des runs ad hoc) si absente"
    )
    input: dict[str, Any] = Field(
        description='Ce qui a été demandé à l\'agent : {"prompt": …, "context": {…}}'
    )
    output_text: str | None = Field(default=None, description="Résumé lisible de ce qui a été produit")
    output_json: dict[str, Any] | None = Field(
        default=None, description="Résultat structuré, lu par les règles du scénario (chemins JSON)"
    )
    execution_status: Literal["completed", "failed"]
    error: str | None = Field(default=None, max_length=4000, description="Cause de l'échec (si failed)")
    started_at: AwareDatetime
    completed_at: AwareDatetime
    usage: ObservedUsageIn = Field(default_factory=ObservedUsageIn)
    tags: list[str] = Field(default_factory=list, max_length=20)
    external_id: str = Field(
        min_length=1,
        max_length=200,
        description="Clé d'idempotence (ex. « nova-sdlc:<uuid> ») : unique par agent",
    )

    @field_validator("external_id")
    @classmethod
    def _strip_external_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("la clé d'idempotence ne doit pas être vide")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at doit être postérieur ou égal à started_at")
        if self.execution_status == "completed" and self.error:
            raise ValueError("« error » n'est accepté que pour un run en échec (execution_status = failed)")
        return self


class RunOut(ApiModel):
    id: uuid.UUID
    status: RunStatus
    status_detail: str | None = None
    origin: RunOrigin
    arm: ExperimentArm | None = None
    repetition: int
    tags: list[str]
    external_id: str | None = Field(default=None, description="Clé d'idempotence (runs observés)")
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    scenario_slug: str
    scenario_name: str
    scenario_version: int | None = None
    category: str
    difficulty: str | None = None
    visibility: str
    classification: int
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    agent_name: str | None = None
    agent_version: str | None = None
    agent_label: str | None = None
    model: str | None = None
    evaluation_config_id: uuid.UUID
    evaluation_round: int
    composite_score: float | None = None
    passed: bool | None = None
    gate_failed: bool
    error_type: str | None = None
    latency_ms: float | None = None
    cost: float | None = None
    total_tokens: int | None = None
    benchmark_execution_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunScenarioOut(ApiModel):
    id: uuid.UUID
    version_id: uuid.UUID
    slug: str
    name: str
    version: int | None = None
    category: str
    difficulty: str | None = None
    visibility: str
    classification: int
    classification_warning: str | None = None
    family_id: str | None = None
    variant_label: str | None = None
    tags: list[str] = Field(default_factory=list)
    content: dict[str, Any] = Field(
        description="Contenu du scénario figé dans le manifeste (masqué si privé)"
    )


class RunCompositeOut(ApiModel):
    round: int
    value: float
    raw_value: float
    passed: bool
    gate_failed: bool
    dimensions: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    missing_dimensions: list[str]
    formula: str


class RunCountsOut(ApiModel):
    evaluations: int
    errors: int
    human_evaluations: int


class RunDetailOut(ApiModel):
    id: uuid.UUID
    status: RunStatus
    status_detail: str | None = None
    origin: RunOrigin
    arm: ExperimentArm | None = None
    repetition: int
    tags: list[str]
    external_id: str | None = None
    error: str | None = None
    error_type: str | None = None
    otel_trace_id: str
    manifest_hash: str
    evaluation_round: int
    composite_score: float | None = None
    passed: bool | None = None
    gate_failed: bool
    created_by: uuid.UUID | None = None
    created_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    executed_at: datetime | None = None
    evaluated_at: datetime | None = None
    finished_at: datetime | None = None
    redacted: bool
    scenario: RunScenarioOut
    agent: dict[str, Any]
    evaluation_config: dict[str, Any]
    trace: dict[str, Any] | None = None
    composite: RunCompositeOut | None = None
    counts: RunCountsOut
    feedback_report_id: uuid.UUID | None = None
    benchmark_execution_id: uuid.UUID | None = None
    benchmark_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    experiment_name: str | None = None


class RunTraceOut(ApiModel):
    run_id: uuid.UUID
    status: RunStatus
    redacted: bool
    trace: dict[str, Any] | None = None
    events: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    model_calls: list[dict[str, Any]]


class RunManifestOut(ApiModel):
    run_id: str
    manifest_hash: str
    redacted: bool
    manifest: dict[str, Any]

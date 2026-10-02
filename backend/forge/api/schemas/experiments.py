"""Schemas of the experiments API (docs/ARCHITECTURE.md §9.3, §12).

``ComparisonOut`` mirrors :class:`forge.domain.experiments.ExperimentComparison`: composite and
dimensions in points (0–100), deltas in points, rates on 0–1, relative changes as ratios.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from forge.api.schemas.benchmarks import AgentVersionRefOut
from forge.api.schemas.common import ApiModel
from forge.domain.enums import ExecutionStatus, ExperimentArm, Recommendation, RegressionSeverity, Verdict


class ExperimentCreateIn(BaseModel):
    baseline_version_id: uuid.UUID
    candidate_version_id: uuid.UUID
    benchmark_id: str | None = Field(default=None, description="Identifiant ou slug du benchmark source")
    scenario_ids: list[uuid.UUID] | None = Field(default=None, description="Scénarios (dernière version)")
    scenario_version_ids: list[uuid.UUID] | None = Field(
        default=None, description="Versions de scénarios exactes"
    )
    evaluation_config_id: uuid.UUID | None = None
    repetitions: int | None = Field(
        default=None, ge=1, le=20, description="Défaut : celles du benchmark, sinon 1"
    )
    name: str | None = Field(default=None, max_length=200)
    description: str = ""
    hypothesis: str = ""
    tags: list[str] = Field(default_factory=list)
    source_feedback_report_id: uuid.UUID | None = None
    trigger: str = Field(default="ui", max_length=40)

    @model_validator(mode="after")
    def _source(self) -> ExperimentCreateIn:
        if not (self.benchmark_id or self.scenario_ids or self.scenario_version_ids):
            raise ValueError("indiquez benchmark_id, scenario_ids ou scenario_version_ids")
        return self


class ExperimentOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    hypothesis: str
    status: ExecutionStatus
    baseline: AgentVersionRefOut | None = None
    candidate: AgentVersionRefOut | None = None
    baseline_version_id: uuid.UUID
    candidate_version_id: uuid.UUID
    benchmark_id: uuid.UUID | None = None
    benchmark_name: str | None = None
    evaluation_config_id: uuid.UUID
    repetitions: int
    n_scenarios: int
    total_runs: int
    completed_runs: int
    failed_runs: int
    progress: float
    recommendation: Recommendation | None = None
    recommendation_label: str | None = None
    confidence: str | None = None
    composite_delta: float | None = None
    source_feedback_report_id: uuid.UUID | None = None
    tags: list[str]
    trigger: str
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    created_by: uuid.UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExperimentScenarioOut(ApiModel):
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    version: int
    slug: str
    name: str
    category: str
    visibility: str
    classification: int
    position: int


class ExperimentDetailOut(ExperimentOut):
    scenarios: list[ExperimentScenarioOut]
    hidden_scenarios: int = 0
    summary: str | None = Field(default=None, description="Phrase de synthèse de la recommandation")


# --- Comparison (mirror of forge.domain.experiments) -------------------------------------------------


class MetricComparisonOut(ApiModel):
    key: str
    label: str
    n_pairs: int
    baseline_mean: float | None = None
    candidate_mean: float | None = None
    delta: float | None = None
    delta_pct: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    prob_improvement: float | None = None
    verdict: Verdict


class ResourceComparisonOut(ApiModel):
    key: str
    label: str
    unit: str
    n_pairs: int
    baseline_mean: float | None = None
    candidate_mean: float | None = None
    delta: float | None = None
    relative_change: float | None = None
    p_value: float | None = None
    assessment: str = Field(description="gain | loss | stable | unknown (une baisse est un gain)")


class ScenarioChangeOut(ApiModel):
    scenario_id: str
    scenario_version_id: str
    slug: str
    name: str
    category: str
    difficulty: str
    visibility: str
    n_baseline: int
    n_candidate: int
    baseline_mean: float | None = None
    candidate_mean: float | None = None
    delta: float | None = None
    noise_std: float
    noise_estimated: bool
    threshold: float
    status: str = Field(description="regression | improvement | stable | unpaired")
    severity: RegressionSeverity | None = None
    baseline_gate_failures: int = 0
    candidate_gate_failures: int = 0
    new_critical_errors: list[str] = Field(default_factory=list)
    resolved_critical_errors: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ErrorChangeOut(ApiModel):
    error_type: str
    baseline_count: int
    candidate_count: int
    baseline_rate: float | None = None
    candidate_rate: float | None = None
    delta_rate: float | None = None
    max_severity: str
    change: str = Field(description="appeared | disappeared | increased | decreased | stable")


class ErrorsComparisonOut(ApiModel):
    appeared: list[str]
    disappeared: list[str]
    changes: list[ErrorChangeOut]
    baseline_error_rate: float | None = None
    candidate_error_rate: float | None = None


class ArmSummaryOut(ApiModel):
    arm: ExperimentArm
    agent_version_id: str | None = None
    agent_label: str
    n_runs: int
    n_scored: int
    n_failed: int
    n_cancelled: int
    composite_mean: float | None = None
    pass_rate: float | None = None
    gate_failure_rate: float | None = None
    error_rate: float | None = None
    robustness: float | None = None


class RobustnessComparisonOut(ApiModel):
    baseline: float | None = None
    candidate: float | None = None
    delta: float | None = None


class NoiseInfoOut(ApiModel):
    pooled_std: float | None = None
    dof: int
    repetitions: int
    default_std: float


class RecommendationOut(ApiModel):
    recommendation: Recommendation
    label: str
    confidence: str = Field(description="high | medium | low")
    confidence_label: str
    summary: str
    reasons: list[str]


class ComparisonStatisticsOut(ApiModel):
    confidence: float
    n_resamples: int
    seed: int
    alpha: float
    method: str
    significance_test: str
    unit: str
    equivalence_delta: float
    equivalence_margin: float
    min_regression_delta: float


class ComparisonOut(ApiModel):
    experiment_id: uuid.UUID
    status: ExecutionStatus
    schema_: str = Field(alias="schema", serialization_alias="schema")
    baseline: ArmSummaryOut
    candidate: ArmSummaryOut
    n_pairs: int
    n_unpaired: int
    composite: MetricComparisonOut
    dimensions: list[MetricComparisonOut]
    #: Per-criterion comparison (absent from comparisons computed before this field existed).
    criteria: list[MetricComparisonOut] = Field(default_factory=list)
    resources: list[ResourceComparisonOut]
    scenarios: list[ScenarioChangeOut]
    regressions: list[ScenarioChangeOut]
    improvements: list[ScenarioChangeOut]
    errors: ErrorsComparisonOut
    robustness: RobustnessComparisonOut
    noise: NoiseInfoOut
    recommendation: RecommendationOut
    warnings: list[str]
    statistics: ComparisonStatisticsOut
    feedback_report_id: uuid.UUID | None = None
    generated_at: datetime | None = None
    provisional: bool = Field(default=False, description="Calcul provisoire (expérience non finalisée)")
    restricted: bool = False
    hidden_scenarios: int = 0


class GateOut(ApiModel):
    experiment_id: uuid.UUID
    passed: bool
    recommendation: Recommendation | None = None
    status: ExecutionStatus
    strict: bool
    confidence: str | None = None
    summary: str | None = None
    reasons: list[str]
    composite_delta: float | None = None
    regressions: int = 0

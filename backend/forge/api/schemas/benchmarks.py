"""Schemas of the benchmarks API (docs/ARCHITECTURE.md §9.1, §12).

``BenchmarkSummaryOut`` mirrors :class:`forge.domain.benchmarks.BenchmarkSummary` (stored as JSON in
``benchmark_executions.summary``): composites on 0–100, dimensions / rates / robustness on 0–1.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import ExecutionStatus

GroupBy = Literal[
    "agent",
    "version",
    "model",
    "scenario",
    "category",
    "difficulty",
    "visibility",
    "family",
    "error_type",
    "date",
]


# --- Inputs ------------------------------------------------------------------------------------------


class ScenarioSelectionIn(BaseModel):
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID | None = Field(
        default=None, description="Version épinglée ; absente = dernière version à chaque lancement"
    )


class BenchmarkCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    description: str = ""
    evaluation_config_id: uuid.UUID | None = Field(
        default=None, description="Défaut : configuration par défaut"
    )
    repetitions: int = Field(default=1, ge=1, le=20)
    scenarios: list[ScenarioSelectionIn] = Field(min_length=1)
    agent_version_ids: list[uuid.UUID] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class BenchmarkUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = None
    evaluation_config_id: uuid.UUID | None = None
    repetitions: int | None = Field(default=None, ge=1, le=20)
    scenarios: list[ScenarioSelectionIn] | None = Field(default=None, min_length=1)
    agent_version_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    archived: bool | None = None


class BenchmarkRunIn(BaseModel):
    trigger: str = Field(default="ui", max_length=40, description="Origine du lancement : ui, ci, api, seed…")


# --- Benchmarks --------------------------------------------------------------------------------------


class ExecutionBriefOut(ApiModel):
    id: uuid.UUID
    number: int
    status: ExecutionStatus
    total_runs: int
    completed_runs: int
    failed_runs: int
    created_at: datetime
    finished_at: datetime | None = None


class BenchmarkOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    evaluation_config_id: uuid.UUID
    repetitions: int
    tags: list[str]
    archived: bool
    n_scenarios: int
    n_agents: int
    n_executions: int
    last_execution: ExecutionBriefOut | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class BenchmarkScenarioOut(ApiModel):
    scenario_id: uuid.UUID
    slug: str
    name: str
    category: str
    visibility: str
    classification: int
    archived: bool
    scenario_version_id: uuid.UUID | None = None
    pinned_version: int | None = None
    latest_version: int
    position: int


class AgentVersionRefOut(ApiModel):
    agent_version_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    agent_slug: str
    version: str
    label: str
    content_hash: str
    position: int | None = None


class BenchmarkDetailOut(BenchmarkOut):
    scenarios: list[BenchmarkScenarioOut]
    agents: list[AgentVersionRefOut]
    hidden_scenarios: int = Field(
        default=0, description="Scénarios au-dessus de votre habilitation (non affichés)"
    )
    evaluation_config_name: str | None = None


# --- Summary (mirror of forge.domain.benchmarks) -----------------------------------------------------


class ScoreStatsOut(ApiModel):
    n: int
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None


class MetricStatsOut(ApiModel):
    n: int
    mean: float | None = None
    median: float | None = None
    p95: float | None = None
    total: float | None = None


class FamilyRobustnessOut(ApiModel):
    family_id: str
    label: str
    n_runs: int
    n_scenarios: int
    std: float
    robustness: float


class RobustnessOut(ApiModel):
    value: float | None = None
    n_families: int = 0
    families: list[FamilyRobustnessOut] = Field(default_factory=list)


class GeneralisationOut(ApiModel):
    public_mean: float | None = None
    private_mean: float | None = None
    fresh_mean: float | None = None
    hidden_mean: float | None = None
    gap: float | None = None
    n_public: int = 0
    n_hidden: int = 0
    alert: bool = False


class LeaderComparisonOut(ApiModel):
    n_pairs: int
    delta: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    significant: bool | None = None


class AgentAggregateOut(ApiModel):
    agent_version_id: str
    agent_id: str
    agent_label: str
    model: str | None = None
    rank: int
    n_runs: int
    n_scored: int
    n_completed: int
    n_failed: int
    n_cancelled: int
    composite: ScoreStatsOut
    group_composite: float | None = None
    pass_rate: float | None = None
    gate_failure_rate: float | None = None
    error_rate: float | None = None
    dimensions: dict[str, float]
    cost: MetricStatsOut
    latency: MetricStatsOut
    tokens: MetricStatsOut
    errors_by_type: dict[str, int]
    errors_by_severity: dict[str, int]
    robustness: RobustnessOut
    generalisation: GeneralisationOut
    vs_leader: LeaderComparisonOut | None = None


class RankingEntryOut(ApiModel):
    rank: int
    agent_version_id: str
    agent_label: str
    group_composite: float | None = None
    composite_mean: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    pass_rate: float | None = None
    delta_to_leader: float | None = None
    significant_gap: bool | None = None


class BestEntryOut(ApiModel):
    dimension: str
    label: str
    agent_version_id: str
    agent_label: str
    value: float


class ScenarioRefOut(ApiModel):
    scenario_id: str
    scenario_version_id: str
    slug: str
    name: str
    category: str
    difficulty: str
    visibility: str
    family_id: str


class AgentRefOut(ApiModel):
    agent_version_id: str
    agent_id: str
    label: str
    model: str | None = None


class MatrixCellOut(ApiModel):
    scenario_id: str
    scenario_version_id: str
    agent_version_id: str
    n_runs: int
    n_scored: int
    composite_mean: float | None = None
    composite_std: float | None = None
    pass_rate: float | None = None
    gate_failures: int
    error_count: int
    error_types: list[str]
    cost_mean: float | None = None
    latency_mean: float | None = None


class MatrixOut(ApiModel):
    scenarios: list[ScenarioRefOut] = Field(default_factory=list)
    agents: list[AgentRefOut] = Field(default_factory=list)
    cells: list[MatrixCellOut] = Field(default_factory=list)


class GroupRowOut(ApiModel):
    key: str
    label: str
    n_runs: int
    n_scored: int
    composite_mean: float | None = None
    composite_ci_low: float | None = None
    composite_ci_high: float | None = None
    pass_rate: float | None = None
    gate_failure_rate: float | None = None
    cost_mean: float | None = None
    latency_mean: float | None = None
    tokens_mean: float | None = None
    error_count: int
    runs_with_errors: int
    by_agent: dict[str, float | None] = Field(default_factory=dict)


class ErrorTypeRowOut(ApiModel):
    error_type: str
    count: int
    runs_affected: int
    max_severity: str
    by_severity: dict[str, int]
    by_agent: dict[str, int]


class TotalsOut(ApiModel):
    n_runs: int = 0
    n_scored: int = 0
    n_completed: int = 0
    n_failed: int = 0
    n_cancelled: int = 0
    n_pending: int = 0
    n_scenarios: int = 0
    n_agents: int = 0
    repetitions: int = 0


class StatisticsInfoOut(ApiModel):
    confidence: float
    n_resamples: int
    seed: int
    method: str
    significance_test: str
    alpha: float


class BenchmarkSummaryOut(ApiModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    totals: TotalsOut
    dimension_weights: dict[str, float]
    statistics: StatisticsInfoOut
    agents: list[AgentAggregateOut]
    ranking: list[RankingEntryOut]
    best_by_dimension: list[BestEntryOut]
    matrix: MatrixOut
    by_category: list[GroupRowOut]
    by_difficulty: list[GroupRowOut]
    by_model: list[GroupRowOut]
    by_family: list[GroupRowOut]
    by_visibility: list[GroupRowOut]
    by_date: list[GroupRowOut]
    by_error_type: list[ErrorTypeRowOut]
    feedback_reports: dict[str, str] = Field(
        default_factory=dict, description="Rapport de feedback benchmark par version d'agent"
    )
    generated_at: datetime | None = None
    restricted: bool = Field(default=False, description="Résumé limité aux scénarios de votre habilitation")
    hidden_scenarios: int = 0


# --- Executions --------------------------------------------------------------------------------------


class ExecutionOut(ExecutionBriefOut):
    benchmark_id: uuid.UUID
    benchmark_name: str | None = None
    benchmark_slug: str | None = None
    evaluation_config_id: uuid.UUID
    repetitions: int
    trigger: str
    error: str | None = None
    triggered_by: uuid.UUID | None = None
    started_at: datetime | None = None
    progress: float = Field(description="Part des runs terminés (0–1)")
    n_scenarios: int
    n_agents: int


class ExecutionDetailOut(ExecutionOut):
    matrix: dict[str, list[str] | list[bool] | int]
    summary: BenchmarkSummaryOut | None = None


class CancelOut(ApiModel):
    detail: str
    cancelled_runs: int


class ResultsOut(ApiModel):
    benchmark_id: uuid.UUID
    execution_id: uuid.UUID
    execution_number: int
    execution_status: ExecutionStatus
    group_by: GroupBy
    filters: dict[str, str | None]
    n_runs: int
    restricted: bool
    agents: dict[str, str]
    rows: list[GroupRowOut]
    errors: list[ErrorTypeRowOut]

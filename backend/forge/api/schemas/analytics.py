"""Schemas of the dashboard and errors explorer (docs/ARCHITECTURE.md §12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import ErrorSeverity, ExecutionStatus, Recommendation


class DashboardCountsOut(ApiModel):
    agents: int
    agent_versions: int
    scenarios: int
    runs: int = Field(description="Runs créés sur la période")


class DashboardKpisOut(ApiModel):
    average_composite: float | None = None
    pass_rate: float | None = None
    error_rate: float | None = Field(default=None, description="Runs évalués avec au moins une erreur")
    failure_rate: float | None = Field(default=None, description="Runs en échec / runs terminés")
    average_cost: float | None = None
    total_cost: float | None = None
    average_latency_ms: float | None = None
    evaluated_runs: int
    reliability_rate: float | None = Field(
        default=None, description="Évaluations sans erreur critique ni garde-fou déclenché / évaluations"
    )
    completed_runs: int
    interrupted_runs: int = Field(description="Exécutions en échec technique (statut failed)")
    gate_failed_runs: int = Field(description="Évaluations dont un garde-fou a été déclenché")
    critical_error_runs: int = Field(description="Évaluations avec au moins une erreur critique")


class PreviousKpisOut(ApiModel):
    """Same indicators over the previous window of the same length (variations)."""

    runs: int
    evaluated_runs: int
    average_composite: float | None = None
    pass_rate: float | None = None
    reliability_rate: float | None = None
    error_rate: float | None = None
    average_cost: float | None = None
    average_latency_ms: float | None = None


class AttentionExperimentOut(ApiModel):
    id: uuid.UUID
    name: str
    critical_regressions: int


class DashboardAttentionOut(ApiModel):
    experiments_with_regression: int
    latest_regression: AttentionExperimentOut | None
    gate_failed_runs: int
    interrupted_runs: int
    critical_error_runs: int
    critical_errors: list[TopErrorOut]


class TrendPointOut(ApiModel):
    date: str
    runs: int
    completed: int
    failed: int
    average_composite: float | None = None
    pass_rate: float | None = None
    error_rate: float | None = None
    average_cost: float | None = None
    average_latency_ms: float | None = None


class TopErrorOut(ApiModel):
    error_type: str
    label: str
    count: int
    runs_affected: int
    max_severity: ErrorSeverity


class RecentExecutionOut(ApiModel):
    id: uuid.UUID
    benchmark_id: uuid.UUID
    benchmark_name: str
    number: int
    status: ExecutionStatus
    total_runs: int
    completed_runs: int
    failed_runs: int
    created_at: datetime
    finished_at: datetime | None = None
    leader_label: str | None = None
    leader_score: float | None = None


class RecentExperimentOut(ApiModel):
    id: uuid.UUID
    name: str
    status: ExecutionStatus
    baseline_label: str | None = None
    candidate_label: str | None = None
    recommendation: Recommendation | None = None
    confidence: str | None = None
    composite_delta: float | None = None
    regressions: int
    critical_regressions: int
    total_runs: int
    completed_runs: int
    failed_runs: int
    created_at: datetime


class DashboardOut(ApiModel):
    days: int
    since: datetime
    generated_at: datetime
    counts: DashboardCountsOut
    runs_by_status: dict[str, int]
    kpis: DashboardKpisOut
    trends: list[TrendPointOut]
    top_error_types: list[TopErrorOut]
    recent_benchmark_executions: list[RecentExecutionOut]
    recent_experiments: list[RecentExperimentOut]
    queue_depth: dict[str, int]
    agent_id: uuid.UUID | None
    first_activity: datetime | None
    previous_kpis: PreviousKpisOut | None
    attention: DashboardAttentionOut
    error_types_total: int
    comparisons_completed: int


class ErrorScenarioOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    category: str
    visibility: str
    classification: int


class ErrorAgentOut(ApiModel):
    id: uuid.UUID
    name: str


class ErrorAgentVersionOut(ApiModel):
    id: uuid.UUID
    version: str
    label: str


class ErrorItemOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    error_type: str
    label: str
    severity: ErrorSeverity
    description: str
    evidence: list[dict[str, Any]]
    criterion_key: str | None = None
    evaluator_kind: str | None = None
    evaluator_key: str
    trace_event_id: uuid.UUID | None = None
    trace_event_seq: int | None = None
    round: int | None = None
    created_at: datetime
    run_status: str
    origin: str
    benchmark_execution_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    scenario: ErrorScenarioOut
    agent: ErrorAgentOut
    agent_version: ErrorAgentVersionOut
    redacted: bool = False


class ErrorTypeCountOut(ApiModel):
    error_type: str
    label: str
    count: int
    runs_affected: int


class ErrorAgentVersionCountOut(ApiModel):
    agent_version_id: uuid.UUID
    label: str
    count: int
    runs_affected: int


class ErrorScenarioCountOut(ApiModel):
    scenario_id: uuid.UUID
    slug: str
    name: str
    count: int
    runs_affected: int


class ErrorAggregationsOut(ApiModel):
    total: int
    runs_affected: int
    critical: int
    by_type: list[ErrorTypeCountOut]
    by_severity: dict[str, int]
    by_agent_version: list[ErrorAgentVersionCountOut]
    by_scenario: list[ErrorScenarioCountOut]


class ErrorsPageOut(ApiModel):
    items: list[ErrorItemOut]
    total: int
    page: int
    page_size: int
    aggregations: ErrorAggregationsOut


class ResultsAgentRowOut(ApiModel):
    agent_version_id: str
    agent_id: str
    agent_label: str
    model: str | None = None
    n_runs: int
    n_scored: int
    n_failed: int
    composite_mean: float | None = None
    composite_ci_low: float | None = None
    composite_ci_high: float | None = None
    pass_rate: float | None = None
    gate_failure_rate: float | None = None
    error_rate: float | None = None
    dimensions: dict[str, float] = Field(default_factory=dict)
    cost_mean: float | None = None
    latency_mean: float | None = None
    latency_p95: float | None = None
    tokens_mean: float | None = None
    errors_by_type: dict[str, int] = Field(default_factory=dict)


class ResultsErrorRowOut(ApiModel):
    error_type: str
    count: int
    runs_affected: int
    max_severity: str
    by_severity: dict[str, int] = Field(default_factory=dict)


class ResultsOverviewOut(ApiModel):
    days: int
    since: datetime
    n_runs: int
    truncated: bool
    agents: list[ResultsAgentRowOut]
    errors: list[ResultsErrorRowOut]


DashboardAttentionOut.model_rebuild()


class QueueActivityOut(ApiModel):
    queued: int = 0
    running: int = 0


class WorkerActivityOut(ApiModel):
    """Technical activity of the workers (Exécutions page, not the overview)."""

    queues: dict[str, QueueActivityOut]
